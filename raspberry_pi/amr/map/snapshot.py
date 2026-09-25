"""C9 — warehouse map snapshot (read-only projection of the existing runtime).

A :class:`MapSnapshot` is the presentation-independent *map state*: everything a
2D SVG map and the future C10 3D digital twin need, already resolved into world
coordinates. Neither view may compute map semantics itself, so the two can never
disagree.

It is an **adapter**, not a new model: every field is read from objects the
project already owns.

====================  ====================================================
Snapshot field        Existing source
====================  ====================================================
``warehouse``         ``WarehouseConfig.locations`` / ``WarehouseMap``
``zones``             ``HazardZone`` rectangles (``hazard.zones`` config)
``robot``             ``Navigator.current_pose()``
``route`` / ``goal``  ``Navigator.plan(goal)`` / ``Navigator.goal``
``hazards``           ``HazardManager.snapshot()`` -> ``active_events``
``safety``            the C7 telemetry snapshot
====================  ====================================================

Coordinate convention (the repository's own, not a new one)
---------------------------------------------------------
Warehouse world frame: ``x``/``y`` in **metres**, **y-up**, ``theta`` in
**radians**. This is the convention of ``amr.navigation.types.Pose`` and
``config/warehouse.yaml``. It is preserved verbatim here; the y-flip and scale
belong to the screen transform (:mod:`amr.map.transform`), never to this model.

Honesty rules encoded here
--------------------------
* **No fabricated geometry.** The repository models the warehouse as named
  waypoints plus explicit hazard-zone rectangles. It has no shelf, rack, static
  obstacle or surveyed boundary geometry, so :class:`MapStatic` reports those as
  ``UNAVAILABLE`` with an explanatory note instead of inventing rectangles.
* **No fabricated world coordinates.** A hazard is placed only when the event
  carries a real world ``location``. A vision detection with an image-space
  bounding box is reported under ``unlocated`` and never given an (x, y).
* **No fabricated provenance.** Every section carries a source tag; simulated
  geometry is ``SIMULATION``, never ``LIVE``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: Map payload schema, independent of the telemetry schema version.
MAP_SCHEMA_VERSION = "1.0"

#: Why static geometry is empty, surfaced to the operator instead of hidden.
NO_STATIC_GEOMETRY = (
    "not modelled: the warehouse is defined as named waypoints "
    "(warehouse.locations) plus hazard zones; no shelf, rack, static-obstacle "
    "or surveyed-boundary geometry exists in the project yet"
)

#: Provenance tags, mirroring :class:`amr.telemetry.types.DataSource`. Declared
#: as plain strings so ``amr.map`` stays importable without the telemetry
#: package (a map model must not depend on the HTTP/dashboard layer).
LIVE = "LIVE"
SIMULATION = "SIMULATION"
UNAVAILABLE = "UNAVAILABLE"


def is_num(v: Any) -> bool:
    """``True`` for a finite real number (``bool`` is not a measurement)."""
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def enum_str(v: Any) -> Optional[str]:
    """Best-effort enum/member to its string value."""
    if v is None:
        return None
    value = getattr(v, "value", v)
    return value if isinstance(value, str) else str(value)


def source_tag(simulated: bool, present: bool) -> str:
    """Provenance: absent data is UNAVAILABLE, never SIMULATION."""
    if not present:
        return UNAVAILABLE
    return SIMULATION if simulated else LIVE


@dataclass(frozen=True)
class MapZone:
    """An axis-aligned rectangle of interest in world metres.

    Matches :class:`amr.hazard.sources.HazardZone` (C5) so the same rectangle is
    used for hazard evaluation and for display.
    """

    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    severity: Optional[str] = None
    kind: Optional[str] = None
    source: str = SIMULATION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "x_min": self.x_min,
            "x_max": self.x_max,
            "y_min": self.y_min,
            "y_max": self.y_max,
            "severity": self.severity,
            "kind": self.kind,
            "source": self.source,
        }


@dataclass(frozen=True)
class MapWaypoint:
    """A named warehouse location (dock, shelf, station...)."""

    name: str
    x: float
    y: float
    theta: float
    source: str = SIMULATION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "theta": self.theta,
            "source": self.source,
        }


@dataclass(frozen=True)
class MapStatic:
    """Static warehouse geometry — reported honestly, never invented.

    ``shelves``/``racks``/``obstacles`` are empty *by design*: the project has no
    such geometry. ``boundary`` is ``None`` for the same reason. The viewport
    the renderer uses is derived from the real data extent instead and published
    as :attr:`bounds`, so the UI can label it a fit-to-data frame rather than a
    surveyed wall.
    """

    waypoints: Tuple[MapWaypoint, ...] = ()
    shelves: Tuple[Dict[str, Any], ...] = ()
    racks: Tuple[Dict[str, Any], ...] = ()
    obstacles: Tuple[Dict[str, Any], ...] = ()
    boundary: Optional[Dict[str, float]] = None
    bounds: Optional[Dict[str, float]] = None
    source: str = UNAVAILABLE
    note: str = NO_STATIC_GEOMETRY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "waypoints": [w.to_dict() for w in self.waypoints],
            "shelves": [dict(s) for s in self.shelves],
            "racks": [dict(r) for r in self.racks],
            "obstacles": [dict(o) for o in self.obstacles],
            "boundary": dict(self.boundary) if self.boundary else None,
            "bounds": dict(self.bounds) if self.bounds else None,
            "source": self.source,
            "note": self.note,
        }


@dataclass(frozen=True)
class MapRobot:
    """The AMR's pose in world metres, from the navigator's own odometry."""

    x: float
    y: float
    yaw: float
    source: str = UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {"x": self.x, "y": self.y, "yaw": self.yaw, "source": self.source}


@dataclass(frozen=True)
class MapGoal:
    """The active navigation goal, as world coordinates."""

    name: str
    x: float
    y: float
    theta: float
    source: str = UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "theta": self.theta,
            "source": self.source,
        }


@dataclass(frozen=True)
class MapHazard:
    """An active hazard event placed on the map.

    ``x``/``y`` are world coordinates **only**. A hazard whose evidence is
    image-space (a vision bounding box) is reported in
    :attr:`MapSnapshot.unlocated` instead, preserving the C5 rule.
    """

    kind: str
    severity: Optional[str]
    confidence: Optional[float]
    source: Optional[str]
    x: float
    y: float
    raised_at: Optional[float] = None
    event_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "confidence": self.confidence,
            "source": self.source,
            "x": self.x,
            "y": self.y,
            "raised_at": self.raised_at,
            "event_id": self.event_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class MapPoint:
    """A world point on the planned route or the travelled path."""

    x: float
    y: float

    def to_dict(self) -> Dict[str, Any]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True)
class MapSafety:
    """Current safety verdict — displayed, never acted on by the map."""

    state: Optional[str] = None
    action: Optional[str] = None
    emergency_stop: bool = False
    hazard_state: Optional[str] = None
    latched: bool = False
    source: str = UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "action": self.action,
            "emergency_stop": self.emergency_stop,
            "hazard_state": self.hazard_state,
            "latched": self.latched,
            "source": self.source,
        }


@dataclass(frozen=True)
class MapSnapshot:
    """Complete, presentation-independent map state for one instant.

    The 2D SVG renderer and the future C10 3D twin both consume this object, so
    map semantics live here rather than in drawing code.
    """

    robot: Optional[MapRobot] = None
    goal: Optional[MapGoal] = None
    route: Tuple[MapPoint, ...] = ()
    path: Tuple[MapPoint, ...] = ()
    hazards: Tuple[MapHazard, ...] = ()
    unlocated: Tuple[Dict[str, Any], ...] = ()
    zones: Tuple[MapZone, ...] = ()
    static: MapStatic = field(default_factory=MapStatic)
    safety: MapSafety = field(default_factory=MapSafety)
    navigation_state: Optional[str] = None
    source: str = UNAVAILABLE
    schema_version: str = MAP_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "units": "metres",
            "frame": "warehouse",
            "y_axis": "up",
            "yaw_units": "radians",
            "warehouse": self.static.to_dict(),
            "robot": self.robot.to_dict() if self.robot else None,
            "goal": self.goal.to_dict() if self.goal else None,
            "route": [p.to_dict() for p in self.route],
            "path": [p.to_dict() for p in self.path],
            "hazards": [h.to_dict() for h in self.hazards],
            "unlocated": [dict(u) for u in self.unlocated],
            "zones": [z.to_dict() for z in self.zones],
            "safety": self.safety.to_dict(),
            "navigation": {"state": self.navigation_state},
        }


# --------------------------------------------------------------------------- #
# Adapters: existing runtime -> map state
# --------------------------------------------------------------------------- #
def waypoints_from(locations: Any,
                   simulated: bool = True) -> Tuple[MapWaypoint, ...]:
    """Adapt ``{name: {x,y,theta}}`` / ``{name: [x,y,theta]}`` to waypoints.

    Accepts the same shapes :class:`amr.warehouse.map.WarehouseMap` accepts, plus
    a ``WarehouseMap`` instance itself, so the map never needs a second copy of
    the warehouse configuration.
    """
    if locations is None:
        return ()
    if hasattr(locations, "names") and hasattr(locations, "pose"):
        items: Iterable[Tuple[str, Any]] = (
            (n, locations.pose(n)) for n in locations.names()
        )
    elif isinstance(locations, dict):
        items = locations.items()
    else:
        return ()
    out: List[MapWaypoint] = []
    for name, value in items:
        try:
            if isinstance(value, dict):
                x, y = value.get("x"), value.get("y")
                theta = value.get("theta", 0.0)
            elif isinstance(value, (list, tuple)) and len(value) >= 2:
                x, y = value[0], value[1]
                theta = value[2] if len(value) > 2 else 0.0
            else:
                x = getattr(value, "x", None)
                y = getattr(value, "y", None)
                theta = getattr(value, "theta", 0.0)
            if not (is_num(x) and is_num(y)):
                continue
            out.append(MapWaypoint(
                name=str(name),
                x=float(x),
                y=float(y),
                theta=float(theta) if is_num(theta) else 0.0,
                source=source_tag(simulated, True),
            ))
        except Exception:  # noqa: BLE001 - one bad entry must not break the map
            continue
    return tuple(out)


def zones_from(any_zones: Any,
               simulated: bool = True) -> Tuple[MapZone, ...]:
    """Adapt C5 ``HazardZone`` objects (or dicts) to drawable rectangles."""
    if not any_zones:
        return ()
    out: List[MapZone] = []
    for z in any_zones:
        try:
            get = z.get if isinstance(z, dict) else (
                lambda k, _z=z: getattr(_z, k, None))
            vals = [get("x_min"), get("x_max"), get("y_min"), get("y_max")]
            if not all(is_num(v) for v in vals):
                continue
            x_min, x_max = float(vals[0]), float(vals[1])
            y_min, y_max = float(vals[2]), float(vals[3])
            # Normalise like HazardZone.__post_init__ (C5) does: a swapped pair
            # is tolerated in config, and an inverted rectangle would otherwise
            # draw as a flipped shape.
            out.append(MapZone(
                name=str(get("name") or "zone"),
                x_min=min(x_min, x_max), x_max=max(x_min, x_max),
                y_min=min(y_min, y_max), y_max=max(y_min, y_max),
                severity=enum_str(get("severity")),
                kind=enum_str(get("kind")),
                source=source_tag(simulated, True),
            ))
        except Exception:  # noqa: BLE001
            continue
    return tuple(out)


def robot_from(pose: Any, simulated: bool = True) -> Optional[MapRobot]:
    """Adapt a pose (``Pose`` / ``HazardLocation`` / dict) to the robot marker."""
    if pose is None:
        return None
    try:
        if isinstance(pose, dict):
            x, y = pose.get("x"), pose.get("y")
            yaw = pose.get("theta", 0.0)
        else:
            x = getattr(pose, "x", None)
            y = getattr(pose, "y", None)
            yaw = getattr(pose, "theta", 0.0)
        if not (is_num(x) and is_num(y)):
            return None
        return MapRobot(
            x=float(x), y=float(y),
            yaw=float(yaw) if is_num(yaw) else 0.0,
            source=source_tag(simulated, True),
        )
    except Exception:  # noqa: BLE001
        return None


def goal_from(goal: Any, simulated: bool = True) -> Optional[MapGoal]:
    """Adapt a ``Goal`` to its world coordinates."""
    if goal is None:
        return None
    robot = robot_from(getattr(goal, "pose", goal), simulated)
    if robot is None:
        return None
    return MapGoal(
        name=str(getattr(goal, "name", None) or "goal"),
        x=robot.x, y=robot.y, theta=robot.yaw,
        source=robot.source,
    )


def route_from(points: Any) -> Tuple[MapPoint, ...]:
    """Adapt planned waypoints to points, skipping anything unusable."""
    out: List[MapPoint] = []
    for p in points or ():
        try:
            if isinstance(p, dict):
                x, y = p.get("x"), p.get("y")
            else:
                x = getattr(p, "x", None)
                y = getattr(p, "y", None)
            if is_num(x) and is_num(y):
                out.append(MapPoint(float(x), float(y)))
        except Exception:  # noqa: BLE001
            continue
    return tuple(out)


def hazards_from(events: Any) -> Tuple[Tuple[MapHazard, ...], Tuple[Dict[str, Any], ...]]:
    """Split active hazard events into located and unlocated groups.

    This is the C5 rule enforced at the map boundary: only an event carrying a
    real world ``location`` becomes a placed marker. Everything else — including
    a vision detection with an image-space bounding box — is reported *without*
    coordinates, so the UI can list it but must not place it.
    """
    located: List[MapHazard] = []
    unlocated: List[Dict[str, Any]] = []
    for ev in events or ():
        if not isinstance(ev, dict):
            continue
        loc = ev.get("location")
        kind = enum_str(ev.get("kind")) or "UNKNOWN"
        confidence = ev.get("confidence")
        try:
            if (isinstance(loc, dict) and is_num(loc.get("x"))
                    and is_num(loc.get("y"))):
                located.append(MapHazard(
                    kind=kind,
                    severity=enum_str(ev.get("severity")),
                    confidence=float(confidence) if is_num(confidence) else None,
                    source=enum_str(ev.get("source")),
                    x=float(loc["x"]), y=float(loc["y"]),
                    raised_at=ev.get("raised_at"),
                    event_id=ev.get("event_id"),
                    metadata=dict(ev.get("metadata") or {}),
                ))
            else:
                # "image-space evidence only" is a different situation from "no
                # location supplied", and the reason is worth showing.
                meta = ev.get("metadata") or {}
                has_bbox = bool(meta.get("bbox"))
                unlocated.append({
                    "kind": kind,
                    "severity": enum_str(ev.get("severity")),
                    "confidence": (float(confidence)
                                   if is_num(confidence) else None),
                    "source": enum_str(ev.get("source")),
                    "event_id": ev.get("event_id"),
                    "reason": ("image-space evidence only; no calibrated world "
                               "location" if has_bbox
                               else "no world location supplied"),
                })
        except Exception:  # noqa: BLE001
            continue
    return tuple(located), tuple(unlocated)


def bounds_for(waypoints: Sequence[MapWaypoint] = (),
               zones: Sequence[MapZone] = (),
               robot: Optional[MapRobot] = None,
               hazards: Sequence[MapHazard] = (),
               goal: Optional[MapGoal] = None,
               margin_m: float = 1.0) -> Optional[Dict[str, float]]:
    """Data extent for the renderer viewport (**not** a surveyed boundary).

    The bounding box of everything genuinely placed, padded by ``margin_m``.
    With no placed geometry at all this returns ``None`` so the UI can report
    "no map data" instead of drawing an invented room.
    """
    xs: List[float] = []
    ys: List[float] = []
    for w in waypoints:
        xs.append(w.x)
        ys.append(w.y)
    for z in zones:
        xs.extend((z.x_min, z.x_max))
        ys.extend((z.y_min, z.y_max))
    for h in hazards:
        xs.append(h.x)
        ys.append(h.y)
    if robot is not None:
        xs.append(robot.x)
        ys.append(robot.y)
    if goal is not None:
        xs.append(goal.x)
        ys.append(goal.y)
    if not xs or not ys:
        return None
    pad = max(0.0, float(margin_m))
    return {
        "x_min": min(xs) - pad,
        "x_max": max(xs) + pad,
        "y_min": min(ys) - pad,
        "y_max": max(ys) + pad,
    }


def _call_or_value(obj: Any, name: str) -> Any:
    """Read ``obj.name`` whether it is a property, method or plain attribute.

    Runtime collaborators are inconsistent (e.g. ``Navigator.status`` is a
    property while other implementations expose ``status()``), so both shapes are
    accepted. A raising getter degrades to ``None`` instead of taking the map
    down.
    """
    try:
        value = getattr(obj, name, None)
    except Exception:  # noqa: BLE001
        return None
    if callable(value):
        try:
            return value()
        except Exception:  # noqa: BLE001
            return None
    return value


def build_map_snapshot(
        *,
        locations: Any = None,
        zones: Any = (),
        navigator: Any = None,
        hazard_snapshot: Any = None,
        telemetry: Any = None,
        path: Sequence[MapPoint] = (),
        simulated: bool = False) -> MapSnapshot:
    """Assemble a :class:`MapSnapshot` from the existing runtime objects.

    Every collaborator is optional and every read is guarded: a missing or
    broken navigator, hazard layer or telemetry collector degrades that section
    to ``None``/``UNAVAILABLE`` rather than raising. The function performs no
    writes and calls no movement API, so it cannot move the robot.
    """
    wps = waypoints_from(locations, simulated)
    zns = zones_from(zones, simulated)

    pose = goal = route = None
    nav_state = None
    if navigator is not None:
        pose = _call_or_value(navigator, "current_pose")
        goal = _call_or_value(navigator, "goal")
        nav_state = enum_str(_call_or_value(navigator, "status"))
        if goal is not None:
            try:
                plan = getattr(navigator, "plan", None)
                if callable(plan):
                    route = route_from(plan(goal))
            except Exception:  # noqa: BLE001
                route = ()

    robot = robot_from(pose, simulated)
    goal_obj = goal_from(goal, simulated)
    hazards: Tuple[MapHazard, ...] = ()
    unlocated: Tuple[Dict[str, Any], ...] = ()
    if isinstance(hazard_snapshot, dict):
        # `HazardManager.snapshot()` publishes `active_events` directly; the
        # `attached` key exists only in the C2 web payload, so keying off it
        # alone would silently drop every real hazard. Accept either shape, but
        # honour an explicit `attached: false` as "no layer".
        if hazard_snapshot.get("attached") is not False:
            hazards, unlocated = hazards_from(hazard_snapshot.get("active_events"))

    safety = MapSafety()
    if telemetry is not None:
        try:
            snap = (_call_or_value(telemetry, "snapshot")
                    or _call_or_value(telemetry, "collect") or {})
            t_safety = snap.get("safety") or {}
            t_hazard = snap.get("hazards") or {}
            safety = MapSafety(
                state=t_safety.get("state"),
                action=t_safety.get("action"),
                emergency_stop=bool(t_safety.get("emergency_stop")),
                hazard_state=t_hazard.get("state"),
                latched=bool(t_hazard.get("latched")),
                source=source_tag(simulated, bool(t_safety)),
            )
        except Exception:  # noqa: BLE001
            safety = MapSafety()

    static = MapStatic(
        waypoints=wps,
        bounds=bounds_for(wps, zns, robot, hazards, goal_obj),
        source=source_tag(simulated, bool(wps or zns)),
    )
    return MapSnapshot(
        robot=robot,
        goal=goal_obj,
        route=route or (),
        path=tuple(path),
        hazards=hazards,
        unlocated=unlocated,
        zones=zns,
        static=static,
        safety=safety,
        navigation_state=nav_state,
        source=source_tag(simulated, robot is not None or bool(wps)),
    )
