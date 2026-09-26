"""C5e — AMR operations projection for the Command Center.

Everything the operator console shows that the existing panels did not already
cover: a health scorecard, a sensor matrix, a system-connection panel, robot
identity, a mission timeline and statistics, navigation detail, a hazard centre
and a performance monitor.

Three rules govern this module.

**It is a projection, not a runtime.** Every value is derived from the payload
the existing console already built (see :func:`build_ops_state`). There is no
polling, no timer, no thread and no second telemetry path: the Command Center
already polls ``GET /dashboard/state`` once per second, and this rides along in
that one response.

**It never invents a measurement.** There is deliberately *no* numeric health
score. A percentage would imply a weighting the project cannot justify, so
health is categorical — ``HEALTHY`` / ``DEGRADED`` / ``WARNING`` / ``FAULT`` —
and the reasoning is exposed as the per-component list it was derived from.
Anything the runtime does not know is ``None``, which the UI renders as ``n/a``.
``None`` is never turned into ``0``.

**It is read-only.** No import here reaches a motor driver, a transport, a
port or an actuator, and nothing in this module may be given a callback that
could.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

OPS_SCHEMA_VERSION = "1.0"

#: Health vocabulary. Deliberately categorical — see the module docstring.
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
WARNING = "WARNING"
FAULT = "FAULT"

#: Worst-first, so a single fault anywhere outranks a pile of warnings.
_HEALTH_RANK = {HEALTHY: 0, DEGRADED: 1, WARNING: 2, FAULT: 3}

#: Sensor states. NOT_CONNECTED means the project knows of the device but has
#: no driver wired; NOT_AVAILABLE means there is no data channel at all. They
#: are kept distinct on purpose: the first is a gap to fill, the second is a
#: thing this build does not do.
AVAILABLE = "AVAILABLE"
NOT_CONNECTED = "NOT CONNECTED"
NOT_AVAILABLE = "NOT AVAILABLE"
NOT_TESTED = "NOT TESTED"
FAULT_STATE = "FAULT"

#: Sensors the project has an interface or a named concept for but no wired
#: driver. Listed explicitly so the console can say so honestly instead of
#: silently omitting them.
_KNOWN_UNDETECTED = (
    ("ultrasonic", "amr.sensors.ultrasonic"),
    ("encoder_left", "amr.control differential drive"),
    ("encoder_right", "amr.control differential drive"),
    ("gas_sensor", "amr.hazard (C4)"),
    ("imu", "not implemented"),
    ("battery", "not implemented"),
)


def _num(value: Any) -> Optional[float]:
    """A finite float, or ``None``. Booleans and NaN/inf are rejected."""
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(n) or math.isinf(n):
        return None
    return n


def _txt(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _section(console: Any, name: str) -> Dict[str, Any]:
    value = console.get(name) if isinstance(console, dict) else None
    return value if isinstance(value, dict) else {}


def _worst(states: Sequence[str]) -> str:
    worst = HEALTHY
    for state in states:
        if _HEALTH_RANK.get(state, 0) > _HEALTH_RANK[worst]:
            worst = state
    return worst


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
def _component_health(console: Dict[str, Any], health: Any) -> List[Dict[str, Any]]:
    """Per-subsystem status, each with the reason it was classified that way.

    The scorecard is *this* list; the overall verdict is its worst element. A
    reader can therefore always see exactly why the robot is called DEGRADED.
    """
    robot = _section(console, "robot")
    safety = _section(console, "safety")
    system = _section(console, "system")
    camera = _section(console, "camera")
    navigation = _section(console, "navigation")
    mission = _section(console, "mission")
    components: List[Dict[str, Any]] = []

    # Connectivity
    connected = bool(robot.get("connected"))
    last_error = _txt(robot.get("last_error"))
    if last_error:
        state, reason = FAULT, f"controller error: {last_error}"
    elif connected:
        state, reason = HEALTHY, "robot link up"
    else:
        state, reason = DEGRADED, "robot link not established"
    components.append({"component": "connectivity", "state": state,
                       "reason": reason})

    # Safety — a critical hazard or an E-stop is a fault, a hold is a warning.
    if safety.get("emergency_stop"):
        state, reason = FAULT, "emergency stop latched"
    elif safety.get("hazard_critical"):
        state, reason = FAULT, "critical hazard active"
    elif safety.get("hazard_active") or safety.get("latched"):
        state, reason = WARNING, "hazard active, motion restricted"
    elif _txt(safety.get("action")) not in (None, "PROCEED"):
        state = WARNING
        reason = f"safety action {safety.get('action')}"
    else:
        state, reason = HEALTHY, "no active hazard"
    components.append({"component": "safety", "state": state, "reason": reason})

    # Navigation
    nav_state = _txt(navigation.get("state"))
    if navigation.get("availability") == "NOT AVAILABLE":
        state, reason = DEGRADED, "navigation not attached"
    elif nav_state:
        state, reason = HEALTHY, f"navigator {nav_state}"
    else:
        state, reason = DEGRADED, "no navigation state"
    components.append({"component": "navigation", "state": state,
                       "reason": reason})

    # Camera — UNAVAILABLE is degraded, not a fault: the robot still drives.
    cam_state = _txt(camera.get("status"))
    if cam_state in ("ERROR",):
        state, reason = FAULT, _txt(camera.get("error")) or "camera error"
    elif cam_state == "UNAVAILABLE":
        state, reason = DEGRADED, _txt(camera.get("error")) or "no camera"
    elif cam_state in ("LIVE", "SIMULATION"):
        state, reason = HEALTHY, f"camera {cam_state}"
    else:
        state, reason = DEGRADED, "camera state unknown"
    components.append({"component": "camera", "state": state, "reason": reason})

    # Telemetry / backend
    errors = system.get("errors") if isinstance(system.get("errors"), list) else []
    if errors:
        state, reason = DEGRADED, "; ".join(str(e) for e in errors)[:120]
    elif _txt(system.get("status")) in ("OK", "DEGRADED"):
        state = HEALTHY if system.get("status") == "OK" else DEGRADED
        reason = f"backend {system.get('status')}"
    else:
        state, reason = HEALTHY, "telemetry flowing"
    components.append({"component": "telemetry", "state": state, "reason": reason})

    # Mission — idle is healthy; a failure is a fault.
    if mission.get("state") == "FAILED":
        state, reason = FAULT, "mission reported failure"
    elif mission.get("availability") == "NOT AVAILABLE":
        state, reason = DEGRADED, "no mission manager attached"
    else:
        state, reason = HEALTHY, _txt(mission.get("phase")) or "idle"
    components.append({"component": "mission", "state": state, "reason": reason})

    # Recording is optional by design, so a missing one is informational.
    components.append({"component": "recording", "state": HEALTHY,
                       "reason": "recorder optional"})
    return components


# --------------------------------------------------------------------------- #
# Sensors + system connection
# --------------------------------------------------------------------------- #
def _sensor_matrix(console: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every sensor the project has a concept of, with its true state.

    Sensors that exist in the telemetry snapshot are reported from it. The rest
    are listed explicitly as ``NOT CONNECTED`` / ``NOT AVAILABLE`` so the
    operator can see the gap when the real robot arrives, rather than the
    console quietly looking like everything is fine.

    The camera is derived from the C8/C15b camera section, not from the generic
    sensor rows, because that is where its real status lives.
    """
    rows: List[Dict[str, Any]] = []
    sensors = _section(console, "sensors")
    existing = sensors.get("rows") if isinstance(sensors.get("rows"), list) else []
    seen = set()
    for row in existing:
        if not isinstance(row, dict):
            continue
        name = _txt(row.get("sensor") or row.get("name"))
        if not name:
            continue
        seen.add(name)
        rows.append({
            "sensor": name,
            "state": AVAILABLE,
            "source": _txt(sensors.get("source")) or "UNAVAILABLE",
            "value": row.get("value"),
            "detail": _txt(row.get("detail")) or "",
        })

    camera = _section(console, "camera")
    cam_state = _txt(camera.get("status"))
    seen.add("camera")
    rows.append({
        "sensor": "camera",
        "state": AVAILABLE if cam_state in ("LIVE", "SIMULATION") else (
            FAULT_STATE if cam_state == "ERROR" else NOT_AVAILABLE),
        "source": _txt(camera.get("source_name")) or _txt(camera.get("source"))
        or "UNAVAILABLE",
        "value": (f"{camera.get('width')} × {camera.get('height')}"
                  if _num(camera.get("width")) and _num(camera.get("height"))
                  else None),
        "detail": _txt(camera.get("error")) or cam_state or "",
    })

    battery = _section(console, "battery")
    battery_pct = _num(battery.get("percentage"))
    # The battery already has a real section, so it must not also be listed as
    # an unwired sensor further down — one sensor, one row.
    seen.add("battery")
    rows.append({
        "sensor": "battery",
        "state": AVAILABLE if battery_pct is not None else NOT_AVAILABLE,
        "source": _txt(battery.get("source")) or "UNAVAILABLE",
        "value": None if battery_pct is None else f"{battery_pct:g}%",
        "detail": _txt(battery.get("note")) or "",
    })

    for name, note in _KNOWN_UNDETECTED:
        if name in seen:
            continue
        rows.append({
            "sensor": name,
            "state": NOT_CONNECTED,
            "source": NOT_AVAILABLE,
            "value": None,
            "detail": note,
        })
    return rows


