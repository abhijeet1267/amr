"""Warehouse task model + manipulator interface (Phase 16).

A :class:`Task` is one unit of work: travel to a named map location and
optionally perform a manipulation (pick / place). The :class:`Manipulator`
protocol is the seam where real gripper/ARM hardware plugs in; a
:class:`MockManipulator` records the actions so the whole pick -> place ->
return pipeline is testable with no end-effector present.

C16 adds the real-backend side of that seam: a :class:`GripperActuator`
protocol (dependency-injected physical I/O) and the
:class:`GripperManipulator` driver that consumes it, selected by
``warehouse.manipulator: "gripper"``. **No gripper hardware ships with this
repository** — the factory refuses to construct that backend without an
injected actuator, so configuring it can never silently degrade into the mock
pretending to pick.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, Tuple, runtime_checkable

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


# --------------------------------------------------------------------------- #
# C16 — real gripper backend (hardware behind an injected actuator)
# --------------------------------------------------------------------------- #
@runtime_checkable
class GripperActuator(Protocol):
    """Physical gripper I/O. The seam real hardware plugs into.

    Dependency-injected the same way as ``amr.hazard.sources.HazardSource``
    and ``amr.rfid.reader.RfidReader``: the actuator wraps whatever actually
    drives the gripper (a servo library, a serial command to a future
    firmware verb), so nothing here talks to a bus itself and the whole path
    is testable with no hardware attached.

    ``close()`` / ``open()`` return ``True`` **only when the hardware
    confirms the action completed** — on real hardware that means a limit
    switch or current-sense reading, not merely that a command was sent.
    ``holding()`` is a cross-check: ``True``/``False`` when the gripper can
    sense a payload, ``None`` when it has no presence sensor.
    """

    def close(self) -> bool:
        """Close the gripper. True only on hardware confirmation."""
        ...

    def open(self) -> bool:
        """Open the gripper. True only on hardware confirmation."""
        ...

    def holding(self) -> Optional[bool]:
        """Presence feedback: True/False, or None when not instrumented."""
        ...


class GripperManipulator:
    """End-effector driver backed by an injected :class:`GripperActuator` (C16).

    **No gripper hardware exists in this repository** — no servo, no arm, no
    firmware verb. What ships here is the driver: the carry-at-most-one rules
    (mirroring :class:`MockManipulator`), hardware-confirmation semantics, and
    a recorded ``last_error`` explaining every refusal. The actuator supplies
    the physical I/O; tests supply a fake.

    Honest-failure rules (do not weaken):

    * An unconfirmed ``close()``/``open()`` is a **failed** pick/place — a
      command sent is not a motion that happened, the same distinction RFID
      draws between a read tag and no answer.
    * ``holding()`` feedback that contradicts the action fails it too: closed
      on nothing is not a pick, open while still gripping is not a place.
    * An actuator that raises never crashes the task loop — the exception is
      captured in ``last_error`` and the action reports ``False``.
    """

    def __init__(self, actuator: GripperActuator) -> None:
        if actuator is None:
            raise ValueError(
                "GripperManipulator requires an actuator; no gripper hardware is "
                "bundled — inject one (GripperManipulator(actuator)) or configure "
                "the 'mock' / 'null' backend"
            )
        self._actuator = actuator
        self.payload: Optional[str] = None
        self.picks = 0
        self.places = 0
        self.last_error: Optional[str] = None

    def _call(self, method: str) -> Optional[bool]:
        """Invoke ``actuator.<method>()``; ``None`` when it raised or is absent."""
        fn = getattr(self._actuator, method, None)
        if fn is None:
            self.last_error = f"actuator has no {method}()"
            return None
        try:
            return bool(fn())
        except Exception as exc:  # noqa: BLE001 - hardware must not kill the loop
            self.last_error = f"actuator {method}() raised: {exc}"
            return None

    def _feedback(self) -> Optional[bool]:
        """Payload presence, or ``None`` when the gripper is not instrumented."""
        fn = getattr(self._actuator, "holding", None)
        if fn is None:
            return None
        try:
            value = fn()
        except Exception:  # noqa: BLE001 - a broken sensor must not crash a task
            return None
        return None if value is None else bool(value)

    def pick(self, payload_id: str) -> bool:
        if self.payload is not None:
            self.last_error = f"already carrying {self.payload!r}"
            return False
        closed = self._call("close")          # None = raised / method absent
        if closed is not True:
            if closed is False:
                # The actuator answered "not confirmed" without saying why.
                self.last_error = "gripper close not confirmed by actuator"
            return False                      # keep _call's specific reason
        if self._feedback() is False:
            self.last_error = "gripper reports holding nothing after close"
            return False
        self.payload = payload_id
        self.picks += 1
        self.last_error = None
        return True

    def place(self, payload_id: str) -> bool:
        if self.payload is None:
            self.last_error = "not carrying anything"
            return False
        if payload_id is not None and self.payload != payload_id:
            # Releasing here would drop whatever is actually held at a station
            # that asked for a different box — refuse before the jaws move.
            self.last_error = (
                f"asked to place {payload_id!r} but carrying {self.payload!r}"
            )
            return False
        opened = self._call("open")
        if opened is not True:
            if opened is False:
                self.last_error = "gripper open not confirmed by actuator"
            return False
        if self._feedback() is True:
            self.last_error = "gripper still reports holding payload after open"
            return False
        self.payload = None
        self.places += 1
        self.last_error = None
        return True

    def has_payload(self) -> bool:
        return self.payload is not None

    def reset(self) -> None:
        """Drop local carry state (an operator action — never a claim that the
        physical gripper opened)."""
        self.payload = None
        self.last_error = None


#: Backend names :func:`make_manipulator` understands. One source of truth so
#: the factory, ``_validate_warehouse`` and the docs cannot drift apart.
MANIPULATOR_BACKENDS: Tuple[str, ...] = ("null", "mock", "gripper")


def make_manipulator(
    name: Optional[str] = "mock",
    actuator: Optional["GripperActuator"] = None,
) -> Manipulator:
    """Factory for the configured ``warehouse.manipulator`` backend.

    * ``"null"`` — :class:`NullManipulator` (no end-effector).
    * ``"mock"`` (default) — :class:`MockManipulator`, records picks/places.
    * ``"gripper"`` — :class:`GripperManipulator`, **and it requires an
      ``actuator``**: failing loudly here is the whole point. A gripper
      backend that silently fell back to the mock would let an operator
      believe real hardware is picking while nothing moves — the same silent
      no-op C17 rejects when tags are configured against a ``null`` reader.
    * anything else — ``ValueError``, naming the known backends.

    ``actuator`` is ignored by the ``null``/``mock`` backends: only the real
    backend does physical I/O, so the other two must not become constructible
    gates for hardware they never drive.
    """
    backend = (name or "mock").strip().lower()
    if backend in ("null", "none"):
        return NullManipulator()
    if backend == "mock":
        return MockManipulator()
    if backend == "gripper":
        if actuator is None:
            raise ValueError(
                'warehouse.manipulator "gripper" requires a GripperActuator: no '
                "gripper hardware is bundled with this repository. Inject one via "
                "GripperManipulator(actuator) passed to "
                "WarehouseTaskManager.create(..., manipulator=...), or configure "
                '"mock" / "null"'
            )
        return GripperManipulator(actuator)
    raise ValueError(
        f"unknown manipulator backend {backend!r}; "
        f"known: {sorted(MANIPULATOR_BACKENDS)}"
    )
