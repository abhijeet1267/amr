"""Context-aware multi-hazard safety layer (Layer 3.5 on the Pi).

Aggregates many independent hazard inputs — gas/smoke sensors, camera vision,
fire/human detection, robot state, navigation state and robot location — into a
single, deterministic :class:`~amr.hazard.types.HazardState`:

    NORMAL  ->  WARNING  ->  SLOW  ->  STOP  ->  EMERGENCY

Why a separate layer?
---------------------
``amr/safety`` answers *"is the path clear right now?"* from the ultrasonic ring
(docs/safety.md, Layer 3). This layer answers the wider question *"is the
environment safe to operate in at all?"*, which depends on more than proximity:
air quality, a human in the aisle, a fire, or where the robot currently is.

Hard rules (do not weaken these)
--------------------------------
1. **Escalate only.** This layer can *tighten* the outcome; it can never relax
   the existing Layer-3 decision. ``RobotManager`` takes the worst of both.
2. **Never drive.** It returns a verdict. Only ``RobotManager`` may command
   motion, so all the existing gating still applies.
3. **Fail safe.** A source that raises, or reports no data, produces a
   ``WARNING`` reading rather than silence.
4. **Deterministic.** No heuristics, no randomness: the same readings always
   produce the same state (mirrors the Layer-3 design promise).

State semantics
---------------
``WARNING``   — hazard present, motion allowed at full speed, operator notified.
``SLOW``      — motion allowed, capped at ``HazardConfig.slow_speed_scale``.
``STOP``      — any ``CRITICAL`` reading of a non-emergency kind.
``EMERGENCY`` — a ``CRITICAL`` reading of a life-safety kind
                (``HazardConfig.emergency_kinds``). **Latches** until
                :meth:`HazardManager.acknowledge` is called by an operator,
                mirroring ``SAFETY_STOP`` semantics.

Events
------
Every hazard above ``INFO`` is recorded as a
:class:`~amr.hazard.types.HazardEvent` in a bounded
:class:`~amr.hazard.event_log.HazardEventLog`, tagged with the robot's location
when one is available. Events escalate in place (never silently downgrade) and
are resolved when the reading disappears — this is the audit trail and the
foundation for future spatial hazard visualisation.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..logging import get_logger
from ..utils.config import HazardConfig
from .event_log import HazardEventLog
from .sources import HazardSource, zones_from_config
from .types import (
    HazardEvent,
    HazardKind,
    HazardLocation,
    HazardReading,
    HazardSeverity,
    HazardState,
    HazardStatus,
)

#: Life-safety kinds used when ``HazardConfig.emergency_kinds`` is empty/unset.
DEFAULT_EMERGENCY_KINDS: Tuple[HazardKind, ...] = (
    HazardKind.FIRE,
    HazardKind.GAS,
    HazardKind.SMOKE,
)

#: Kinds that reduce speed (rather than merely warn) at ``WARNING`` severity.
DEFAULT_SLOW_KINDS: Tuple[HazardKind, ...] = (
    HazardKind.GAS,
    HazardKind.SMOKE,
    HazardKind.HUMAN,
    HazardKind.ZONE_BREACH,
)


def _parse_kinds(values: Any, fallback: Sequence[HazardKind]) -> Tuple[HazardKind, ...]:
    """Coerce a config list of kind names into kinds.

    ``None`` (key absent) falls back to the documented default; an explicit
    empty list means "none", so an operator can deliberately switch a band off.
    """
    if values is None:
        return tuple(fallback)
    kinds: List[HazardKind] = []
    for entry in values:
        kind = HazardKind.parse(entry)
        if kind is not HazardKind.UNKNOWN and kind not in kinds:
            kinds.append(kind)
    return tuple(kinds)


#: Human-readable reason attached to a latched EMERGENCY.
_LATCH_REASON = "EMERGENCY latched; awaiting operator acknowledgement"


class HazardManager:
    """Aggregates hazard sources into one deterministic, most-severe verdict.

    The manager is the only public entry point of this package. It is polled
    (never threaded), holds no hardware handles, and performs no I/O beyond the
    optional event export — so it can be driven directly from a control loop or
    a unit test.
    """

    def __init__(
        self,
        config: HazardConfig,
        sources: Sequence[HazardSource] = (),
        event_log: Optional[HazardEventLog] = None,
        clock: Callable[[], float] = time.time,
    ):
        self._config = config
        self._sources: List[HazardSource] = list(sources or ())
        self._clock = clock
        self._emergency_kinds = _parse_kinds(
            config.emergency_kinds, DEFAULT_EMERGENCY_KINDS
        )
        self._slow_kinds = _parse_kinds(config.slow_kinds, DEFAULT_SLOW_KINDS)
        self.events = (
            event_log
            if event_log is not None
            else HazardEventLog(
                capacity=config.max_events, path=config.event_log_path
            )
        )
        self.log = get_logger("hazard")

        self._status = HazardStatus(updated_at=self._clock())
        self._active: Dict[str, HazardEvent] = {}
        self._seq = 0
        self._latched = False
        self._last_location: Optional[HazardLocation] = None

    # ------------------------------------------------------------------ #
    # Configuration / composition
    # ------------------------------------------------------------------ #
    @classmethod
    def from_config(
        cls,
        config: HazardConfig,
        sources: Sequence[HazardSource] = (),
        pose_provider: Optional[Callable[[], Any]] = None,
        event_log: Optional[HazardEventLog] = None,
        clock: Callable[[], float] = time.time,
    ) -> "HazardManager":
        """Build a manager, adding a zone source when ``hazard.zones`` is set.

        Keeps construction in one place so callers do not have to remember to
        wire the location-aware part of the layer.
        """
        from .sources import RestrictedZoneSource

        wired: List[HazardSource] = list(sources or ())
        zones = zones_from_config(config)
        if zones:
            wired.append(RestrictedZoneSource(zones, pose_provider))
        return cls(config, wired, event_log=event_log, clock=clock)

    def add_source(self, source: HazardSource) -> None:
        """Attach a source discovered later (e.g. a camera manager after start)."""
        self._sources.append(source)

    @property
    def sources(self) -> Tuple[HazardSource, ...]:
        return tuple(self._sources)

    @property
    def emergency_kinds(self) -> Tuple[HazardKind, ...]:
        return self._emergency_kinds

    @property
    def slow_kinds(self) -> Tuple[HazardKind, ...]:
        return self._slow_kinds

    # ------------------------------------------------------------------ #
    # Current verdict
    # ------------------------------------------------------------------ #
    @property
    def status(self) -> HazardStatus:
        """The most recent :class:`HazardStatus` (``NORMAL`` before the first)."""
        return self._status

    @property
    def state(self) -> HazardState:
        return self._status.state

    @property
    def speed_scale(self) -> float:
        """Speed multiplier the robot should apply right now (1.0 = no change)."""
        return self._status.speed_scale

    @property
    def latched(self) -> bool:
        return self._latched

    def active_events(self) -> Tuple[HazardEvent, ...]:
        """Hazard events that have not yet cleared."""
        return self.events.active()

    # ------------------------------------------------------------------ #
    # Evaluation
    # ------------------------------------------------------------------ #
    def evaluate(
        self,
        location: Any = None,
        extra: Sequence[HazardReading] = (),
    ) -> HazardStatus:
        """Poll every source and produce the current hazard verdict.

        :param location: the robot's pose (any object with ``x``/``y``); reused
            from the previous call when omitted.
        :param extra: additional one-off readings injected by the caller (e.g. a
            result the web layer already computed).
        :returns: the new immutable :class:`HazardStatus`.
        """
        if location is not None:
            self._last_location = HazardLocation.from_any(location)
        where = self._last_location

        readings: List[HazardReading] = list(extra or ())
        for source in self._sources:
            readings.extend(self._read_source(source))

        state, reasons = self._decide(readings)

        # A latched EMERGENCY outranks everything until acknowledged.
        if self._latched and state.rank < HazardState.EMERGENCY.rank:
            state = HazardState.EMERGENCY
            reasons = tuple(list(reasons) + [_LATCH_REASON])
        elif state is HazardState.EMERGENCY:
            self._latched = True

        self._sync_events(readings, state, where)

        self._status = HazardStatus(
            state=state,
            reasons=tuple(reasons),
            readings=tuple(readings),
            speed_scale=self._speed_scale(state),
            latched=self._latched,
            location=where,
            updated_at=self._clock(),
        )
        return self._status

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _read_source(self, source: HazardSource) -> List[HazardReading]:
        """Read one source, converting any failure into a fail-safe warning."""
        name = str(getattr(source, "name", type(source).__name__))
        try:
            raw = source.read()
        except Exception as exc:  # noqa: BLE001 - a broken source must not stop us
            self.log.error("hazard source %s failed: %s", name, exc)
            return [self._source_fault(name, f"{name} source failed: {exc}")]
        return [r for r in (raw or ()) if isinstance(r, HazardReading)]

    @staticmethod
    def _source_fault(name: str, message: str) -> HazardReading:
        return HazardReading(
            kind=HazardKind.ROBOT_FAULT,
            severity=HazardSeverity.WARNING,
            source=name,
            message=message,
        )

    def _decide(
        self, readings: Sequence[HazardReading]
    ) -> Tuple[HazardState, List[str]]:
        """Map readings onto a state. Pure and deterministic (worst wins)."""
        critical = [r for r in readings if r.severity is HazardSeverity.CRITICAL]
        if critical:
            reasons = [r.describe() for r in critical]
            if any(r.kind in self._emergency_kinds for r in critical):
                return HazardState.EMERGENCY, reasons
            return HazardState.STOP, reasons

        warnings = [r for r in readings if r.severity is HazardSeverity.WARNING]
        if warnings:
            slow = [r for r in warnings if r.kind in self._slow_kinds]
            if slow:
                return HazardState.SLOW, [r.describe() for r in slow]
            return HazardState.WARNING, [r.describe() for r in warnings]

        return HazardState.NORMAL, []

    def _speed_scale(self, state: HazardState) -> float:
        if state is HazardState.SLOW:
            return float(self._config.slow_speed_scale)
        if state.blocks_motion:
            return 0.0
        return 1.0

    # ------------------------------------------------------------------ #
    # Event recording
    # ------------------------------------------------------------------ #
    def _next_event_id(self) -> str:
        self._seq += 1
        return f"hzd-{self._seq:04d}"

    def _sync_events(
        self,
        readings: Sequence[HazardReading],
        state: HazardState,
        where: Optional[HazardLocation],
    ) -> None:
        """Raise/escalate/resolve events so the log mirrors the readings.

        An event is keyed by ``kind:source``, so one ongoing gas leak is a single
        event that escalates (WARNING -> CRITICAL) rather than a new event every
        control-loop tick. Events record the *worst* state seen and never
        silently downgrade.
        """
        current: Dict[str, HazardReading] = {}
        for reading in readings:
            if reading.severity is HazardSeverity.INFO:
                continue
            current[reading.key] = reading

        for key, reading in current.items():
            existing = self._active.get(key)
            if existing is None:
                event = HazardEvent(
                    event_id=self._next_event_id(),
                    kind=reading.kind,
                    severity=reading.severity,
                    state=state,
                    message=reading.describe(),
                    raised_at=self._clock(),
                    source=reading.source,
                    # Prefer the hazard's own pose when the source knows one
                    # (e.g. a vision detection with a world-frame estimate);
                    # otherwise fall back to the robot pose. A source that
                    # cannot locate the hazard simply passes location=None --
                    # we never invent coordinates from image-space data.
                    location=reading.location or where,
                    metadata=dict(reading.metadata),
                )
                self._active[key] = self.events.record(event)
                continue
            if reading.severity.rank > existing.severity.rank:
                escalated = existing.escalated_with(
                    reading.severity, state, reading.describe()
                )
                self._active[key] = escalated
                self.events.replace(escalated)

        for key in [k for k in self._active if k not in current]:
            event = self._active.pop(key)
            if not event.resolved:
                self.events.resolve(event.event_id, self._clock())

    # ------------------------------------------------------------------ #
    # Operator controls
    # ------------------------------------------------------------------ #
    def acknowledge(self) -> HazardStatus:
        """Clear a latched ``EMERGENCY`` (operator acknowledgement).

        This releases the *hazard* latch only. It deliberately does **not**
        return the robot to a moving mode: if the robot was forced into
        ``SAFETY_STOP``, the operator must also acknowledge that through
        ``RobotManager.request_mode(IDLE)``. The safety model never
        auto-releases (docs/safety.md).
        """
        if not self._latched:
            return self._status
        self.log.warning("HAZARD EMERGENCY latch acknowledged by operator")
        self._latched = False
        return self.evaluate(location=self._last_location)

    def reset(self) -> None:
        """Clear the latch and drop all recorded events (maintenance use)."""
        self._latched = False
        self._active.clear()
        self.events.clear()
        self._status = HazardStatus(updated_at=self._clock())

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #
    def recent_events(self, count: int = 5) -> Tuple[HazardEvent, ...]:
        """The ``count`` most recent recorded events (newest last)."""
        return self.events.recent(count)

    def snapshot(self) -> dict:
        """JSON-friendly view for telemetry, the web panel and the dashboard."""
        status = self._status
        return {
            "enabled": bool(self._config.enabled),
            "status": self._config.status,
            "state": status.state.value,
            "speed_scale": status.speed_scale,
            "latched": status.latched,
            "blocks_motion": status.blocks_motion,
            "reasons": list(status.reasons),
            "location": status.location.to_dict() if status.location else None,
            "updated_at": status.updated_at,
            "sources": [
                str(getattr(s, "name", type(s).__name__)) for s in self._sources
            ],
            "active_events": [e.to_dict() for e in self.active_events()],
            "recent_events": [e.to_dict() for e in self.recent_events(5)],
            "events_recorded": len(self.events),
            "counts_by_kind": self.events.counts_by_kind(),
        }

