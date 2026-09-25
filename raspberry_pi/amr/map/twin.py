"""C10 — 3D digital twin state, derived from the C9 ``MapSnapshot``.

The twin is a **view**, not a robot system. It never reads the runtime, never
commands anything, and holds no robot state of its own: :func:`build_twin_state`
takes the very same :class:`~amr.map.snapshot.MapSnapshot` the 2D map renders, so
the 2D and 3D views cannot disagree.

What this module adds is exactly two things the 2D view does not need:

1. **The world → 3D conversion**, centralised here (in Python, where it is unit
   tested) instead of being scattered through the browser's drawing code.
2. **Scene assembly** — a small procedural description of the AMR and the
   warehouse for the renderer to draw.

Coordinate conversion (the one place it happens)
------------------------------------------------
The repository frame is 2D, **y-up**, right-handed, yaw CCW from +x
(:mod:`amr.map.snapshot`). A 3D renderer is **z-up**, with ``y`` pointing the
other way on screen. The mapping used throughout is::

    three.x =  world.x
    three.y = -world.y      # y-up -> screen-depth
    three.z =  height       # metres above the floor

and for heading, rotating +x onto -y is a **negative** rotation about +z, so::

    rotation_z_deg = -degrees(yaw)

That single negation is the same one the 2D SVG renderer applies to yaw, which is
why the two views agree. A yaw of 0 points the AMR along world +x (its
configured forward direction); ``+pi/2`` turns it 90 deg CCW in world terms and
therefore -90 deg about the renderer's z axis.

Renderer
--------
The browser renderer is **raw WebGL with no third-party library** (see
``docs/digital_twin.md`` for why). This module therefore describes *what* to
draw in plain arrays/objects; it deliberately does not emit GLSL or matrices.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .snapshot import (
    UNAVAILABLE,
    MapPoint,
    MapSnapshot,
    is_num,
)

#: Twin payload schema. Independent of the map schema it is derived from.
TWIN_SCHEMA_VERSION = "1.0"

#: The twin's own coordinate description, published so a client never guesses.
TWIN_COORDINATE_SYSTEM = {
    "units": "metres",
    "source_frame": "warehouse",
    "source_y_axis": "up",
    "source_yaw_units": "radians",
    "up_axis": "z",
    "axis_map": "three.x=world.x, three.y=-world.y, three.z=height",
    "yaw_rule": "rotation_z_deg = -degrees(world_yaw)",
}

#: Robot envelope in metres. Nominal, unmeasured, and labelled as such: they
#: describe a schematic AMR, not a surveyed CAD model.
ROBOT_LENGTH_M = 0.60
ROBOT_WIDTH_M = 0.40
ROBOT_HEIGHT_M = 0.28
WHEEL_RADIUS_M = 0.08
CAMERA_HEIGHT_M = 0.40
#: Floor marker radius for a waypoint/goal in the twin.
MARKER_RADIUS_M = 0.15
#: Extrusion height for a hazard zone, purely so it reads in 3D.
ZONE_HEIGHT_M = 0.05

#: Shown in the UI so the scene is never mistaken for a surveyed building.
GEOMETRY_DISCLAIMER = (
    "schematic: the project has no surveyed shelf, rack, boundary or static-"
    "obstacle geometry. Only waypoints, hazard zones and the AMR pose are real."
)

_SEVERITY_CRITICAL = ("EMERGENCY", "STOP", "CRITICAL")


def yaw_to_rotation_z(yaw: float) -> float:
    """World yaw (radians, CCW, y-up) -> renderer rotation about +z (degrees).

    The negation is the y-up -> z-up axis swap; see the module docstring. Invalid
    input yields ``0.0`` rather than propagating NaN into a matrix.
    """
    if not is_num(yaw):
        return 0.0
    return -math.degrees(float(yaw))


def world_to_three(x: float, y: float, z: float = 0.0) -> Optional[List[float]]:
    """Convert a world point (metres, y-up) to renderer coordinates ``[x,y,z]``.

    Returns ``None`` for unusable input so the renderer can omit the shape
    rather than drawing something at the origin.
    """
    if not (is_num(x) and is_num(y)):
        return None
    return [float(x), -float(y), float(z) if is_num(z) else 0.0]


def _points3(points: Sequence[MapPoint], z: float = 0.0) -> List[List[float]]:
    """Convert a run of world points, dropping any that cannot be mapped."""
    out: List[List[float]] = []
    for p in points or ():
        mapped = world_to_three(p.x, p.y, z)
        if mapped is not None:
            out.append(mapped)
    return out


def robot_model() -> Dict[str, Any]:
    """Procedural AMR: chassis, four wheels, camera mast, sensor + mount.

    A functional digital twin, not a CAD model — simple primitives only, so the
    renderer needs no asset loading and the whole page stays self-contained.
    ``forward`` is +x in renderer space, matching ``yaw = 0``.
    """
    hl, hw = ROBOT_LENGTH_M / 2.0, ROBOT_WIDTH_M / 2.0
    # Wheel corner offsets: x is forward/back, y is left/right.
    wheels = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            wheels.append({
                "position": [sx * (hl - WHEEL_RADIUS_M), sy * hw, WHEEL_RADIUS_M],
                "radius": WHEEL_RADIUS_M,
                "width": 0.05,
                "axis": "y",
            })
    return {
        "chassis": {
            "size": [ROBOT_LENGTH_M, ROBOT_WIDTH_M, ROBOT_HEIGHT_M],
            "center_z": WHEEL_RADIUS_M + ROBOT_HEIGHT_M / 2.0,
        },
        "deck": {
            "size": [ROBOT_LENGTH_M * 0.8, ROBOT_WIDTH_M * 0.8, 0.02],
            "center_z": WHEEL_RADIUS_M + ROBOT_HEIGHT_M + 0.01,
        },
        "wheels": wheels,
        # The C8 camera, represented as a module on the front face. It is a
        # *model* of the sensor, never live imagery.
        "camera": {
            "position": [hl - 0.05, 0.0, CAMERA_HEIGHT_M],
            "size": [0.06, 0.10, 0.06],
            "fov_deg": 62.0,
        },
        "sensor": {
            "position": [0.0, 0.0, WHEEL_RADIUS_M + ROBOT_HEIGHT_M + 0.10],
            "radius": 0.05,
            "height": 0.10,
            "kind": "ultrasonic_mast",
        },
        # A visual mount only: no manipulator is implemented (that is a later
        # milestone), so the renderer shows where one would attach.
        "manipulator_mount": {
            "position": [0.0, 0.0, WHEEL_RADIUS_M + ROBOT_HEIGHT_M + 0.02],
            "size": [0.20, 0.20, 0.02],
            "implemented": False,
        },
        "forward_axis": "+x",
        "envelope": {
            "length_m": ROBOT_LENGTH_M,
            "width_m": ROBOT_WIDTH_M,
            "height_m": ROBOT_HEIGHT_M,
        },
    }


def _floor_frame(bounds: Optional[Dict[str, float]]) -> Dict[str, Any]:
    """Scene floor sized to the real data extent (never a claimed building size)."""
    if not bounds:
        return {"available": False,
                "note": "no map data: the floor is not sized or drawn"}
    x_min, x_max = float(bounds["x_min"]), float(bounds["x_max"])
    y_min, y_max = float(bounds["y_min"]), float(bounds["y_max"])
    # Add a small apron so edge waypoints are not flush with the plane edge.
    pad = 0.25
    corners = [world_to_three(x_min - pad, y_min - pad),
               world_to_three(x_max + pad, y_min - pad),
               world_to_three(x_max + pad, y_max + pad),
               world_to_three(x_min - pad, y_max + pad)]
    return {
        "available": True,
        "corners": [c for c in corners if c is not None],
        "size_m": [abs(x_max - x_min) + 2 * pad, abs(y_max - y_min) + 2 * pad],
        "source": "data-extent",
        "note": ("floor spans the available data extent; it is not a surveyed "
                 "warehouse boundary"),
    }


def _waypoints3(snap: MapSnapshot) -> List[Dict[str, Any]]:
    """Named waypoints as floor markers. ``role`` is inferred from the name only
    for display emphasis; it never invents a location that is not in the data."""
    out: List[Dict[str, Any]] = []
    for w in snap.static.waypoints:
        pos = world_to_three(w.x, w.y)
        if pos is None:
            continue
        name = (w.name or "").lower()
        role = "waypoint"
        if "dock" in name or "charg" in name:
            role = "dock"
        elif name.startswith("shelf") or "pick" in name:
            role = "pickup"
        elif "station" in name or "drop" in name or "deliver" in name:
            role = "drop"
        out.append({
            "name": w.name,
            "position": pos,
            "radius": MARKER_RADIUS_M,
            "role": role,
            "source": w.source,
        })
    return out


def _zones3(snap: MapSnapshot) -> List[Dict[str, Any]]:
    """Hazard/restricted zones as low extruded slabs in renderer space."""
    out: List[Dict[str, Any]] = []
    for z in snap.zones:
        lo = world_to_three(z.x_min, z.y_min, 0.0)
        hi = world_to_three(z.x_max, z.y_max, ZONE_HEIGHT_M)
        if lo is None or hi is None:
            continue
        out.append({
            "name": z.name,
            "min": lo,
            "max": hi,
            "height_m": ZONE_HEIGHT_M,
            "severity": z.severity,
            "kind": z.kind,
            "source": z.source,
            "restricted": True,
        })
    return out


def _hazards3(snap: MapSnapshot) -> List[Dict[str, Any]]:
    """Placed hazards as vertical markers.

    Only entries in ``MapSnapshot.hazards`` appear, and that tuple is populated
    **only** for events carrying a real world location (C9/C5 rule), so an
    image-space detection can never reach this function with coordinates.
    """
    out: List[Dict[str, Any]] = []
    for h in snap.hazards:
        pos = world_to_three(h.x, h.y, 0.0)
        if pos is None:
            continue
        critical = (h.severity or "").upper() in _SEVERITY_CRITICAL
        out.append({
            "kind": h.kind,
            "severity": h.severity,
            "confidence": h.confidence,
            "source": h.source,
            "position": pos,
            "height_m": 0.45 if critical else 0.30,
            "radius_m": 0.10,
            "critical": critical,
        })
    return out


def _robot3(snap: MapSnapshot) -> Optional[Dict[str, Any]]:
    """The AMR's renderer transform, from ``MapSnapshot.robot`` only.

    ``None`` when there is no pose — the renderer then shows no robot rather
    than parking one at the origin, which is a real place (the dock).
    """
    r = snap.robot
    if r is None:
        return None
    pos = world_to_three(r.x, r.y, 0.0)
    if pos is None:
        return None
    return {
        "position": pos,
        "rotation_z_deg": yaw_to_rotation_z(r.yaw),
        "yaw_rad": float(r.yaw),
        "source": r.source,
        "model": robot_model(),
    }


def _goal3(snap: MapSnapshot) -> Optional[Dict[str, Any]]:
    if snap.goal is None:
        return None
    pos = world_to_three(snap.goal.x, snap.goal.y, 0.0)
    if pos is None:
        return None
    return {
        "name": snap.goal.name,
        "position": pos,
        "rotation_z_deg": yaw_to_rotation_z(snap.goal.theta),
        "source": snap.goal.source,
        "radius": MARKER_RADIUS_M,
    }


@dataclass(frozen=True)
class DigitalTwinState:
    """Presentation-independent 3D scene state for one instant.

    Deliberately a *derived view*: every value traces back to a field of the
    supplied :class:`~amr.map.snapshot.MapSnapshot`. The twin keeps no robot
    state, so it cannot drift from the 2D view or from the runtime.
    """

    source: str = UNAVAILABLE
    floor: Dict[str, Any] = field(default_factory=dict)
    waypoints: List[Dict[str, Any]] = field(default_factory=list)
    zones: List[Dict[str, Any]] = field(default_factory=list)
    hazards: List[Dict[str, Any]] = field(default_factory=list)
    unlocated: List[Dict[str, Any]] = field(default_factory=list)
    route: List[List[float]] = field(default_factory=list)
    path: List[List[float]] = field(default_factory=list)
    robot: Optional[Dict[str, Any]] = None
    goal: Optional[Dict[str, Any]] = None
    safety: Dict[str, Any] = field(default_factory=dict)
    mission: Dict[str, Any] = field(default_factory=dict)
    camera: Dict[str, Any] = field(default_factory=dict)
    navigation: Dict[str, Any] = field(default_factory=dict)
    geometry_disclaimer: str = GEOMETRY_DISCLAIMER
    renderer: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = TWIN_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "coordinate_system": dict(TWIN_COORDINATE_SYSTEM),
            "geometry_disclaimer": self.geometry_disclaimer,
            "floor": dict(self.floor),
            "waypoints": [dict(w) for w in self.waypoints],
            "zones": [dict(z) for z in self.zones],
            "hazards": [dict(h) for h in self.hazards],
            "unlocated": [dict(u) for u in self.unlocated],
            "route": [list(p) for p in self.route],
            "path": [list(p) for p in self.path],
            "robot": dict(self.robot) if self.robot else None,
            "goal": dict(self.goal) if self.goal else None,
            "safety": dict(self.safety),
            "mission": dict(self.mission),
            "camera": dict(self.camera),
            "navigation": dict(self.navigation),
            "renderer": dict(self.renderer),
        }


def _call_or_value(obj: Any, name: str) -> Any:
    """Read ``obj.name`` whether it is a property, method or plain attribute."""
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


def build_twin_state(
    snap: MapSnapshot,
    *,
    telemetry: Any = None,
    camera: Any = None,
) -> DigitalTwinState:
    """Derive the 3D scene from a C9 :class:`MapSnapshot`.

    :param snap: the canonical map state — the single source of truth.
    :param telemetry: optional C7 collector, read only to surface mission status.
        The twin never re-derives it; it shows what the dashboard already shows.
    :param camera: optional C8 source, for the camera module's status label.
    """
    mission: Dict[str, Any] = {}
    if telemetry is not None:
        try:
            snap_dict = (_call_or_value(telemetry, "snapshot")
                         or _call_or_value(telemetry, "collect") or {})
            t_mission = snap_dict.get("mission") or {}
            # Field names come from the existing telemetry contract; no new
            # mission states are invented.
            mission = {
                "mission_id": t_mission.get("mission_id"),
                "current_task": t_mission.get("current_task"),
                "current_task_type": t_mission.get("current_task_type"),
                "current_task_status": t_mission.get("current_task_status"),
                "completed_tasks": t_mission.get("completed_tasks"),
                "failed_tasks": t_mission.get("failed_tasks"),
                "source": t_mission.get("source"),
            }
        except Exception:  # noqa: BLE001 - a twin must never break the panel
            mission = {}
    camera_info: Dict[str, Any] = {}
    if camera is not None:
        try:
            describe = getattr(camera, "describe", None)
            got = describe() if callable(describe) else None
            if isinstance(got, dict):
                camera_info = {
                    "status": got.get("status"),
                    "name": got.get("name"),
                    "simulated": bool(got.get("simulated")),
                }
        except Exception:  # noqa: BLE001
            camera_info = {}

    return DigitalTwinState(
        source=snap.source,
        floor=_floor_frame(snap.static.bounds),
        waypoints=_waypoints3(snap),
        zones=_zones3(snap),
        hazards=_hazards3(snap),
        # Carried through verbatim: these hazards have NO world location, so the
        # renderer must keep them unplaced.
        unlocated=[dict(u) for u in snap.unlocated],
        route=_points3(snap.route),
        # The bounded C9 trail — the browser never accumulates its own history.
        path=_points3(snap.path),
        robot=_robot3(snap),
        goal=_goal3(snap),
        safety=dict(snap.safety.to_dict()),
        mission=mission,
        camera=camera_info,
        navigation={"state": snap.navigation_state},
        renderer={
            "backend": "webgl",
            "library": None,
            "shading": "flat",
            "note": "raw WebGL, no third-party 3D library, no build step",
        },
    )
