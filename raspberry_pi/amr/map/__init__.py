"""C9 — read-only 2D warehouse map for the AMR dashboard.

Two layers, deliberately separate:

* :mod:`amr.map.snapshot` — the **map state**: a presentation-independent
  :class:`~amr.map.snapshot.MapSnapshot` assembled from objects the project
  already owns (warehouse locations, hazard zones, navigator pose/goal/route,
  hazard events, telemetry safety). No HTTP, no drawing.
* :mod:`amr.map.transform` — the **single** world->screen conversion plus a
  bounded :class:`~amr.map.transform.PathHistory`.

:class:`MapService` binds them for the web layer: it samples the runtime, keeps a
bounded travelled-path trail, and publishes both the JSON snapshot and the SVG
document. C10's 3D twin will consume the same ``MapSnapshot`` rather than
re-deriving map state from the runtime, so the two views cannot disagree.

This package **never** commands the robot: it imports no motor, PWM, serial or
GPIO code and calls no navigation movement method.
"""

from .snapshot import (
    LIVE,
    MAP_SCHEMA_VERSION,
    NO_STATIC_GEOMETRY,
    SIMULATION,
    UNAVAILABLE,
    MapGoal,
    MapHazard,
    MapPoint,
    MapRobot,
    MapSafety,
    MapSnapshot,
    MapStatic,
    MapWaypoint,
    MapZone,
    bounds_for,
    build_map_snapshot,
    enum_str,
    goal_from,
    hazards_from,
    is_num,
    robot_from,
    route_from,
    source_tag,
    waypoints_from,
    zones_from,
)
from .transform import DEFAULT_PATH_LIMIT, MapTransform, PathHistory

# Imported last: MapService builds on the two modules above.
from .service import MapService  # noqa: E402  (circular-import-free by design)

__all__ = [
    "DEFAULT_PATH_LIMIT",
    "LIVE",
    "MAP_SCHEMA_VERSION",
    "MapGoal",
    "MapHazard",
    "MapPoint",
    "MapRobot",
    "MapSafety",
    "MapService",
    "MapSnapshot",
    "MapStatic",
    "MapTransform",
    "MapWaypoint",
    "MapZone",
    "MapService",
    "NO_STATIC_GEOMETRY",
    "PathHistory",
    "SIMULATION",
    "UNAVAILABLE",
    "bounds_for",
    "build_map_snapshot",
    "enum_str",
    "goal_from",
    "hazards_from",
    "is_num",
    "robot_from",
    "route_from",
    "source_tag",
    "waypoints_from",
    "zones_from",
]
