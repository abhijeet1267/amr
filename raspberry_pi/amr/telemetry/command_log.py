"""Bounded command execution log for the Command Center.

Every command submitted through the dashboard gets a traceable record. The
design is honest about the difference between *accepted* and *executed*:

* a command is recorded the moment the web layer **accepts** it;
* its ``state`` advances only on evidence the backend actually provides —
  a ``REJECTED``/``FAILED`` verdict from :meth:`RobotManager`, or a successful
  response;
* for motion commands we do **not** claim "the robot moved" from a 200 alone.
  The command is marked ``ACCEPTED``/``SUCCEEDED`` at the protocol level, and a
  separate ``executed`` flag is set only when the robot's state confirms motion
  started (``is_moving`` true immediately after). That distinction is the whole
  point: a successful HTTP response means the command was *taken*, not that a
  wheel turned.

The log is a bounded ring so a long-running console cannot grow without limit.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CommandState(str, Enum):
    """Lifecycle states for a dashboard command.

    Deliberately does NOT assert physical completion for motion: ``SUCCEEDED``
    means the backend accepted and acknowledged the command, not that the robot
    reached a destination. The ``executed`` field carries the (optional)
    confirmation that motion actually began.
    """

    #: Recorded, parameters being checked.
    CREATED = "CREATED"
    #: Parameters checked and the request about to be dispatched.
    VALIDATED = "VALIDATED"
    #: The backend took the command (HTTP request dispatched).
    ACCEPTED = "ACCEPTED"
    #: The backend acknowledged it (200 / ACK), no physical confirmation yet.
    SUCCEEDED = "SUCCEEDED"
    #: The backend rejected it (mode/safety gating, bad parameters).
    REJECTED = "REJECTED"
    #: A transport / runtime error occurred.
    FAILED = "FAILED"
    #: The request did not complete in time.
    TIMED_OUT = "TIMED_OUT"
    #: We do not know what happened (e.g. the connection dropped mid-request).
    UNKNOWN = "UNKNOWN"


# The command names the web layer actually understands (see server.py dispatch).
SUPPORTED_COMMANDS = (
    "forward", "backward", "left", "right", "rotate_left", "rotate_right",
    "rotate", "stop", "estop", "mode",
)


@dataclass
class CommandRecord:
    """One command execution record."""

    command: str
    params: Dict[str, Any]
    state: CommandState
    created_at: float
    #: Correlation id so the frontend can match a record to its request.
    command_id: str
    #: When the backend acknowledged the command, if it did.
    acknowledged_at: Optional[float] = None
    #: When the command's final state was reached.
    completed_at: Optional[float] = None
    #: Backend response body / reason.
    response: Optional[Any] = None
    #: Error detail, for REJECTED/FAILED/TIMED_OUT.
    error: Optional[str] = None
    #: True only when the robot's state confirms motion actually began.
    executed: Optional[bool] = None
    #: SIMULATION / HARDWARE — which mode the command ran against.
    environment: str = "HARDWARE"
    #: The robot mode after the command, if known.
    robot_mode_after: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "params": self.params,
            "state": self.state.value,
            "command_id": self.command_id,
            "created_at": self.created_at,
            "acknowledged_at": self.acknowledged_at,
            "completed_at": self.completed_at,
            "response": self.response,
            "error": self.error,
            "executed": self.executed,
            "environment": self.environment,
            "robot_mode_after": self.robot_mode_after,
            "duration_ms": (
                round((self.completed_at or self.acknowledged_at
                       or self.created_at) - self.created_at, 3) * 1000
            ),
        }


class CommandLog:
    """A bounded, append-only record of dashboard commands."""

    def __init__(self, maxlen: int = 200):
        self._maxlen = maxlen
        self._records: List[CommandRecord] = []
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"cmd-{self._counter:06d}"

    def create(
        self, command: str, params: Dict[str, Any], environment: str = "HARDWARE"
    ) -> CommandRecord:
        rec = CommandRecord(
            command=command,
            params=dict(params or {}),
            state=CommandState.CREATED,
            created_at=time.time(),
            command_id=self._next_id(),
            environment=environment,
        )
        self._records.append(rec)
        self._trim()
        return rec

    def _trim(self) -> None:
        if len(self._records) > self._maxlen:
            del self._records[: len(self._records) - self._maxlen]

    def _find(self, command_id: str) -> Optional[CommandRecord]:
        for rec in reversed(self._records):
            if rec.command_id == command_id:
                return rec
        return None

    # -- state transitions -------------------------------------------------- #
    def mark_validated(self, command_id: str) -> None:
        rec = self._find(command_id)
        if rec is not None:
            rec.state = CommandState.VALIDATED

    def mark_accepted(self, command_id: str) -> None:
        rec = self._find(command_id)
        if rec is not None and rec.state in (
            CommandState.CREATED, CommandState.VALIDATED,
        ):
            rec.state = CommandState.ACCEPTED

    def mark_succeeded(
        self,
        command_id: str,
        response: Optional[Any] = None,
        *,
        executed: Optional[bool] = None,
        robot_mode_after: Optional[str] = None,
    ) -> None:
        """The backend acknowledged the command (200 / ACK).

        ``executed`` is set only when the caller verified via robot state that
        motion actually started; otherwise it stays ``None`` (unknown) rather
        than a fabricated ``True``.
        """
        rec = self._find(command_id)
        if rec is None:
            return
        rec.state = CommandState.SUCCEEDED
        rec.acknowledged_at = time.time()
        rec.completed_at = rec.acknowledged_at
        rec.response = response
        rec.executed = executed
        rec.robot_mode_after = robot_mode_after

    def mark_rejected(
        self, command_id: str, error: str, response: Optional[Any] = None
    ) -> None:
        rec = self._find(command_id)
        if rec is None:
            return
        rec.state = CommandState.REJECTED
        rec.completed_at = time.time()
        rec.error = error
        rec.response = response

    def mark_failed(self, command_id: str, error: str) -> None:
        rec = self._find(command_id)
        if rec is None:
            return
        rec.state = CommandState.FAILED
        rec.completed_at = time.time()
        rec.error = error

    def mark_timed_out(self, command_id: str) -> None:
        rec = self._find(command_id)
        if rec is None:
            return
        rec.state = CommandState.TIMED_OUT
        rec.completed_at = time.time()
        rec.error = "request did not complete in time"

    def mark_unknown(self, command_id: str, error: str = "unknown outcome") -> None:
        rec = self._find(command_id)
        if rec is None:
            return
        rec.state = CommandState.UNKNOWN
        rec.completed_at = time.time()
        rec.error = error

    # -- queries ------------------------------------------------------------ #
    def latest(self, limit: int = 50) -> List[CommandRecord]:
        """Most recent first, bounded."""
        return list(reversed(self._records[-limit:]))

    def get(self, command_id: str) -> Optional[CommandRecord]:
        return self._find(command_id)

    def count_by_state(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for rec in self._records:
            out[rec.state.value] = out.get(rec.state.value, 0) + 1
        return out

    def to_dict(self, limit: int = 50) -> Dict[str, Any]:
        return {
            "commands": [r.to_dict() for r in self.latest(limit)],
            "counts": self.count_by_state(),
            "total": len(self._records),
        }
