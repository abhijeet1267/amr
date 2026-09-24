"""C6 — obstacle avoidance policy (Layer 3).

This module decides *what to do about a non-critical obstacle*; it never
touches motors, serial or GPIO. The only thing it produces is a
:class:`~amr.safety.safety_manager.SafetyDecision` carrying the already
reserved :attr:`~amr.safety.safety_manager.SafetyAction.TURN` / ``REPLAN``
actions, which the existing motion system
(:class:`amr.navigation.navigator.LocalNavigator`) then honours.

Why this is a policy and not a second safety controller
-----------------------------------------------------
The hazard layer (3.5) already separates the two cases for us, using the
thresholds that are *already* configured in ``config/hazard.yaml``:

* an ``OBSTACLE`` reading that is ``CRITICAL`` (or any EMERGENCY/STOP state)
  makes ``RobotManager`` enforce an immediate ``STOP`` — that path is
  untouched by C6 and keeps absolute priority;
* an ``OBSTACLE`` reading that is merely ``WARNING`` does **not** block
  motion, so the robot would otherwise drive straight into it. That is the
  case C6 activates.

So C6 adds no new severity, no new state machine and no new thresholds. It
promotes two reserved enum members to active use for the already-modelled
"obstacle present, not immediately lethal" situation.

Safety priority (worst outcome always wins)::

    EMERGENCY / proximity STOP        <- highest, unchanged
      ^
      |  TURN / REPLAN
      |
    OBSTACLE warning (no immediate stop)

Any ``STOP`` verdict from Layer 3 (dead comms, no valid data, or a distance
below the stop threshold) short-circuits the whole module: an obstacle can
never upgrade a stop into a turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

from .safety_manager import SafetyAction, SafetyDecision
from ..hazard.types import HazardKind, HazardStatus


class ObstacleSide(str, Enum):
    """Where the obstacle sits relative to the robot's body frame."""

    FRONT = "FRONT"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    REAR = "REAR"
    UNKNOWN = "UNKNOWN"


class AvoidanceAction(str, Enum):
    """What the *navigator* should do (the decision layer's intent).

    Kept separate from :class:`SafetyAction` on purpose: ``SafetyAction``
    describes the safety verdict, this describes the requested manoeuvre.
    :meth:`AvoidancePolicy.decide` maps one onto the other.
    """

    NONE = "NONE"
    TURN = "TURN"
    REPLAN = "REPLAN"
    STOP = "STOP"



@dataclass(frozen=True)
class ObstacleReport:
    """An obstacle observation distilled from the hazard layer.

    This is *evidence*, not a verdict. ``side`` says where it is; nothing
    here invents a world coordinate.
    """

    side: ObstacleSide = ObstacleSide.UNKNOWN
    #: Highest-confidence active obstacle reading (0..1), or ``None``.
    confidence: Optional[float] = None
    #: Free-form origin, e.g. ``camera_front`` / ``ultrasonic``.
    source: str = "hazard"
    #: Set when a previous TURN/REPLAN for this obstacle has already been
    #: exhausted, so the policy escalates to a plain stop instead of looping.
    exhausted: bool = False

    def __post_init__(self) -> None:
        # Malformed evidence must never raise into the control loop. An
        # unrecognised side degrades to UNKNOWN, which the policy treats as
        # "replan" rather than guessing a heading.
        try:
            side = ObstacleSide(self.side)
        except (ValueError, TypeError):
            side = ObstacleSide.UNKNOWN
        object.__setattr__(self, "side", side)
        conf = self.confidence
        if conf is not None:
            try:
                conf = float(conf)
            except (TypeError, ValueError):
                conf = None
            # Out-of-range confidence is treated as absent, never clamped up.
            if conf is not None and not 0.0 <= conf <= 1.0:
                conf = None
            object.__setattr__(self, "confidence", conf)

    @property
    def actionable(self) -> bool:
        """``True`` when the obstacle's position lets us pick a heading.

        An ``UNKNOWN`` side is deliberately not actionable: the robot cannot
        choose a safe heading from it, so the policy escalates to a replan
        rather than guessing a direction.
        """
        return self.side is not ObstacleSide.UNKNOWN


