"""C15c — bounded time-series and an event stream for the Command Center.

The C7 telemetry snapshot is a *point-in-time* value, which is all the earlier
dashboards needed. A professional operator console also needs to show how a
value has been **moving**, and needs one ordered feed of everything that has
happened. Neither existed anywhere in the project, so this module adds them.

Two deliberate constraints, both driven by the Raspberry Pi target:

**Server-side, bounded memory.** Samples live in a fixed-length
:class:`collections.deque`. A long-running robot must not grow its heap without
limit, so there is no unbounded history here and none in the browser either —
the page re-fetches a window rather than accumulating. The buffer is the *only*
place history exists, which also means charts and the event log cannot disagree
about the past.

**Read-only.** Nothing here calls ``tick()``, dispatches a command, or touches
an actuator. It observes the same snapshots the dashboard already displays. The
one thing that would be easy to get wrong is inventing a number to keep a chart
pretty: a sample whose value is genuinely ``None`` is recorded as ``None`` and
the chart shows a gap, because ``UNAVAILABLE`` is not zero.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Sequence

#: Bumped if the payload shape below changes in a way readers must notice.
SERIES_SCHEMA_VERSION = "1.0"

#: Default number of samples retained. At the dashboard's 1 Hz that is ~2.5
#: minutes of context in roughly 100 KB of JSON — comfortable on a Pi 4/5.
DEFAULT_SERIES_CAPACITY = 150

#: Default number of events retained. Events are far rarer than samples.
DEFAULT_EVENT_CAPACITY = 200

#: Event categories the console can filter on.
CATEGORIES = ("MISSION", "SAFETY", "HAZARD", "VISION", "NAVIGATION",
              "CAMERA", "SYSTEM")

#: Event levels, ordered most to least severe.
LEVELS = ("CRITICAL", "WARNING", "INFO")

_LEVEL_RANK = {name: i for i, name in enumerate(LEVELS)}


def _is_num(value: Any) -> bool:
    """True for a finite real number (rejects bool, None, NaN, inf)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return not (math.isnan(value) or math.isinf(value))


def _num(value: Any) -> Optional[float]:
    return float(value) if _is_num(value) else None


def level_rank(level: str) -> int:
    """Sort key for a level name; unknown levels sort after ``INFO``."""
    return _LEVEL_RANK.get(str(level or "").upper(), len(LEVELS))


@dataclass
class Sample:
    """One observation of one or more metrics at a single instant."""

    timestamp: float
    values: Dict[str, Optional[float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"t": self.timestamp, "v": dict(self.values)}


@dataclass
class Event:
    """One thing that happened, for the Command Center's event log."""

    timestamp: float
    level: str
    category: str
    message: str
    detail: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "t": self.timestamp,
            "level": self.level,
            "category": self.category,
            "message": self.message,
            "detail": dict(self.detail) if self.detail else None,
        }


#: Which telemetry section feeds which chart, and how to read it out. Keeping
#: this as data (not code) means the frontend and the backend cannot disagree
#: about what a metric means, and adding a chart is a one-line change.
METRICS: Dict[str, Any] = {
    "speed": ("velocity", "linear", "m/s"),
    "battery": ("battery", "percentage", "%"),
    "battery_voltage": ("battery", "voltage", "V"),
}


def extract_metrics(snapshot: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Pull the chartable values out of a telemetry snapshot.

    Unavailable values stay ``None``. They are *not* coerced to 0, because
    "no battery sensor" and "0% battery" are completely different facts and a
    chart that cannot tell them apart is worse than no chart.
    """
    out: Dict[str, Optional[float]] = {}
    for name, (section, field_name, _unit) in METRICS.items():
        value = (snapshot.get(section) or {}).get(field_name)
        out[name] = _num(value)
    return out


@dataclass
class Sample:
    """One observation of one or more metrics at a single instant."""

    timestamp: float
    values: Dict[str, Optional[float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"t": self.timestamp, "v": dict(self.values)}


@dataclass
class Event:
    """One thing that happened, for the Command Center's event log."""

    timestamp: float
    level: str
    category: str
    message: str
    detail: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "t": self.timestamp,
            "level": self.level,
            "category": self.category,
            "message": self.message,
            "detail": dict(self.detail) if self.detail else None,
        }


