"""Layered safety (Pi side).

* :mod:`amr.safety.safety_manager` — Layer 3: the deterministic Pi-side
  safety decision (docs/safety.md).

Layer 1 (Arduino hardware stop) lives in the firmware; Layer 2 (state) is
:class:`amr.robot.robot_state.RobotState`.
"""

from .safety_manager import (
    CAUTION_FACTOR,
    SafetyAction,
    SafetyDecision,
    SafetyManager,
)

__all__ = [
    "CAUTION_FACTOR",
    "SafetyAction",
    "SafetyDecision",
    "SafetyManager",
]
