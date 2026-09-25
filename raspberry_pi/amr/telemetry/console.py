"""C11 — advanced telemetry + mission monitoring console.

A **read-only projection** of the existing runtime for the operations dashboard.

This module deliberately owns no state. It is handed the already-computed C7
telemetry snapshot, the C9 map snapshot, the C10 twin state and the C7 health
summary, and it *assembles* them into one response the browser can render in a
single fetch. Every field it returns is copied or derived arithmetically from
those inputs — nothing is sampled from hardware here, and nothing is cached, so
the console cannot drift from the runtime.

Two rules shape the whole design:

1. **One source of truth.** No new telemetry schema, no second mission engine,
   no re-derivation of safety or navigation decisions. The dashboard reads the
   same objects the 2D map and 3D twin read.
2. **Absence stays absence.** A value that is ``UNAVAILABLE`` is reported as
   such. It is never coerced to ``0``, ``"ok"``, ``100%`` or a plausible-looking
   default. See :func:`_value` and :func:`_availability`.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

#: Console payload schema. Independent of the telemetry schema it presents.
CONSOLE_SCHEMA_VERSION = "1.0"

#: The four source tags the C7 ``DataSource`` enum defines. Anything outside
#: this set is surfaced verbatim rather than coerced, so a future enum member
#: shows up honestly instead of being flattened to "unknown".
SOURCE_TAGS = ("LIVE", "SIMULATION", "UNAVAILABLE", "ERROR")

#: Sentinel returned when a field has no value. Distinct from any real number.
NOT_AVAILABLE = "N/A"


def _value(v: Any, fmt: str = "", unit: str = "") -> str:
    """Format one value for display, preserving absence.

    ``None`` becomes :data:`NOT_AVAILABLE` — never ``0``, never ``"--"``, never
    an invented default.
    """
    if v is None:
        return NOT_AVAILABLE
    try:
        if fmt and isinstance(v, (int, float)):
            return (format(float(v), fmt) + unit) if unit else format(float(v), fmt)
        if unit and isinstance(v, (int, float)):
            return f"{v}{unit}"
    except (TypeError, ValueError):
        return NOT_AVAILABLE
    return str(v)


def _num(v: Any) -> Optional[float]:
    """Coerce to a finite float, or ``None`` — never NaN/inf leaking to JSON."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def source_of(section: Any) -> str:
    """The C7 ``DataSource`` value of a telemetry section, or UNAVAILABLE."""
    raw = section.get("source") if isinstance(section, dict) else getattr(section, "source", None)
    if raw is None:
        return "UNAVAILABLE"
    return raw if isinstance(raw, str) else getattr(raw, "value", str(raw))


def _availability(source: str) -> str:
    """Map a source tag to a coarse availability word for the UI.

    Deliberately merges ``UNAVAILABLE`` and ``ERROR`` into "not available": a
    missing sensor must never render as a healthy one.
    """
    return "AVAILABLE" if source in ("LIVE", "SIMULATION") else "NOT AVAILABLE"


# --------------------------------------------------------------------------- #
# Display-only derivations (no new runtime state)
# --------------------------------------------------------------------------- #
def route_progress_points(telemetry: Any) -> Optional[Dict[str, Any]]:
    """Summarise the planned route from existing navigation telemetry.

    Uses only ``navigation.route`` and ``navigation.progress`` that the C7
    collector already produced. The progress figure is reported **as-is**; this
    function never recomputes a percentage, because the collector's value is
    straight-line distance, not path-following completion, and re-deriving it
    here would risk quietly implying the latter.
    """
    nav = telemetry.get("navigation") if isinstance(telemetry, dict) else None
    if not isinstance(nav, dict):
        return None
    route = nav.get("route") or []
    if not isinstance(route, Sequence) or isinstance(route, (str, bytes)) or not route:
        return None
    progress = _num(nav.get("progress"))
    return {
        "waypoints": len(route),
        "progress": progress,
        "progress_pct": (None if progress is None
                         else max(0.0, min(1.0, progress)) * 100.0),
        "progress_basis": "straight-line distance to goal (not path-following)",
        "progress_available": progress is not None,
    }