class TelemetrySeries:
    """Bounded ring of :class:`Sample` objects, fed from telemetry snapshots.

    The fixed length is the important part: a robot left running for days must
    not grow its heap without limit. The dashboard re-fetches this window each
    tick rather than accumulating history in the browser, so the server is the
    single owner of the past.
    """

    def __init__(self, capacity: int = DEFAULT_SERIES_CAPACITY) -> None:
        self.capacity = max(1, int(capacity))
        self._samples: Deque[Sample] = deque(maxlen=self.capacity)
        self._lock = threading.Lock()
        #: Bumped on every append so the UI can tell "same data" from "new".
        self._revision = 0

    def record(self, snapshot: Dict[str, Any]) -> Optional[Sample]:
        """Append one sample from ``snapshot``.

        A snapshot without a usable timestamp is **skipped** rather than
        recorded at the wrong moment — the same rule the C14 recorder follows.
        """
        if not isinstance(snapshot, dict):
            return None
        stamp = _num(snapshot.get("timestamp"))
        if stamp is None:
            return None
        sample = Sample(timestamp=stamp, values=extract_metrics(snapshot))
        with self._lock:
            self._samples.append(sample)
            self._revision += 1
        return sample

    def samples(self, names: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """The retained window, oldest first, optionally narrowed to some metrics."""
        with self._lock:
            current = list(self._samples)
        if names is None:
            return [s.to_dict() for s in current]
        wanted = [n for n in names if n in METRICS]
        return [{"t": s.timestamp, "v": {n: s.values.get(n) for n in wanted}}
                for s in current]

    def to_dict(self, names: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        with self._lock:
            revision, count = self._revision, len(self._samples)
        return {
            "schema_version": SERIES_SCHEMA_VERSION,
            "revision": revision,
            "capacity": self.capacity,
            "count": count,
            "metrics": {
                name: {"unit": METRICS[name][2], "section": METRICS[name][0],
                       "field": METRICS[name][1]}
                for name in METRICS
            },
            "samples": self.samples(names),
        }

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()
            self._revision += 1


class EventStream:
    """Bounded, de-duplicated feed of notable occurrences.

    It is fed by :meth:`observe`, which compares each new snapshot against the
    previous one and emits only on a genuine *change*. Without that, a 1 Hz
    poll would emit "mission: PICK" sixty times a minute and the log would be
    useless.
    """

    def __init__(self, capacity: int = DEFAULT_EVENT_CAPACITY) -> None:
        self.capacity = max(1, int(capacity))
        self._events: Deque[Event] = deque(maxlen=self.capacity)
        self._lock = threading.Lock()
        #: Last-seen value per watched key; drives change detection.
        self._seen: Dict[str, Any] = {}
        self._revision = 0

    def emit(self, event: Event) -> Optional[Event]:
        """Append an event unless it repeats the current one verbatim."""
        if not _is_num(event.timestamp):
            return None
        with self._lock:
            if self._events and self._events[-1].message == event.message \
                    and self._events[-1].category == event.category:
                return None
            self._events.append(event)
            self._revision += 1
        return event

    def events(self, *, level: Optional[str] = None,
               category: Optional[str] = None,
               limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retained events, newest first, optionally filtered."""
        with self._lock:
            current = list(self._events)
        items = [e for e in current
                 if (level is None or e.level.upper() == level.upper())
                 and (category is None or e.category.upper() == category.upper())]
        items.reverse()
        if limit is not None and limit >= 0:
            items = items[:limit]
        return [e.to_dict() for e in items]

    def to_dict(self, *, limit: Optional[int] = 60) -> Dict[str, Any]:
        with self._lock:
            revision, count = self._revision, len(self._events)
        return {
            "schema_version": SERIES_SCHEMA_VERSION,
            "revision": revision,
            "capacity": self.capacity,
            "count": count,
            "categories": list(CATEGORIES),
            "levels": list(LEVELS),
            "events": self.events(limit=limit),
        }

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._seen.clear()
            self._revision += 1

    def observe(self, snapshot: Dict[str, Any],
                health: Optional[Dict[str, Any]] = None) -> List[Event]:
        """Emit events for whatever *changed* since the previous snapshot.

        Called once per tick with the authoritative snapshot, so the log is a
        projection of real state rather than a parallel narrative.
        """
        if not isinstance(snapshot, dict):
            return []
        stamp = _num(snapshot.get("timestamp"))
        if stamp is None:
            return []
        emitted: List[Event] = []

        def add(level: str, category: str, message: str,
                detail: Optional[Dict[str, Any]] = None) -> None:
            ev = self.emit(Event(timestamp=stamp, level=level,
                                 category=category, message=message,
                                 detail=detail))
            if ev is not None:
                emitted.append(ev)

        mission = snapshot.get("mission") or {}
        key = ("mission", mission.get("current_task"),
               mission.get("current_task_status"), mission.get("current_task_type"))
        if self._seen.get("mission") != key:
            self._seen["mission"] = key
            if mission.get("current_task"):
                add("INFO", "MISSION",
                    f"{str(mission.get('current_task_type') or 'TASK').upper()} "
                    f"{mission.get('current_task')}")
            else:
                done = mission.get("completed_tasks") or 0
                add("INFO", "MISSION",
                    f"mission complete ({done} tasks)" if done
                    else "mission idle")

        nav = snapshot.get("navigation") or {}
        key = ("nav", nav.get("state"), nav.get("current_goal"))
        if self._seen.get("nav") != key:
            self._seen["nav"] = key
            if nav.get("state"):
                goal = nav.get("current_goal")
                add("INFO", "NAVIGATION",
                    f"{nav['state']}" + (f" -> {goal}" if goal else ""))

        avoid = nav.get("avoidance")
        if avoid and self._seen.get("avoidance") != avoid:
            self._seen["avoidance"] = avoid
            action = avoid.get("action") if isinstance(avoid, dict) else avoid
            add("WARNING", "SAFETY", f"avoidance {action}")

        for hz in (snapshot.get("hazards") or {}).get("active") or ():
            if not isinstance(hz, dict):
                continue
            ident = (f"hz:{hz.get('event_id') or hz.get('raised_at')}"
                     f" or {hz.get('kind')}")
            if self._seen.get(ident):
                continue
            self._seen[ident] = True
            kind = str(hz.get("kind") or "HAZARD")
            level = "CRITICAL" if str(hz.get("severity") or "").upper() == "CRITICAL" \
                else "WARNING"
            msg = f"{kind} detected"
            if _is_num(hz.get("confidence")):
                msg += f" (confidence {hz['confidence']:.2f})"
            # A bbox means the evidence came from a camera.
            from_vision = bool((hz.get("metadata") or {}).get("bbox"))
            add(level, "VISION" if from_vision else "HAZARD", msg,
                {"kind": kind, "source": hz.get("source"),
                 "location": hz.get("location")})

        safety = snapshot.get("safety") or {}
        key = ("safety", safety.get("state"), safety.get("action"),
               bool(safety.get("emergency_stop")))
        if self._seen.get("safety") != key:
            self._seen["safety"] = key
            if safety.get("emergency_stop"):
                add("CRITICAL", "SAFETY", "EMERGENCY STOP")
            elif safety.get("action") and safety.get("action") != "PROCEED":
                add("WARNING", "SAFETY",
                    f"action {safety.get('action')}"
                    + (f" ({safety.get('reason')})" if safety.get("reason") else ""))

        camera = snapshot.get("camera") or {}
        key = ("camera", camera.get("status"))
        if self._seen.get("camera") != key:
            self._seen["camera"] = key
            if camera.get("status") in ("UNAVAILABLE", "ERROR"):
                add("WARNING", "CAMERA",
                    f"camera {camera['status']}"
                    + (f": {camera.get('reason')}" if camera.get("reason") else ""))

        if health and health.get("status") == "DEGRADED":
            for err in health.get("errors") or []:
                ident = f"degraded:{err}"
                if self._seen.get(ident):
                    continue
                self._seen[ident] = True
                add("WARNING", "SYSTEM", f"degraded: {err}")

        return emitted


class CommandCenterHistory:
    """The pair of buffers a Command Center needs, in one object.

    Grouping them keeps the wiring to a single attribute on the web app and
    makes "clear everything" one call. Both are read-only observers.
    """

    def __init__(self, *, series_capacity: int = DEFAULT_SERIES_CAPACITY,
                 event_capacity: int = DEFAULT_EVENT_CAPACITY) -> None:
        self.series = TelemetrySeries(series_capacity)
        self.events = EventStream(event_capacity)

    def observe(self, snapshot: Dict[str, Any],
                health: Optional[Dict[str, Any]] = None) -> None:
        """Record one authoritative snapshot into both buffers."""
        self.series.record(snapshot)
        self.events.observe(snapshot, health)

    def to_dict(self, *, series_limit: Optional[int] = None,
                event_limit: int = 60) -> Dict[str, Any]:
        return {
            "series": self.series.to_dict(series_limit),
            "events": self.events.to_dict(limit=event_limit),
        }

    def clear(self) -> None:
        self.series.clear()
        self.events.clear()
