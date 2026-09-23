"""Warehouse task model + manipulator interface (Phase 16).

A :class:`Task` is one unit of work: travel to a named map location and
optionally perform a manipulation (pick / place). The :class:`Manipulator`
protocol is the seam where real gripper/ARM hardware plugs in; a
:class:`MockManipulator` records the actions so the whole pick -> place ->
return pipeline is testable with no end-effector present.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

_id_counter = itertools.count(1)


def _next_id() -> str:
    return f"task-{next(_id_counter):04d}"


class TaskType(str, Enum):
    """Kinds of warehouse work."""

    MOVE = "move"                  # travel to a location
    PICK = "pick"                  # travel to a location + pick the payload
    PLACE = "place"                # travel to a location + place the payload
    RETURN_TO_DOCK = "return_to_dock"  # travel back to the dock


class TaskStatus(str, Enum):
    """Lifecycle of a single task."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """One unit of warehouse work."""

    task_type: TaskType
    location: str
    payload_id: Optional[str] = None
    task_id: str = field(default_factory=_next_id)
    status: TaskStatus = field(default_factory=lambda: TaskStatus.PENDING)
    created_at: float = field(default_factory=time.time)
    attempts: int = 0
    last_error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "type": self.task_type.value,
            "location": self.location,
            "payload_id": self.payload_id,
            "status": self.status.value,
            "attempts": self.attempts,
            "last_error": self.last_error,
        }


class QueueFullError(Exception):
    """Raised when a task is submitted to a full queue."""


@dataclass
class TaskResult:
    """Terminal outcome of a task."""

    task_id: str
    status: TaskStatus
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "error": self.error,
        }


# --------------------------------------------------------------------------- #
# Manipulator (gripper/ARM) seam
# --------------------------------------------------------------------------- #
@runtime_checkable
class Manipulator(Protocol):
    """End-effector contract. Real hardware plugs in here."""

    def pick(self, payload_id: str) -> bool:
        """Attempt to pick ``payload_id``. Return True on success."""
        ...

    def place(self, payload_id: str) -> bool:
        """Attempt to place ``payload_id``. Return True on success."""
        ...

    def has_payload(self) -> bool:
        ...

    def reset(self) -> None:
        ...


class MockManipulator:
    """Records picks/places; carries at most one payload at a time."""

    def __init__(self) -> None:
        self.payload: Optional[str] = None
        self.picks = 0
        self.places = 0

    def pick(self, payload_id: str) -> bool:
        if self.payload is not None:
            return False  # already carrying something
        self.payload = payload_id
        self.picks += 1
        return True

    def place(self, payload_id: str) -> bool:
        if self.payload is None:
            return False  # nothing to place
        self.payload = None
        self.places += 1
        return True

    def has_payload(self) -> bool:
        return self.payload is not None

    def reset(self) -> None:
        self.payload = None


class NullManipulator:
    """No end-effector: pick/place are no-ops that report success."""

    def pick(self, payload_id: str) -> bool:
        return True

    def place(self, payload_id: str) -> bool:
        return True

    def has_payload(self) -> bool:
        return False

    def reset(self) -> None:
        pass


def make_manipulator(name: Optional[str] = "mock") -> Manipulator:
    """Factory: ``"null"`` -> :class:`NullManipulator`, else mock."""
    if (name or "mock").lower() == "null":
        return NullManipulator()
    return MockManipulator()