@dataclass(frozen=True)
class AvoidancePolicy:
    """Deterministic obstacle-avoidance policy (pure — no I/O, no state).

    Every field maps to a documented entry in ``config/safety.yaml``'s
    ``avoidance:`` block. All of them are *software defaults*: the project has
    never been driven on a real robot, so none of these numbers is
    experimentally validated (``config/safety.yaml`` remains
    ``status: NOT_VERIFIED``).
    """

    #: Master switch. ``False`` leaves every existing code path unchanged.
    enabled: bool = False
    #: Attempts before an avoidance attempt is declared exhausted.
    max_replans: int = 3
    #: Turn speed fraction and arc duration, applied by the navigator.
    turn_speed_scale: float = 0.5
    turn_duration_s: float = 0.6
    #: Clearance (m) at or below which a candidate side counts as blocked.
    #: With no clearance feed, avoidance never guesses a heading (see
    #: :meth:`choose_turn_side`).
    open_clearance_m: float = 1.0

    @classmethod
    def from_config(cls, config: Any) -> "AvoidancePolicy":
        """Build a policy from an :class:`~amr.utils.config.AvoidanceConfig`.

        Kept duck-typed so this module has no import-time dependency on the
        config package (and therefore no cycle). ``None`` yields a disabled
        policy, so omitting configuration can never enable avoidance.
        """
        if config is None:
            return cls()
        get = lambda name, default: getattr(config, name, default)  # noqa: E731
        return cls(
            enabled=bool(get("enabled", False)),
            max_replans=get("max_replans", 3),
            turn_speed_scale=get("turn_speed_scale", 0.5),
            turn_duration_s=get("turn_duration_s", 0.6),
            open_clearance_m=get("open_clearance_m", 1.0),
        )

    def __post_init__(self) -> None:
        # Configuration is clamped defensively: a bad value in the YAML must
        # degrade to a safe, deterministic default rather than raise at
        # start-up or, worse, be used unclamped on a real robot.
        try:
            replans = int(self.max_replans)
        except (TypeError, ValueError):
            replans = 0
        object.__setattr__(self, "max_replans", max(0, replans))
        try:
            scale = float(self.turn_speed_scale)
        except (TypeError, ValueError):
            scale = 0.0
        object.__setattr__(self, "turn_speed_scale", min(1.0, max(0.0, scale)))
        try:
            duration = float(self.turn_duration_s)
        except (TypeError, ValueError):
            duration = 0.0
        object.__setattr__(self, "turn_duration_s", max(0.0, duration))
        try:
            clearance = float(self.open_clearance_m)
        except (TypeError, ValueError):
            clearance = 0.0
        object.__setattr__(self, "open_clearance_m", max(0.0, clearance))

    # ------------------------------------------------------------------ #
    def decide(
        self,
        base: SafetyDecision,
        obstacle: Optional[ObstacleReport] = None,
        *,
        clearance: Optional[Dict[str, float]] = None,
    ) -> Tuple[SafetyDecision, AvoidanceAction]:
        """Combine the Layer-3 verdict with obstacle evidence.

        Returns ``(decision, avoidance_action)``. Pure: identical inputs always
        produce an identical result, which is what makes C6 testable.
        """
        # 1. Layer 3 always wins. STOP (dead comms / no data / too close) and
        #    WAIT (inside the caution band) are returned untouched: an
        #    obstacle must never convert a stop into a manoeuvre.
        if base.action in (SafetyAction.STOP, SafetyAction.WAIT):
            return base, (
                AvoidanceAction.STOP if base.action is SafetyAction.STOP
                else AvoidanceAction.NONE
            )

        # 2. Nothing to avoid (or the policy is off) -> unchanged behaviour.
        #    Note: an UNKNOWN *side* is still real evidence, so it is NOT
        #    discarded here -- it falls through to choose_turn_side(), which
        #    cannot pick a heading and so escalates to REPLAN. Only a complete
        #    absence of evidence leaves navigation untouched.
        if not self.enabled or obstacle is None:
            return base, AvoidanceAction.NONE

        # 3. Loop guard: this obstacle has already exhausted its replans, so
        #    another manoeuvre would just oscillate. Stop instead.
        if obstacle.exhausted:
            return (
                SafetyDecision(
                    SafetyAction.STOP,
                    ("obstacle avoidance exhausted replan budget",),
                ),
                AvoidanceAction.STOP,
            )

        # 4. Pick a side. Prefer a clear side; fall back to REPLAN when the
        #    obstacle is not to one side, or every candidate side is blocked.
        side = self.choose_turn_side(
            obstacle,
            clearance=clearance,
            open_clearance_m=self.open_clearance_m,
        )
        if side is None:
            return (
                SafetyDecision(
                    SafetyAction.REPLAN,
                    (f"obstacle {obstacle.side.value} on path, no clear side",),
                ),
                AvoidanceAction.REPLAN,
            )
        return (
            SafetyDecision(
                SafetyAction.TURN,
                (f"obstacle {obstacle.side.value} on path, "
                 f"steering {side.value}",),
            ),
            AvoidanceAction.TURN,
        )

    # ------------------------------------------------------------------ #
    @classmethod
    def choose_turn_side(
        cls,
        obstacle: ObstacleReport,
        *,
        clearance: Optional[Dict[str, float]] = None,
        open_clearance_m: float = 1.0,
    ) -> Optional[ObstacleSide]:
        """Return the side to steer toward, or ``None`` to replan instead.

        A turn is only proposed when the target side is *known clear* — i.e.
        its measured clearance exceeds ``open_clearance_m``. With no clearance
        data we defer to REPLAN rather than guessing: inventing a turn
        direction from an unsensed direction would be exactly the kind of
        unverified assumption this project avoids.
        """
        if not obstacle.actionable:
            return None
        if obstacle.side is ObstacleSide.LEFT:
            candidates = (ObstacleSide.RIGHT,)
        elif obstacle.side is ObstacleSide.RIGHT:
            candidates = (ObstacleSide.LEFT,)
        elif obstacle.side is ObstacleSide.FRONT:
            # Pick the roomier side so the turn is the shorter one.
            candidates = (ObstacleSide.LEFT, ObstacleSide.RIGHT)
        else:
            # UNKNOWN / REAR: we cannot reason about a safe heading.
            return None

        if clearance is None:
            return None
        try:
            threshold = float(open_clearance_m)
        except (TypeError, ValueError):
            return None
        best: Optional[Tuple[float, ObstacleSide]] = None
        for candidate in candidates:
            distance = clearance.get(candidate.value)
            if distance is None or isinstance(distance, bool):
                continue
            try:
                distance = float(distance)
            except (TypeError, ValueError):
                continue
            # NaN fails every comparison, so an explicit check is required:
            # a NaN reading must never be mistaken for infinite clearance.
            if distance != distance:
                continue
            if distance <= threshold:
                continue  # blocked (or unreadable) — not a candidate
            if best is None or distance > best[0]:
                best = (distance, candidate)
        return best[1] if best is not None else None