def _system_panel(console: Dict[str, Any], recording: Any,
                  replay: Any) -> List[Dict[str, Any]]:
    """Connection status per layer.

    ``web_server`` is only reachable because a request is being served, so it is
    reported as CONNECTED by construction. The rows beneath it are what stop a
    working web page from being mistaken for a working robot.
    """
    robot = _section(console, "robot")
    camera = _section(console, "camera")
    system = _section(console, "system")
    simulated = bool(console.get("simulated"))
    rec = _section(console, "recording") if isinstance(recording, dict) else {}
    rep = _section(console, "replay") if isinstance(replay, dict) else {}
    cam_state = _txt(camera.get("status")) or "UNAVAILABLE"
    return [
        {"layer": "web_server", "state": "CONNECTED",
         "detail": "serving this request"},
        {"layer": "telemetry", "state": "CONNECTED",
         "detail": f"uptime {_num(system.get('uptime')) and 'tracked' or 'n/a'}"},
        {"layer": "camera",
         "state": "READY" if cam_state in ("LIVE", "SIMULATION") else "UNAVAILABLE",
         "detail": cam_state},
        # Never claim a physical link that has not been demonstrated.
        {"layer": "robot_controller",
         "state": "SIMULATION" if simulated else (
             "CONNECTED" if robot.get("connected") else "NOT CONNECTED"),
         "detail": "mock transport" if simulated else "serial link"},
        {"layer": "arduino", "state": NOT_TESTED,
         "detail": "firmware not flashed or run on hardware"},
        {"layer": "pi_hardware", "state": NOT_TESTED,
         "detail": "no Raspberry Pi in this verification"},
        {"layer": "recording",
         "state": ("ACTIVE" if rec.get("active") else "IDLE")
         if rec else NOT_AVAILABLE,
         "detail": _txt(rec.get("recording_id")) or "no recording"},
        {"layer": "replay",
         "state": _txt(rep.get("state")) or "NO_RECORDING",
         "detail": _txt(rep.get("recording_id")) or "no recording loaded"},
    ]


