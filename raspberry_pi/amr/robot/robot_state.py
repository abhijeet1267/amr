"""Robot logical state model (mode + snapshot).

Foundation for the robot manager (Phase 8) and the mode state machine
(Phase 9). The manager *owns* the :class:`RobotState` instance and mutates
it on the control loop; every other layer (web UI, warehouse tasks, safety)
*reads* it.

Mode state machine (full spec in docs/safety.md)::

    IDLE ──> MANUAL ──> AUTONOMOUS
       └────┴──────────┴──> SAFETY_STOP   (sensor / comm / watchdog fault)
       └────└──────────└──> ERROR         (unrecoverable, needs a human)
    SAFETY_STOP / ERROR ──> IDLE          (only after an explicit human reset)

Transition *enforcement* lives in the robot manager; this module only
defines the vocabulary and a couple of read-only predicates.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RobotMode(Enum):
    """Logical operating mode of the robot."""

    IDLE = "IDLE"
    MANUAL = "MANUAL"
    AUTONOMOUS = "AUTONOMOUS"
    SAFETY_STOP = "SAFETY_STOP"
    ERROR = "ERROR"

    @property
    def is_safe_to_move(self) -> bool:
        """``True`` only in modes where motion commands are allowed."""
        return self in (RobotMode.MANUAL, RobotMode.AUTONOMOUS)


@dataclass
class RobotState:
    """A snapshot of robot mode, motion, and sensor state.

    Plain value object — no I/O. Sensor distances are ``None`` until the
    first valid reading arrives (``-1`` from a sensor means "no echo" and is
    normalised to ``None`` by the telemetry layer).
    """

    mode: RobotMode = RobotMode.IDLE
    connected: bool = False
    left_speed: int = 0
    right_speed: int = 0
    front_cm: Optional[int] = None
    left_cm: Optional[int] = None
    right_cm: Optional[int] = None
    rear_cm: Optional[int] = None
    last_error: Optional[str] = None
    updated_at: float = field(default_factory=time.time)

    @property
    def is_moving(self) -> bool:
        return self.left_speed != 0 or self.right_speed != 0

    def to_dict(self) -> dict:
        """JSON-friendly snapshot (for the web UI / logging)."""
        return {
            "mode": self.mode.value,
            "connected": self.connected,
            "left_speed": self.left_speed,
            "right_speed": self.right_speed,
            "front_cm": self.front_cm,
            "left_cm": self.left_cm,
            "right_cm": self.right_cm,
            "rear_cm": self.rear_cm,
            "last_error": self.last_error,
            "is_moving": self.is_moving,
            "updated_at": self.updated_at,
        }
