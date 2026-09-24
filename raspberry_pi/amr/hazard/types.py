"""Vocabulary for the context-aware multi-hazard safety layer.

This module defines **only data**: enumerations and frozen value objects. It has
no I/O, no hardware access and no third-party dependencies, so it can be
imported from anywhere in the stack (and tested in isolation).

Relationship to the existing layered safety model (docs/safety.md)
-----------------------------------------------------------------
The repository already ships three safety layers: the Arduino hardware stop
(Layer 1), the Pi-side state (Layer 2) and the deterministic proximity policy
(Layer 3, :class:`amr.safety.safety_manager.SafetyManager`).

This package adds a **hazard layer** that sits *alongside* Layer 3. It is an
additional, independent input: it can only ever **escalate** the outcome, never
relax it. It never talks to the motors — every motion decision still passes the
single gated :class:`amr.robot.robot_manager.RobotManager` API.

Hazard states (worst wins)
--------------------------
``NORMAL``
    No hazard observed. Full speed permitted.
``WARNING``
    A hazard is present but below its stop threshold. Full speed permitted,
    the operator is notified.
``SLOW``
    A hazard requires reduced speed. Motion continues at
    ``slow_speed_scale`` x the commanded speed.
``STOP``
    A hazard requires an immediate stop. Motion is vetoed.
``EMERGENCY``
    A life-safety hazard (fire / gas / smoke, configurable). Motion is vetoed
    **and the state latches**: it persists until an operator calls
    ``acknowledge()``, mirroring the ``SAFETY_STOP`` semantics in docs/safety.md.

Import hygiene
--------------
This module deliberately does **not** import :mod:`amr.robot` or
:mod:`amr.navigation`. Locations are accepted as any object carrying ``x``,
``y``/``theta`` attributes (duck typing via :meth:`HazardLocation.from_any`) so
that ``amr.hazard`` can be imported from the robot manager without a circular
import.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


class HazardKind(str, Enum):
    """What kind of hazard a reading describes."""

    GAS = "GAS"                    # combustible / toxic gas (e.g. MQ-2)
    SMOKE = "SMOKE"                # smoke / particulate (gas or vision sensor)
    FIRE = "FIRE"                  # open flame detected (vision or IR)
    HUMAN = "HUMAN"                # person detected in the robot's path
    OBSTACLE = "OBSTACLE"          # generic visual obstacle (C5 extension point)
    TEMPERATURE = "TEMPERATURE"    # over-temperature
    ZONE_BREACH = "ZONE_BREACH"    # robot location inside a restricted zone
    ROBOT_FAULT = "ROBOT_FAULT"    # robot / navigation state is unhealthy
    VISION = "VISION"              # generic visual hazard
    VISION_FAULT = "VISION_FAULT"  # vision detector/camera unavailable (C5)
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, value: Any) -> "HazardKind":
        """Coerce ``value`` (enum, name or string) to a kind.

        Unknown values degrade to :attr:`UNKNOWN` rather than raising, so a new
        detector cannot crash the safety loop.
        """
        if isinstance(value, HazardKind):
            return value
        if value is None:
            return cls.UNKNOWN
        text = str(value).strip().upper()
        for member in cls:
            if member.value == text or member.name == text:
                return member
        return cls.UNKNOWN


class HazardSeverity(str, Enum):
    """How urgent a single hazard reading is.

    Severity is produced by a *source* (from configured thresholds) and is then
    mapped — together with the kind — to a :class:`HazardState`.
    """

    INFO = "INFO"          # informational; never changes the hazard state
    WARNING = "WARNING"    # attention required
    CRITICAL = "CRITICAL"  # immediate action required

    @property
    def rank(self) -> int:
        """Numeric ordering (higher is worse) for worst-wins comparisons."""
        return _SEVERITY_RANK[self]

    @classmethod
    def parse(cls, value: Any) -> "HazardSeverity":
        """Coerce ``value`` to a severity; unknown values become ``WARNING``.

        Degrading to ``WARNING`` (not ``INFO``) is deliberate: an unrecognised
        severity must not silently disappear from the hazard decision.
        """
        if isinstance(value, HazardSeverity):
            return value
        text = str(value or "").strip().upper()
        for member in cls:
            if member.value == text or member.name == text:
                return member
        return cls.WARNING


_SEVERITY_RANK: Dict[HazardSeverity, int] = {
    HazardSeverity.INFO: 0,
    HazardSeverity.WARNING: 1,
    HazardSeverity.CRITICAL: 2,
}


class HazardState(str, Enum):
    """Aggregated hazard state for the whole robot (worst-wins)."""

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    SLOW = "SLOW"
    STOP = "STOP"
    EMERGENCY = "EMERGENCY"

    @property
    def rank(self) -> int:
        """Numeric ordering (higher is worse)."""
        return _STATE_RANK[self]

    @property
    def blocks_motion(self) -> bool:
        """``True`` when no motion may be commanded in this state."""
        return self in (HazardState.STOP, HazardState.EMERGENCY)

    @property
    def latches(self) -> bool:
        """``True`` when the state persists until an operator acknowledges it."""
        return self is HazardState.EMERGENCY

    def worst(self, other: "HazardState") -> "HazardState":
        """Return the more severe of ``self`` and ``other``."""
        return self if self.rank >= other.rank else other

    @classmethod
    def parse(cls, value: Any) -> "HazardState":
        """Coerce ``value`` to a state; unknown values become ``NORMAL``.

        Unknown values degrade to ``NORMAL`` so that a bad *observed* state can
        never silently *block* the robot; blocking is always driven by a
        concrete reading.
        """
        if isinstance(value, HazardState):
            return value
        text = str(value or "").strip().upper()
        for member in cls:
            if member.value == text or member.name == text:
                return member
        return cls.NORMAL


_STATE_RANK: Dict[HazardState, int] = {
    HazardState.NORMAL: 0,
    HazardState.WARNING: 1,
    HazardState.SLOW: 2,
    HazardState.STOP: 3,
    HazardState.EMERGENCY: 4,
}


VISION_CLASS_TO_KIND: Dict[str, HazardKind] = {
    # Canonical vision class label (upper-cased, stripped) -> hazard kind.
    # PERSON/HUMAN are synonyms for the same person kind; OBSTACLE and
    # RESTRICTED_ZONE are supported mappings (coachable extension points).
    "HUMAN": HazardKind.HUMAN,
    "PERSON": HazardKind.HUMAN,
    "PEOPLE": HazardKind.HUMAN,
    "FIRE": HazardKind.FIRE,
    "FLAME": HazardKind.FIRE,
    "SMOKE": HazardKind.SMOKE,
    "OBSTACLE": HazardKind.OBSTACLE,
    "RESTRICTED_ZONE": HazardKind.ZONE_BREACH,
    "RESTRICTED": HazardKind.ZONE_BREACH,
}


@dataclass(frozen=True)
class HazardLocation:
    """Where a hazard (or the robot when it detected one) was located.

    A 2D world-frame position in metres plus an optional heading in radians.
    Kept independent of :class:`amr.navigation.types.Pose` so this package
    imports standalone; use :meth:`from_any` to convert a ``Pose``.

    ``zone`` optionally records the named warehouse location the hazard belongs
    to, which the future spatial hazard visualisation can group by.
    """

    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0
    zone: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"x": self.x, "y": self.y, "theta": self.theta, "zone": self.zone}

    @classmethod
    def from_any(cls, value: Any) -> Optional["HazardLocation"]:
        """Best-effort conversion of a pose-like object into a location.

        Accepts a :class:`HazardLocation`, any object exposing ``x``/``y``
        (e.g. ``amr.navigation.types.Pose`), a mapping with ``x``/``y`` keys
        (e.g. JSON from a detector backend), or a 2-3 element sequence.
        Returns ``None`` when nothing usable is supplied -- in particular a
        mapping that lacks both coordinates yields ``None`` rather than a
        fabricated origin.
        """
        if value is None:
            return None
        if isinstance(value, HazardLocation):
            return value
        if isinstance(value, Mapping):
            if "x" not in value or "y" not in value:
                return None
            raw_theta = value.get("theta", 0.0) or 0.0
            zone = value.get("zone")
            try:
                return cls(
                    x=float(value["x"]),
                    y=float(value["y"]),
                    theta=float(raw_theta),
                    zone=str(zone) if zone is not None else None,
                )
            except (TypeError, ValueError):
                return None
        if hasattr(value, "x") and hasattr(value, "y"):
            return cls(
                x=float(value.x),
                y=float(value.y),
                theta=float(getattr(value, "theta", 0.0) or 0.0),
                zone=getattr(value, "zone", None),
            )
        if isinstance(value, (tuple, list)) and 2 <= len(value) <= 3:
            seq: Sequence[Any] = value
            return cls(
                x=float(seq[0]),
                y=float(seq[1]),
                theta=float(seq[2]) if len(seq) > 2 else 0.0,
            )
        return None


@dataclass(frozen=True)
class HazardReading:
    """One observation from one hazard source (or an injected extra reading).

    ``value``/``unit`` carry the raw measurement when there is one (``ppm`` for
    gas, ``degC`` for temperature, a 0..1 ``confidence`` for vision). A message
    is always included so an event-log line is human-readable on its own.
    """

    kind: HazardKind = HazardKind.UNKNOWN
    value: float = 0.0
    unit: str = ""
    severity: HazardSeverity = HazardSeverity.WARNING
    source: str = "unknown"
    message: str = ""
    timestamp: float = field(default_factory=time.time)
    #: Where the hazard itself is, when the source knows (e.g. a vision
    #: detection that carries a world-frame pose). ``None`` means "unknown" and
    #: is deliberately *not* a fabricated 0,0: the manager falls back to the
    #: robot's own pose when recording the event.
    location: Optional[HazardLocation] = None
    #: Free-form, non-safety-critical context carried from a source (e.g. a
    #: vision detection's image-space bbox and object_id). Never used to make a
    #: safety decision; persisted so the event log keeps the evidence trail.
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Coerce tolerantly: readings may originate from external detectors.
        object.__setattr__(self, "kind", HazardKind.parse(self.kind))
        object.__setattr__(self, "severity", HazardSeverity.parse(self.severity))
        if not isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", {})

    @property
    def is_critical(self) -> bool:
        return self.severity is HazardSeverity.CRITICAL

    @property
    def key(self) -> str:
        """Stable identity for de-duplicating concurrent readings."""
        return f"{self.kind.value}:{self.source}"

    def describe(self) -> str:
        """Compact human-readable summary for logs and reason strings."""
        if self.message:
            return self.message
        if self.unit:
            return f"{self.kind.value} {self.value:g}{self.unit} ({self.source})"
        return f"{self.kind.value} ({self.source})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "value": self.value,
            "unit": self.unit,
            "severity": self.severity.value,
            "source": self.source,
            "message": self.message,
            "timestamp": self.timestamp,
            "location": self.location.to_dict() if self.location else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HazardEvent:
    """A recorded hazard occurrence, with optional spatial information.

    Events are the durable record: they are stored in a bounded
    :class:`amr.hazard.event_log.HazardEventLog` and can be exported as JSON
    lines for a dashboard or future spatial hazard visualisation.

    Instances are immutable; :meth:`resolved_with` / :meth:`escalated_with`
    return updated copies so the log can replace an entry by :attr:`event_id`.
    """

    event_id: str
    kind: HazardKind = HazardKind.UNKNOWN
    severity: HazardSeverity = HazardSeverity.WARNING
    state: HazardState = HazardState.WARNING
    message: str = ""
    raised_at: float = field(default_factory=time.time)
    source: str = "unknown"
    location: Optional[HazardLocation] = None
    cleared_at: Optional[float] = None
    #: Evidence context preserved from the originating reading (e.g. a vision
    #: detection's bbox / object_id). Recorded for audit and visualisation; it
    #: is never consulted when deciding the safety state.
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", HazardKind.parse(self.kind))
        object.__setattr__(self, "severity", HazardSeverity.parse(self.severity))
        object.__setattr__(self, "state", HazardState.parse(self.state))
        if not isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", {})

    @property
    def confidence(self) -> Optional[float]:
        """Detector confidence when the event came from a vision source.

        Returned as-is (0..1, never rescaled); ``None`` for non-vision events.
        """
        raw = self.metadata.get("confidence")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        return float(raw)

    @property
    def resolved(self) -> bool:
        """``True`` once the event has been cleared."""
        return self.cleared_at is not None

    @property
    def duration_s(self) -> Optional[float]:
        """Seconds the event was active, or ``None`` while it is still open."""
        if self.cleared_at is None:
            return None
        return max(0.0, self.cleared_at - self.raised_at)

    def resolved_with(self, cleared_at: Optional[float] = None) -> "HazardEvent":
        """Return a copy marked as cleared."""
        return replace(
            self,
            cleared_at=time.time() if cleared_at is None else cleared_at,
        )

    def escalated_with(
        self,
        severity: HazardSeverity,
        state: HazardState,
        message: str = "",
    ) -> "HazardEvent":
        """Return a copy with an updated severity/state (``raised_at`` kept)."""
        return replace(
            self,
            severity=HazardSeverity.parse(severity),
            state=HazardState.parse(state),
            message=message or self.message,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind.value,
            "severity": self.severity.value,
            "state": self.state.value,
            "message": self.message,
            "source": self.source,
            "raised_at": self.raised_at,
            "cleared_at": self.cleared_at,
            "duration_s": self.duration_s,
            "resolved": self.resolved,
            "location": self.location.to_dict() if self.location else None,
            "metadata": dict(self.metadata),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class HazardStatus:
    """The hazard layer's current verdict — a frozen, inspectable snapshot."""

    state: HazardState = HazardState.NORMAL
    reasons: Tuple[str, ...] = ()
    readings: Tuple[HazardReading, ...] = ()
    speed_scale: float = 1.0
    latched: bool = False
    location: Optional[HazardLocation] = None
    updated_at: float = field(default_factory=time.time)

    @property
    def blocks_motion(self) -> bool:
        """``True`` when motion must be vetoed."""
        return self.state.blocks_motion

    @property
    def allowed(self) -> bool:
        """Mirror of ``SafetyDecision.allowed``: may the robot move?"""
        return not self.blocks_motion

    @property
    def caution(self) -> bool:
        """``True`` when the robot should proceed with reduced speed."""
        return self.state is HazardState.SLOW

    def worst(self, other: HazardState) -> HazardState:
        """The more severe of this status' state and ``other``."""
        return self.state.worst(other)

    def __str__(self) -> str:
        if self.reasons:
            return f"{self.state.value} ({'; '.join(self.reasons)})"
        return self.state.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "reasons": list(self.reasons),
            "speed_scale": self.speed_scale,
            "latched": self.latched,
            "blocks_motion": self.blocks_motion,
            "updated_at": self.updated_at,
            "location": self.location.to_dict() if self.location else None,
            "readings": [r.to_dict() for r in self.readings],
        }