def _identity(console: Dict[str, Any]) -> Dict[str, Any]:
    """Robot identity for the header. Config-sourced, never invented."""
    robot = _section(console, "robot")
    mission = _section(console, "mission")
    navigation = _section(console, "navigation")
    return {
        # Falls back to a neutral placeholder rather than a made-up id.
        "robot_id": _txt(robot.get("robot_id")) or "UNIDENTIFIED",
        "name": "Warehouse Autonomous Mobile Robot",
        "mode": _txt(robot.get("mode")) or "n/a",
        "mission": _txt(mission.get("current_task_type")) or _txt(mission.get("phase"))
        or "NO ACTIVE MISSION",
        "state": _txt(navigation.get("state")) or _txt(mission.get("phase")) or "n/a",
        "destination": _txt(mission.get("destination")),
        "simulated": bool(console.get("simulated")),
    }


# --------------------------------------------------------------------------- #
# Mission timeline + statistics
# --------------------------------------------------------------------------- #
#: The warehouse task order, which is fixed by the task manager rather than
#: invented per run, so it is stated as data here.
_MISSION_STEPS = ("PICK", "PLACE", "RETURN_TO_DOCK")


def _mission_timeline(mission: Dict[str, Any],
                      events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mission phases marked done / current / pending.

    Derived from the actual mission section plus the mission events the
    existing :class:`~amr.telemetry.series.EventStream` already records. A step
    is only ``done`` when the runtime says so — either the task type advanced
    past it, or the mission completed.
    """
    phase = (_txt(mission.get("phase")) or "IDLE").upper()
    task_type = _txt(mission.get("current_task_type"))
    steps = [{"step": s, "state": "pending", "at": None} for s in _MISSION_STEPS]
    if phase == "COMPLETED":
        for step in steps:
            step["state"] = "done"
    elif phase not in ("IDLE", "UNAVAILABLE"):
        for step in steps:
            if step["step"] == task_type:
                step["state"] = "current"
                break
            step["state"] = "done"
    # Attach a real timestamp where the event stream has one for that step.
    for step in steps:
        for event in events:
            if step["step"].lower() in str(event.get("message") or "").lower():
                step["at"] = _num(event.get("t"))
                break
    return steps


def _mission_stats(mission: Dict[str, Any], safety: Dict[str, Any],
                   hazards: Dict[str, Any],
                   events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts the runtime can actually supply. Anything unknown stays ``None``."""
    stamps = [t for t in (_num(e.get("t")) for e in events) if t is not None]
    elapsed = None
    if len(stamps) >= 2:
        span = max(stamps) - min(stamps)
        # Guard against a clock jump being reported as a 3-day mission.
        if 0 <= span < 86400:
            elapsed = round(span, 1)
    messages = [str(e.get("message") or "").lower() for e in events]
    return {
        # Derived from the observed event window, so it only appears once at
        # least two timestamped events exist.
        "elapsed_s": elapsed,
        "tasks_completed": mission.get("completed_tasks"),
        "tasks_total": mission.get("total_tasks"),
        "tasks_failed": mission.get("failed_tasks"),
        "mission_progress": mission.get("mission_progress"),
        "task_progress": mission.get("task_progress"),
        "hazards_active": hazards.get("active"),
        "hazards_observed": sum(1 for e in events
                                if str(e.get("category")) == "HAZARD"),
        "avoidances": sum(1 for m in messages
                          if "turn" in m or "replan" in m),
        "emergency_stop": bool(safety.get("emergency_stop")),
    }


# --------------------------------------------------------------------------- #
# Navigation + hazard centre
# --------------------------------------------------------------------------- #
def _navigation(console: Dict[str, Any]) -> Dict[str, Any]:
    nav = _section(console, "navigation")
    yaw = _num(_section(_section(console, "robot"),
                        "orientation").get("yaw"))
    goal = nav.get("current_goal")
    goal_name = _txt(goal.get("name")) if isinstance(goal, dict) else _txt(goal)
    avoidance = nav.get("avoidance")
    return {
        "state": _txt(nav.get("state")),
        "target": goal_name,
        "source": _txt(nav.get("source")) or "UNAVAILABLE",
        "availability": nav.get("availability"),
        "route_points": (len(nav.get("route"))
                         if isinstance(nav.get("route"), list) else None),
        "avoidance": (_txt(avoidance.get("action"))
                      if isinstance(avoidance, dict) else _txt(avoidance)),
        "planner": "LocalNavigator" if nav.get("availability") == "AVAILABLE"
                   else None,
        # Shown in degrees for the operator, but converted from the
        # authoritative radian value rather than sourced separately.
        "heading_deg": None if yaw is None else round(math.degrees(yaw), 1),
        # Distance to the goal is NOT computed: the runtime exposes no measured
        # range to the target, and a straight-line guess would be a fabricated
        # measurement presented next to real ones.
        "distance_m": None,
    }


def _hazard_centre(console: Dict[str, Any],
                   events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    hazards = _section(console, "hazards")
    safety = _section(console, "safety")
    listed = console.get("hazard_list")
    if isinstance(listed, dict):
        active = [h for h in (listed.get("active") or []) if isinstance(h, dict)]
    elif isinstance(listed, list):
        active = [h for h in listed if isinstance(h, dict)]
    else:
        active = []

    current = None
    if active:
        top = active[0]
        meta = top.get("metadata") if isinstance(top.get("metadata"), dict) else {}
        bbox = meta.get("bbox")
        has_bbox = isinstance(bbox, list)
        current = {
            "kind": _txt(top.get("kind")) or "UNKNOWN",
            "severity": _txt(top.get("severity")),
            "confidence": _num(top.get("confidence")),
            "source": _txt(top.get("source")),
            "raised_at": _num(top.get("raised_at")),
            # bbox is image-space pixels, reported under its own key and never
            # converted into a world coordinate (the C13 rule).
            "bbox_image_px": list(bbox) if has_bbox else None,
            "coordinate_space": "image" if has_bbox else None,
            "world_location": None,
        }

    recent = [{
        "t": _num(e.get("t")),
        "level": _txt(e.get("level")),
        "category": _txt(e.get("category")),
        "message": _txt(e.get("message")),
    } for e in events if str(e.get("category")) in ("HAZARD", "SAFETY", "VISION")]
    recent.sort(key=lambda e: (e["t"] is None, -(e["t"] or 0)))
    return {
        "state": _txt(hazards.get("state")),
        "active_count": hazards.get("active"),
        "critical_count": hazards.get("critical"),
        "action": _txt(safety.get("action")),
        "current": current,
        "recent": recent[:50],
    }


# --------------------------------------------------------------------------- #
# Performance + alerts
# --------------------------------------------------------------------------- #
def _performance(console: Dict[str, Any], history: Any, replay: Any,
                 tick_hz: Any) -> Dict[str, Any]:
    """Real rates only.

    Nothing here is timed in the browser and nothing is estimated. Where the
    project has no measurement, the key is ``None`` and the UI prints ``n/a``:
    a fabricated FPS or latency number sitting next to real telemetry is worse
    than an honest blank.
    """
    rep = _section(console, "replay") if isinstance(replay, dict) else {}
    series = _section(history, "series") if isinstance(history, dict) else {}
    samples = series.get("samples") if isinstance(series.get("samples"), list) else []
    rate = None
    if len(samples) >= 2:
        span = _num(samples[-1].get("t")) - _num(samples[0].get("t"))
        if span and span > 0:
            rate = round((len(samples) - 1) / span, 2)
    return {
        "dashboard_hz": _num(tick_hz),
        "observed_series_hz": rate,
        # Not measured anywhere in the project today. Explicitly null, not 0.
        "api_latency_ms": None,
        "camera_fps": None,
        "inference_fps": None,
        "inference_latency_ms": None,
        "replay_speed": _num(rep.get("speed")),
        "replay_state": _txt(rep.get("state")),
    }


def _alerts(console: Dict[str, Any],
            events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Operator alerts derived from real state and real events.

    Read/unread is deliberately *not* here — that is browser state and belongs
    in the frontend, so nothing has to persist on the server for it.
    """
    alerts: List[Dict[str, Any]] = []
    safety = _section(console, "safety")
    hazards = _section(console, "hazards")
    mission = _section(console, "mission")
    system = _section(console, "system")

    if safety.get("emergency_stop"):
        alerts.append({"severity": "critical", "category": "SAFETY",
                       "message": "Emergency stop latched"})
    if hazards.get("critical"):
        alerts.append({"severity": "critical", "category": "HAZARD",
                       "message": f"{hazards.get('critical')} critical hazard(s)"})
    elif hazards.get("active"):
        alerts.append({"severity": "warning", "category": "HAZARD",
                       "message": f"{hazards.get('active')} hazard(s) active"})
    if mission.get("state") == "COMPLETED":
        alerts.append({"severity": "info", "category": "MISSION",
                       "message": "Mission completed"})
    if mission.get("state") == "FAILED":
        alerts.append({"severity": "critical", "category": "MISSION",
                       "message": "Mission failed"})
    errors = system.get("errors") if isinstance(system.get("errors"), list) else []
    for err in errors[:5]:
        alerts.append({"severity": "warning", "category": "SYSTEM",
                       "message": str(err)[:120]})
    for event in events:
        if str(event.get("level")) == "CRITICAL":
            alerts.append({"severity": "critical",
                           "category": _txt(event.get("category")) or "SYSTEM",
                           "message": _txt(event.get("message")) or "critical event",
                           "t": _num(event.get("t"))})
    # Newest first, and de-duplicated so one repeating condition is not listed
    # ten times.
    seen, unique = set(), []
    for alert in reversed(alerts):
        key = (alert["severity"], alert["category"], alert["message"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(alert)
    return unique[:25]


def _replay_summary(replay: Any) -> Dict[str, Any]:
    """Replay analytics, counted from the recording itself.

    Empty while no recording is loaded — the summary is a post-run artefact, so
    inventing one beforehand would be reporting on a run that has not happened.
    """
    rep = _section({}, "replay") if not isinstance(replay, dict) else replay
    if not rep or not rep.get("recording_id"):
        return {"available": False, "reason": "no recording loaded"}
    return {
        "available": True,
        "recording_id": _txt(rep.get("recording_id")),
        "state": _txt(rep.get("state")),
        "frames": rep.get("frames"),
        "total_frames": rep.get("total_frames"),
        "position_s": _num(rep.get("position")),
        "duration_s": _num(rep.get("duration")),
        "speed": _num(rep.get("speed")),
    }


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def build_ops_state(console: Any, *, history: Any = None, replay: Any = None,
                    recording: Any = None, tick_hz: Any = None) -> Dict[str, Any]:
    """Assemble the C5e operations projection from an existing console payload.

    :param console: the dict :func:`amr.telemetry.console.build_console_state`
        already produces. This function reads it and nothing else — it does not
        re-collect telemetry, re-tick the runtime, or open a second data path.
    :param history: the C15c history payload (charts + event stream).
    :param replay: the C14b replay status.
    :param recording: the C14c recorder status.
    :param tick_hz: the control-loop rate, reported verbatim.
    """
    con = console if isinstance(console, dict) else {}
    # recording/replay normally already ride inside the console payload; the
    # explicit arguments win so callers can pass them straight through.
    rec = recording if isinstance(recording, dict) else con.get("recording")
    rep = replay if isinstance(replay, dict) else con.get("replay")
    hist = history if isinstance(history, dict) else con.get("history")

    event_block = _section(hist, "events")
    events = event_block.get("events") if isinstance(
        event_block.get("events"), list) else []

    components = _component_health(con, None)
    health = {
        # Categorical, never a fabricated percentage: the worst subsystem wins
        # and the list below is the evidence for that verdict.
        "overall": _worst([c["state"] for c in components]),
        "score": None,
        "score_note": ("no numeric score: the project defines no weighting "
                       "that would justify one"),
        "components": components,
    }
    mission = _section(con, "mission")
    safety = _section(con, "safety")
    hazards = _section(con, "hazards")
    return {
        "schema_version": OPS_SCHEMA_VERSION,
        "read_only": True,
        "identity": _identity(con),
        "health": health,
        "sensors": _sensor_matrix(con),
        "system": _system_panel(con, rec, rep),
        "navigation": _navigation(con),
        "mission": {
            "timeline": _mission_timeline(mission, events),
            "statistics": _mission_stats(mission, safety, hazards, events),
        },
        "hazards": _hazard_centre(con, events),
        "safety_history": [
            {"t": _num(e.get("t")), "level": _txt(e.get("level")),
             "message": _txt(e.get("message"))}
            for e in events if str(e.get("category")) == "SAFETY"
        ][:50],
        "performance": _performance(con, hist, rep, tick_hz),
        "alerts": _alerts(con, events),
        "replay_summary": _replay_summary(rep),
    }