# --------------------------------------------------------------------------- #
# Hazard-layer adapter
# --------------------------------------------------------------------------- #
#: Maps a perception source name onto a body-frame side. A vision detection
#: only knows *which camera* saw the object; a camera mounted at the front of
#: the robot corresponds to FRONT. Unmapped names stay UNKNOWN, which the
#: policy treats as "replan, do not guess".
_SOURCE_SIDES = {
    "camera_front": ObstacleSide.FRONT,
    "camera_rear": ObstacleSide.REAR,
    "camera_left": ObstacleSide.LEFT,
    "camera_right": ObstacleSide.RIGHT,
    "front": ObstacleSide.FRONT,
    "rear": ObstacleSide.REAR,
    "left": ObstacleSide.LEFT,
    "right": ObstacleSide.RIGHT,
    "ultrasonic": ObstacleSide.FRONT,
}


def report_from_hazard(
    status: Optional[HazardStatus],
    *,
    exhausted: bool = False,
) -> Optional[ObstacleReport]:
    """Distil active ``OBSTACLE`` evidence out of a hazard snapshot.

    Returns ``None`` when there is nothing actionable to avoid, so callers can
    simply pass the result through to :meth:`AvoidancePolicy.decide`.

    Only ``OBSTACLE`` readings are considered: a ``FIRE`` or ``HUMAN`` hazard
    keeps its own existing escalation path and must not be quietly re-labelled
    as a steerable obstacle.
    """
    if status is None:
        return None
    obstacles = [r for r in status.readings if r.kind is HazardKind.OBSTACLE]
    if not obstacles:
        return None
    # Highest confidence first, then source, for a stable tie-break.
    best = sorted(obstacles, key=lambda r: (-r.value, r.source))[0]
    side = _SOURCE_SIDES.get(best.source, ObstacleSide.UNKNOWN)
    return ObstacleReport(
        side=side,
        confidence=best.value if best.unit == "confidence" else None,
        source=best.source,
        exhausted=exhausted,
    )
