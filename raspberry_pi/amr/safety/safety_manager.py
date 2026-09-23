"""Layer-3 safety manager (Pi side) — deterministic, no heuristics.

Implements exactly what docs/safety.md promises: *immediate, deterministic
safety stops*. Aggressive obstacle avoidance is intentionally NOT here.

Higher-level code (web control, navigation, warehouse tasks) **must** call
:meth:`SafetyManager.check` (or :meth:`SafetyManager.can_move`) before
issuing any motion command and must obey a ``STOP`` immediately.

Decision vocabulary (docs/safety.md, Layer 3)::

    PROCEED — no action needed
    WAIT    — approaching a threshold: pause / slow down
    STOP    — motion must stop immediately
    TURN / REPLAN — reserved for future obstacle avoidance; the current
              deterministic rules never emit them

Rule order (first match wins, worst outcome always wins)::

    1. controller disconnected            -> STOP
    2. no valid sensor data at all        -> STOP
    3. any valid reading < stop threshold -> STOP
    4. any valid reading < CAUTION_FACTOR * threshold -> WAIT
    5. otherwise                          -> PROCEED

A reading of ``None`` (invalid / no echo) is ignored *per direction* — a
clear path is not an obstacle (Layer 1 rule). But a complete loss of valid
sensor data is treated as unsafe (rule 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from ..sensors.ultrasonic import UltrasonicReading
from ..utils.config import SafetyConfig

#: WAIT threshold = CAUTION_FACTOR x stop threshold (documented default).
CAUTION_FACTOR = 2.0


class SafetyAction(Enum):
    """What the robot must do right now."""

    PROCEED = "PROCEED"
    WAIT = "WAIT"
    STOP = "STOP"
    TURN = "TURN"      # reserved — never emitted by the current rules
    REPLAN = "REPLAN"  # reserved — never emitted by the current rules


@dataclass(frozen=True)
class SafetyDecision:
    """A frozen, inspectable safety verdict."""

    action: SafetyAction
    reasons: Tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        """Motion is permitted only on ``PROCEED``."""
        return self.action is SafetyAction.PROCEED

    @property
    def caution(self) -> bool:
        return self.action is SafetyAction.WAIT

    def __str__(self) -> str:  # pragma: no cover - debug aid
        if self.reasons:
            return f"{self.action.value} ({'; '.join(self.reasons)})"
        return self.action.value


_DIRS = ("front", "left", "right", "rear")


class SafetyManager:
    """Deterministic Pi-side safety policy built from :class:`SafetyConfig`."""

    def __init__(self, config: SafetyConfig):
        self._cfg = config

    def check(
        self,
        reading: Optional[UltrasonicReading],
        connected: bool,
    ) -> SafetyDecision:
        """Evaluate the current situation. Pure function — no I/O, no state."""
        # 1. Communication health has priority over everything.
        if not connected:
            return SafetyDecision(
                SafetyAction.STOP, ("comm link to controller lost",)
            )

        # 2. Blindness is unsafe.
        if reading is None or reading.all_invalid():
            return SafetyDecision(SafetyAction.STOP, ("no valid sensor data",))

        stops: list[str] = []
        cautions: list[str] = []
        for name in _DIRS:
            dist = getattr(reading, name)
            if dist is None:
                continue  # invalid per direction: ignore (Layer 1 rule)
            stop_at = getattr(self._cfg, f"{name}_stop_distance_cm")
            if dist < stop_at:
                stops.append(f"{name} {dist}cm < {stop_at}cm")
            elif dist < CAUTION_FACTOR * stop_at:
                cautions.append(
                    f"{name} {dist}cm < {CAUTION_FACTOR:g}x{stop_at}cm"
                )

        if stops:
            return SafetyDecision(SafetyAction.STOP, tuple(stops))
        if cautions:
            return SafetyDecision(SafetyAction.WAIT, tuple(cautions))
        return SafetyDecision(SafetyAction.PROCEED, ())

    def can_move(self, reading: Optional[UltrasonicReading], connected: bool) -> bool:
        """Convenience predicate: may motion be commanded right now?"""
        return self.check(reading, connected).allowed