def hazard_summary(telemetry: Any, map_snapshot: Any) -> Dict[str, Any]:
    """Hazard counts and the placed/unplaced split.

    The placed/unplaced split is read from the **map/twin** projection, which
    already enforces the C9 rule: a hazard is placed only with a real world
    location. This function never decides placement itself.
    """
    hz = telemetry.get("hazards") if isinstance(telemetry, dict) else None
    hz = hz if isinstance(hz, dict) else {}
    active = hz.get("active") or []
    active = active if isinstance(active, list) else []

    critical = 0
    kinds: List[str] = []
    for h in active:
        if not isinstance(h, dict):
            continue
        kind = h.get("kind")
        if kind is not None and str(kind) not in kinds:
            kinds.append(str(kind))
        if str(h.get("severity") or "").upper() in ("CRITICAL", "EMERGENCY", "STOP"):
            critical += 1

    placed = (map_snapshot or {}).get("hazards") if isinstance(map_snapshot, dict) else None
    unplaced = (map_snapshot or {}).get("unlocated") if isinstance(map_snapshot, dict) else None
    return {
        "active": len(active),
        "critical": critical,
        "kinds": kinds,
        "state": hz.get("state"),
        "latched": bool(hz.get("latched")),
        "events_recorded": hz.get("events_recorded"),
        "placed": len(placed) if isinstance(placed, list) else 0,
        "unlocated": len(unplaced) if isinstance(unplaced, list) else 0,
        "source": source_of(hz),
    }


def component_health(telemetry: Any, health: Any) -> List[Dict[str, Any]]:
    """Per-component health rows for the system panel.

    Every row carries the source tag of the data behind it, so a missing
    subsystem is visible as ``UNAVAILABLE`` rather than hidden behind a green
    "ok". The ``api`` row describes this very response path, not robot safety.
    """
    t = telemetry if isinstance(telemetry, dict) else {}
    h = health if isinstance(health, dict) else {}

    def row(name: str, section: Any) -> Dict[str, Any]:
        source = source_of(section)
        return {"component": name, "source": source,
                "availability": _availability(source)}

    rows = [row(n, t.get(k)) for n, k in (
        ("telemetry", "system"), ("navigation", "navigation"),
        ("safety", "safety"), ("hazards", "hazards"),
        ("battery", "battery"), ("sensors", "sensors"),
        ("mission", "mission"), ("camera", "camera"),
    )]
    rows.append({
        "component": "api",
        "source": "LIVE" if h.get("ok") else "ERROR",
        "availability": "AVAILABLE" if h.get("ok") else "NOT AVAILABLE",
    })
    return rows


def _mission_panel(t: Dict[str, Any]) -> Dict[str, Any]:
    """Mission display state, built only from the C7 mission section.

    There is no mission engine here: status is *described* from the existing
    counters and task status, and when the section is UNAVAILABLE the panel
    says so instead of showing a blank-but-healthy mission.
    """
    m = t.get("mission") if isinstance(t.get("mission"), dict) else {}
    source = source_of(m)
    active_task = m.get("current_task")
    status = m.get("current_task_status")
    completed = m.get("completed_tasks")
    failed = m.get("failed_tasks")
    if source in ("UNAVAILABLE", "ERROR") and not active_task:
        state = "Mission data unavailable"
    elif failed:
        state = "FAILED"
    elif active_task and str(status or "").upper() in ("COMPLETED", "DONE"):
        state = "TASK COMPLETE"
    elif active_task:
        state = "ACTIVE"
    elif completed:
        state = "COMPLETED"
    else:
        state = "IDLE"
    return {
        "mission_id": m.get("mission_id"),
        "state": state,
        "current_task": active_task,
        "current_task_type": m.get("current_task_type"),
        "current_task_status": status,
        "queued": m.get("queued"),
        "completed_tasks": completed,
        "failed_tasks": failed,
        "source": source,
        "availability": _availability(source),
    }


