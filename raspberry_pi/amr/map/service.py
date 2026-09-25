"""C9 — the service binding map state, path history and rendering.

:class:`MapService` is the only object the web layer talks to. It owns the
references to the existing runtime collaborators (navigator, hazard layer,
telemetry collector, warehouse locations), a bounded
:class:`~amr.map.transform.PathHistory` fed from the navigator's own pose, and
the current :class:`~amr.map.snapshot.MapSnapshot`.

Read-only guarantee
-------------------
Every method only *reads*. The service never calls ``tick``, ``step``, ``go_to``,
``dispatch`` or any motor API, and imports no control/communication code. A test
asserts this by spying on those methods.
"""

from __future__ import annotations

import html
import math
from typing import Any, Dict, List, Optional, Tuple

from .snapshot import (
    MapHazard,
    MapSnapshot,
    build_map_snapshot,
)
from .transform import DEFAULT_PATH_LIMIT, MapTransform, PathHistory

#: Palette. Kept in Python (not in JS) so the SVG view is reproducible and any
#: future server-side export matches the browser exactly.
COL_BG = "#0b101a"
COL_GRID = "#1b2433"
COL_AXIS = "#33415c"
COL_WAYPOINT = "#38bdf8"
COL_ROUTE = "#38bdf8"
COL_PATH = "#475569"
COL_ZONE = "#f59e0b"
COL_ROBOT = "#22c55e"
COL_GOAL = "#a855f7"
COL_HAZARD = "#ef4444"
COL_TEXT = "#e2e8f0"
COL_MUTED = "#94a3b8"

#: Severities that warrant the loudest hazard marker.
_HAZARD_CRITICAL = ("EMERGENCY", "STOP", "CRITICAL")


def _escape(value: Any) -> str:
    """XML-escape text; waypoint names come from config and must be escaped."""
    return html.escape(str(value), quote=True)


def _fmt(value: float) -> str:
    return f"{value:.2f}"


