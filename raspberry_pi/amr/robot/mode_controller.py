"""Robot mode state machine (Phase 9).

Enforces the transitions documented in docs/safety.md:

* ``SAFETY_STOP`` is reachable from **any** mode (deterministic, forced).
* Leaving ``SAFETY_STOP`` / ``ERROR`` requires an explicit operator reset
  (back to ``IDLE`` only — never directly into motion).
* ``AUTONOMOUS`` is only reachable from ``MANUAL`` (the operator must
  first have the robot under manual control).
"""

from __future__ import annotations

from typing import FrozenSet

from .robot_state import RobotMode


class ModeTransitionError(Exception):
    """A requested mode transition is not allowed by the state machine."""


#: Allowed *requested* transitions (safety_stop/reset are handled separately).
_ALLOWED: dict[RobotMode, FrozenSet[RobotMode]] = {
    RobotMode.IDLE: frozenset(
        {RobotMode.MANUAL, RobotMode.SAFETY_STOP, RobotMode.ERROR}
    ),
    RobotMode.MANUAL: frozenset(
        {
            RobotMode.IDLE,
            RobotMode.AUTONOMOUS,
            RobotMode.SAFETY_STOP,
            RobotMode.ERROR,
        }
    ),
    RobotMode.AUTONOMOUS: frozenset(
        {
            RobotMode.IDLE,
            RobotMode.MANUAL,
            RobotMode.SAFETY_STOP,
            RobotMode.ERROR,
        }
    ),
    RobotMode.SAFETY_STOP: frozenset({RobotMode.IDLE}),
    RobotMode.ERROR: frozenset({RobotMode.IDLE}),
}


class ModeController:
    """Owns the current :class:`RobotMode` and validates transitions.

    The robot manager (Phase 8) is the only expected owner; it consults the
    safety manager *before* calling :meth:`request`.
    """

    def __init__(self, initial: RobotMode = RobotMode.IDLE):
        self._mode = initial

    @property
    def mode(self) -> RobotMode:
        return self._mode

    def can_transition(self, target: RobotMode) -> bool:
        return target is self._mode or target in _ALLOWED[self._mode]

    def request(self, target: RobotMode) -> RobotMode:
        """Transition to ``target`` if allowed; idempotent for the same mode."""
        if target is self._mode:
            return self._mode
        if target not in _ALLOWED[self._mode]:
            raise ModeTransitionError(
                f"illegal mode transition {self._mode.value} -> {target.value}"
            )
        self._mode = target
        return self._mode

    def safety_stop(self) -> RobotMode:
        """Forced transition to ``SAFETY_STOP`` from any mode (idempotent)."""
        self._mode = RobotMode.SAFETY_STOP
        return self._mode

    def reset(self) -> RobotMode:
        """Operator acknowledgement: ``SAFETY_STOP``/``ERROR`` -> ``IDLE``."""
        if self._mode not in (RobotMode.SAFETY_STOP, RobotMode.ERROR):
            raise ModeTransitionError(
                f"reset only valid from SAFETY_STOP/ERROR, not {self._mode.value}"
            )
        self._mode = RobotMode.IDLE
        return self._mode