def _robot_panel(t: Dict[str, Any]) -> Dict[str, Any]:
    """Robot identity, pose and velocity, straight from the C7 sections.

    Velocity is reported as the collector measured it. A commanded PWM duty
    cycle is *not* a velocity, so nothing is inferred here when the value is
    absent.
    """
    pos = t.get("position") if isinstance(t.get("position"), dict) else {}
    ori = t.get("orientation") if isinstance(t.get("orientation"), dict) else {}
    vel = t.get("velocity") if isinstance(t.get("velocity"), dict) else {}
    syssec = t.get("system") if isinstance(t.get("system"), dict) else {}
    return {
        "robot_id": syssec.get("robot_id"),
        "connected": bool(syssec.get("connected")),
        "mode": syssec.get("mode"),
        "position": {"x": pos.get("x"), "y": pos.get("y"), "z": pos.get("z"),
                     "source": source_of(pos)},
        "orientation": {"yaw": ori.get("yaw"), "source": source_of(ori)},
        "velocity": {"linear": vel.get("linear"), "angular": vel.get("angular"),
                     "source": source_of(vel)},
        "last_error": syssec.get("last_error"),
    }


def _safety_panel(t: Dict[str, Any], hazards: Dict[str, Any]) -> Dict[str, Any]:
    """Safety display state — the C7 result, copied, never re-decided.

    The avoidance field is whatever the navigator last reported. The console
    adds no avoidance logic of its own and cannot clear a latch.
    """
    s = t.get("safety") if isinstance(t.get("safety"), dict) else {}
    nav = t.get("navigation") if isinstance(t.get("navigation"), dict) else {}
    reasons = s.get("reasons") or []
    return {
        "state": s.get("state"),
        "action": s.get("action"),
        "emergency_stop": bool(s.get("emergency_stop")),
        "reasons": [str(r) for r in reasons] if isinstance(reasons, list) else [],
        "hazard_state": s.get("hazard_state"),
        "hazard_latched": bool(s.get("hazard_latched")),
        "avoidance": nav.get("avoidance"),
        "hazard_active": hazards.get("active"),
        "hazard_critical": hazards.get("critical"),
        "source": source_of(s),
        "availability": _availability(source_of(s)),
    }


def _sensor_panel(t: Dict[str, Any]) -> Dict[str, Any]:
    """Sensor rows. Ultrasonic readings are listed only when actually read."""
    s = t.get("sensors") if isinstance(t.get("sensors"), dict) else {}
    rows: List[Dict[str, Any]] = []
    readings = s.get("ultrasonic") or []
    if isinstance(readings, list):
        for r in readings:
            if not isinstance(r, dict):
                continue
            rows.append({
                "sensor": str(r.get("position") or "unknown"),
                "value": r.get("distance_cm"),
                "unit": "cm",
                "source": r.get("source") or source_of(s),
                "availability": _availability(r.get("source") or source_of(s)),
            })
    return {"rows": rows, "source": source_of(s),
            "availability": _availability(source_of(s))}


def _battery_panel(t: Dict[str, Any]) -> Dict[str, Any]:
    """Battery, with every field that does not exist reported as absent."""
    b = t.get("battery") if isinstance(t.get("battery"), dict) else {}
    source = source_of(b)
    return {
        "percentage": b.get("percentage"),
        "voltage": b.get("voltage"),
        "charging": b.get("charging"),
        "source": source,
        "availability": _availability(source),
        "note": ("no battery source in this build"
                 if source == "UNAVAILABLE" else None),
    }


