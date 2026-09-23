"""Geometry and goal types for the navigation layer (Phase 12).

Pure math + frozen dataclasses. No ROS, no hardware — this module imports
anywhere in the stack and is exercised by the unit tests directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict


def wrap_angle(a: float) -> float:
    """Wrap an angle in radians to the half-open range ``(-pi, pi]``."""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def distance(p: "Pose", q: "Pose") -> float:
    """Planar (x, y) distance between two poses, in metres."""
    return math.hypot(q.x - p.x, q.y - p.y)


@dataclass(frozen=True)
class Pose:
    """A 2D pose in the world frame: ``x``/``y`` in metres, ``theta`` in radians."""

    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y, "theta": self.theta}

    @classmethod
    def from_dict(cls, d: dict) -> "Pose":
        return cls(
            float(d.get("x", 0.0)),
            float(d.get("y", 0.0)),
            float(d.get("theta", 0.0)),
        )


@dataclass(frozen=True)
class Goal:
    """A navigation goal: a target pose plus a name for logging/status."""

    pose: Pose
    name: str = "goal"

    @classmethod
    def named(cls, name: str, pose: Pose) -> "Goal":
        return cls(pose=pose, name=name)


class NavStatus(str, Enum):
    """Lifecycle of one navigation attempt."""

    IDLE = "IDLE"
    MOVING = "MOVING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class NavResult:
    """Outcome of a navigation attempt (for blocking-style callers)."""

    status: NavStatus
    pose: Pose
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "pose": self.pose.to_dict(),
            "error": self.error,
        }