class MapService:
    """Read-only map state + rendering for one AMR runtime."""

    def __init__(self, *,
                 locations: Any = None,
                 zones: Any = (),
                 navigator: Any = None,
                 hazard_layer: Any = None,
                 telemetry: Any = None,
                 simulated: bool = False,
                 path_limit: int = DEFAULT_PATH_LIMIT) -> None:
        self._locations = locations
        self._zones = tuple(zones or ())
        self._navigator = navigator
        self._hazard_layer = hazard_layer
        self._telemetry = telemetry
        self._simulated = bool(simulated)
        self._path = PathHistory(limit=path_limit)
        self._snapshot: Optional[MapSnapshot] = None

    @property
    def simulated(self) -> bool:
        return self._simulated

    def reset_path(self) -> None:
        self._path.clear()

    # -- state -------------------------------------------------------------- #
    def snapshot(self, record_path: bool = True) -> MapSnapshot:
        """Sample the runtime and return the current map state.

        The pose trail is fed from the navigator's own odometry;
        :class:`~amr.map.transform.PathHistory` de-duplicates and bounds it, so a
        stationary robot cannot fill the buffer.
        """
        hazard_snapshot = None
        if self._hazard_layer is not None:
            try:
                hazard_snapshot = self._hazard_layer.snapshot()
            except Exception:  # noqa: BLE001 - the map must never break the page
                hazard_snapshot = None

        def _build() -> MapSnapshot:
            return build_map_snapshot(
                locations=self._locations,
                zones=self._zones,
                navigator=self._navigator,
                hazard_snapshot=hazard_snapshot,
                telemetry=self._telemetry,
                path=self._path.points(),
                simulated=self._simulated,
            )

        snap = _build()
        if record_path and snap.robot is not None:
            self._path.add(snap.robot.x, snap.robot.y, snap.robot.yaw)
            # Re-attach so the returned snapshot includes the point just added.
            snap = build_map_snapshot(
                locations=self._locations,
                zones=self._zones,
                navigator=self._navigator,
                hazard_snapshot=hazard_snapshot,
                telemetry=self._telemetry,
                path=self._path.points(),
                simulated=self._simulated,
            )
        self._snapshot = snap
        return snap

    def as_dict(self) -> Dict[str, Any]:
        return self.snapshot().to_dict()

    # -- rendering ---------------------------------------------------------- #
    def transform(self, snap: MapSnapshot, width: int, height: int,
                  zoom: float = 1.0, pan_x: float = 0.0,
                  pan_y: float = 0.0) -> Optional[MapTransform]:
        """Build the viewport transform for a snapshot.

        Returns ``None`` when the snapshot has no placed geometry, so the UI can
        render an explicit "no map data" state instead of an empty invented room.
        """
        bounds = snap.static.bounds
        if not bounds:
            return None
        return MapTransform(bounds=bounds, width=width, height=height,
                            zoom=zoom, pan_x=pan_x, pan_y=pan_y)

    def svg(self, width: int = 720, height: int = 460, *,
            zoom: float = 1.0, pan_x: float = 0.0, pan_y: float = 0.0,
            show_labels: bool = True) -> str:
        """Render the current map as a standalone, deterministic SVG document.

        Layer order (back to front): grid, axes, zones, path, route, waypoints,
        goal, hazards, robot. The output is valid XML and is byte-identical for
        identical inputs — no timestamps, no RNG, no iteration-order dependence.
        """
        snap = self.snapshot()
        out: List[str] = []
        add = out.append
        add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {int(width)} '
            f'{int(height)}" width="100%" height="100%" '
            f'preserveAspectRatio="xMidYMid meet" '
            f'class="amr-map" data-source="{_escape(snap.source)}">')
        add(f'<rect x="0" y="0" width="{int(width)}" height="{int(height)}" '
            f'fill="{COL_BG}"/>')

        tr = self.transform(snap, width, height, zoom, pan_x, pan_y)
        if tr is None:
            # Honest empty state: the warehouse is configured as waypoints, so
            # "no bounds" means nothing was available to place.
            add(f'<text x="{int(width) / 2}" y="{int(height) / 2}" '
                f'fill="{COL_MUTED}" font-size="14" text-anchor="middle">'
                f'no map data available</text>')
            add("</svg>")
            return "\n".join(out)

        add('<g class="layer-grid">')
        add(self._grid_svg(tr, int(width), int(height)))
        add("</g>")

        if snap.zones:
            add('<g class="layer-zones">')
            for z in snap.zones:
                r = tr.rect(z.x_min, z.y_min, z.x_max, z.y_max)
                if r is None:
                    continue
                add(f'<rect x="{_fmt(r["x"])}" y="{_fmt(r["y"])}" '
                    f'width="{_fmt(r["width"])}" height="{_fmt(r["height"])}" '
                    f'fill="{COL_ZONE}" fill-opacity="0.10" stroke="{COL_ZONE}" '
                    f'stroke-width="1.5" stroke-dasharray="6 4">'
                    f'<title>{_escape(z.name)} ({_escape(z.severity)})</title>'
                    f"</rect>")
                if show_labels:
                    add(f'<text x="{_fmt(r["x"] + 5)}" y="{_fmt(r["y"] + 14)}" '
                        f'fill="{COL_ZONE}" font-size="10">{_escape(z.name)}</text>')
            add("</g>")

        if len(snap.path) > 1:
            pts = tr.polyline(snap.path)
            if pts:
                add(f'<polyline class="layer-path" points="{pts}" fill="none" '
                    f'stroke="{COL_PATH}" stroke-width="1.5" '
                    f'stroke-dasharray="3 3"/>')

        if len(snap.route) > 1:
            pts = tr.polyline(snap.route)
            if pts:
                add(f'<polyline class="layer-route" points="{pts}" fill="none" '
                    f'stroke="{COL_ROUTE}" stroke-width="2" '
                    f'stroke-linecap="round"/>')

        add('<g class="layer-waypoints">')
        for w in snap.static.waypoints:
            x, y = tr.to_screen(w.x, w.y)
            if not (math.isfinite(x) and math.isfinite(y)):
                continue
            add(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="4" '
                f'fill="none" stroke="{COL_WAYPOINT}" stroke-width="1.5">'
                f'<title>{_escape(w.name)} ({_fmt(w.x)}, {_fmt(w.y)}) m</title>'
                f"</circle>")
            if show_labels:
                add(f'<text x="{_fmt(x + 8)}" y="{_fmt(y + 4)}" '
                    f'fill="{COL_MUTED}" font-size="10">{_escape(w.name)}</text>')
        add("</g>")

        if snap.goal is not None:
            gx, gy = tr.to_screen(snap.goal.x, snap.goal.y)
            if math.isfinite(gx) and math.isfinite(gy):
                add(f'<g class="layer-goal" transform="translate({_fmt(gx)},'
                    f'{_fmt(gy)}) rotate({_fmt(tr.yaw_to_degrees(snap.goal.theta))})">'
                    f'<circle r="7" fill="none" stroke="{COL_GOAL}" '
                    f'stroke-width="2"/>'
                    f'<circle r="2" fill="{COL_GOAL}">'
                    f'<title>goal {_escape(snap.goal.name)}</title></circle></g>')

        if snap.hazards:
            add('<g class="layer-hazards">')
            for h in snap.hazards:
                self._hazard_svg(add, tr, h)
            add("</g>")

        if snap.robot is not None:
            rx, ry = tr.to_screen(snap.robot.x, snap.robot.y)
            if math.isfinite(rx) and math.isfinite(ry):
                # The marker rotates by the navigator's real yaw, so heading on
                # the map is the runtime's heading, never a CSS guess.
                add(f'<g class="layer-robot" data-layer="robot" '
                    f'transform="translate({_fmt(rx)},{_fmt(ry)}) '
                    f'rotate({_fmt(tr.yaw_to_degrees(snap.robot.yaw))})">'
                    f'<polygon points="0,-11 8,8 0,4 -8,8" fill="{COL_ROBOT}" '
                    f'stroke="#0b101a" stroke-width="1">'
                    f'<title>AMR ({_fmt(snap.robot.x)}, {_fmt(snap.robot.y)}) m, '
                    f'yaw {_fmt(snap.robot.yaw)} rad</title></polygon></g>')

        add("</svg>")
        return "\n".join(out)

    def _hazard_svg(self, add, tr: MapTransform, h: MapHazard) -> None:
        """One hazard marker, with a tooltip carrying its real metadata."""
        x, y = tr.to_screen(h.x, h.y)
        if not (math.isfinite(x) and math.isfinite(y)):
            return
        critical = (h.severity or "").upper() in _HAZARD_CRITICAL
        radius = 9 if critical else 7
        colour = COL_HAZARD if critical else COL_ZONE
        conf = ("" if h.confidence is None
                else f", confidence {h.confidence:.2f}")
        add(f'<circle class="hazard" cx="{_fmt(x)}" cy="{_fmt(y)}" '
            f'r="{radius}" fill="{colour}" fill-opacity="0.75" '
            f'stroke="{colour}" stroke-width="2">'
            f'<title>{_escape(h.kind)} ({_escape(h.severity)}){conf}, '
            f'source {_escape(h.source)}</title></circle>')
        add(f'<text x="{_fmt(x + radius + 3)}" y="{_fmt(y + 4)}" '
            f'fill="{colour}" font-size="10">{_escape(h.kind)}</text>')

    def _grid_svg(self, tr: MapTransform, width: int, height: int) -> str:
        """Metric grid + axes.

        The grid step is chosen from the fitted scale so lines land on round
        metric values (1 m, 0.5 m, ...) at any zoom instead of drifting to
        arbitrary decimal places.
        """
        step = 1.0
        for candidate in (10.0, 5.0, 2.0, 1.0, 0.5, 0.2, 0.1, 0.05, 0.02):
            if candidate * tr.scale >= 28.0:
                step = candidate
                break
        parts: List[str] = []
        x_start = math.floor(tr.bounds["x_min"] / step) * step
        x = x_start
        while x <= tr.bounds["x_max"] + step * 0.5:
            px, _py = tr.to_screen(x, 0.0)
            if math.isfinite(px):
                axis = abs(x) < step * 1e-6
                parts.append(
                    f'<line x1="{_fmt(px)}" y1="0" x2="{_fmt(px)}" '
                    f'y2="{height}" stroke="{COL_AXIS if axis else COL_GRID}" '
                    f'stroke-width="{1.4 if axis else 1}"/>')
            x += step
        y_start = math.floor(tr.bounds["y_min"] / step) * step
        y = y_start
        while y <= tr.bounds["y_max"] + step * 0.5:
            _px, py = tr.to_screen(0.0, y)
            if math.isfinite(py):
                axis = abs(y) < step * 1e-6
                parts.append(
                    f'<line x1="0" y1="{_fmt(py)}" x2="{width}" y2="{_fmt(py)}" '
                    f'stroke="{COL_AXIS if axis else COL_GRID}" '
                    f'stroke-width="{1.4 if axis else 1}"/>')
            y += step
        parts.append(f'<text x="6" y="{height - 8}" fill="{COL_MUTED}" '
                     f'font-size="10">metres, y-up; viewport fits available '
                     f'data (not a surveyed boundary)</text>')
        return "".join(parts)