def _camera_panel(t: Dict[str, Any]) -> Dict[str, Any]:
    """Camera status from the C8 section; acquisition stays where it is."""
    c = t.get("camera") if isinstance(t.get("camera"), dict) else {}
    source = source_of(c)
    return {
        "status": c.get("status"),
        "source_name": c.get("source_name"),
        "device": c.get("device"),
        "width": c.get("width"),
        "height": c.get("height"),
        "format": c.get("format"),
        "frame_id": c.get("frame_id"),
        "timestamp": c.get("timestamp"),
        "has_frame": bool(c.get("has_frame")),
        "error": c.get("error"),
        "source": source,
        "availability": _availability(source),
    }



def build_console_state(
    telemetry: Dict[str, Any],
    *,
    health: Optional[Dict[str, Any]] = None,
    map_snapshot: Optional[Dict[str, Any]] = None,
    twin: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the full read-only operations console payload.

    :param telemetry: the C7 ``TelemetrySnapshot.to_dict()`` — authoritative.
    :param health: the C7 health summary from ``TelemetryCollector.health()``.
    :param map_snapshot: the C9 ``MapSnapshot.to_dict()``.
    :param twin: the C10 ``DigitalTwinState.to_dict()``.

    Nothing here samples hardware, mutates the runtime, or re-decides safety.
    The map and twin are included under their existing keys so the 2D and 3D
    panels keep reading exactly the payloads they read today.
    """
    t = telemetry if isinstance(telemetry, dict) else {}
    h = health if isinstance(health, dict) else {}
    m = map_snapshot if isinstance(map_snapshot, dict) else {}
    tw = twin if isinstance(twin, dict) else {}

    mission = _mission_panel(t)
    hz = t.get("hazards") if isinstance(t.get("hazards"), dict) else {}
    hazards = hazard_summary(t, m)
    safety = _safety_panel(t, hazards)
    nav = t.get("navigation") if isinstance(t.get("navigation"), dict) else {}
    syssec = t.get("system") if isinstance(t.get("system"), dict) else {}

    components = component_health(t, h)
    return {
        "schema_version": CONSOLE_SCHEMA_VERSION,
        "telemetry_schema_version": t.get("schema_version"),
        "timestamp": t.get("timestamp"),
        "simulated": bool(t.get("simulated")),
        "source": "SIMULATION" if t.get("simulated") else "LIVE",
        "read_only": True,
        "summary": {
            "robot": _value(syssec.get("mode") or ("connected"
                       if syssec.get("connected") else "offline")),
            "robot_source": source_of(syssec),
            "navigation": _value(nav.get("state")),
            "navigation_source": source_of(nav),
            "safety": _value(safety.get("action") or safety.get("state")),
            "safety_source": safety.get("source"),
            "emergency_stop": safety.get("emergency_stop"),
            "mission": _value(mission.get("state")),
            "mission_source": mission.get("source"),
        },
        "robot": _robot_panel(t),
        "navigation": {
            "state": nav.get("state"),
            "current_goal": nav.get("current_goal"),
            "route": route_progress_points(t),
            "avoidance": nav.get("avoidance"),
            "source": source_of(nav),
            "availability": _availability(source_of(nav)),
        },
        "mission": mission,
        "safety": safety,
        "hazards": hazards,
        # The raw C7 hazard section, so the existing hazard list renderer can
        # keep reading exactly what it read before C11.
        "hazard_list": hz,
        "battery": _battery_panel(t),
        "sensors": _sensor_panel(t),
        "camera": _camera_panel(t),
        "system": {
            "uptime": syssec.get("uptime"),
            "software_version": syssec.get("software_version"),
            "last_error": syssec.get("last_error"),
            "connected": bool(syssec.get("connected")),
            "status": h.get("status"),
            "errors": h.get("errors") or [],
            "components": components,
            "degraded": [c["component"] for c in components
                         if c["availability"] != "AVAILABLE"],
            "source": source_of(syssec),
        },
        # Passed through under their C9/C10 keys: the existing map and twin
        # renderers keep consuming exactly the payloads they consume today.
        "map": m,
        "twin": tw,
    }

