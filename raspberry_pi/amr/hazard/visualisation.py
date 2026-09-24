"""Spatial hazard visualisation — render recorded events onto the warehouse map.

C3: a **pure read-side** renderer. Given the warehouse map
(``config/warehouse.yaml`` → ``AppConfig.warehouse.locations``), the recorded
hazard events (``read_events(path)``, ``HazardEvent`` objects or a
``HazardManager.snapshot()``) and the configured zones, it produces one
self-contained SVG document styled like ``assets/warehouse-map.svg``.

Guarantees (mirroring the hazard layer's hard rules, docs/hazard.md):

* **Read-only** — imports nothing from ``amr.robot`` / ``amr.navigation`` /
  ``amr.warehouse``, never touches the control loop, issues no commands. Safe
  to run on a laptop that has nothing but the JSONL export.
* **Deterministic** — no clock, no randomness: identical inputs produce
  byte-identical SVG.
* **Tolerant** — malformed location/zone entries are skipped, and events
  without a usable location are listed in the side panel instead of being
  dropped, the same way ``read_events`` skips malformed JSONL lines.
* **Stdlib only** — nothing outside this package and ``amr.utils.config``.

CLI::

    cd raspberry_pi
    python -m amr.hazard.visualisation --events events.jsonl --out map.svg
    python -m amr.hazard.visualisation --out -        # SVG to stdout
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from ..utils.config import ConfigError, load_config
from .event_log import read_events
from .sources import zones_from_config
from .types import HazardState

#: Marker / legend colour per hazard state (worst is reddest).
STATE_COLORS: Mapping[str, str] = {
    HazardState.NORMAL.value: "#2ecc71",
    HazardState.WARNING.value: "#f1c40f",
    HazardState.SLOW.value: "#e67e22",
    HazardState.STOP.value: "#e74c3c",
    HazardState.EMERGENCY.value: "#ff3b30",
}

# Palette and typography follow assets/warehouse-map.svg.
_BG = "#0f1420"
_GRID = "#22304a"
_TEXT = "#e6ecf7"
_MUTED = "#8b98b8"
_WAYPOINT_FILL = "#1f2b45"
_WAYPOINT_STROKE = "#4da3ff"
_DOCK_STROKE = "#2ecc71"
_ZONE_STROKE = "#e74c3c"
_FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"

#: World bounds used when there is nothing to derive them from.
_DEFAULT_BOUNDS = (0.0, 5.0, 0.0, 3.0)

#: Deterministic fan-out radius (px) when several events share a location.
_CLUSTER_RADIUS_PX = 11.0

#: Side panel geometry.
_PANEL_W = 224
_PANEL_GAP = 16
_MAX_PANEL_LINES = 10


def _esc(value: Any) -> str:
    """XML-escape text **and** attribute values (quotes included)."""
    return escape(str(value), {'"': "&quot;"})


def _px(value: float) -> str:
    """Format a pixel coordinate stably (one decimal keeps output byte-stable)."""
    return f"{value:.1f}"


def _sort_key(event: Mapping[str, Any]) -> Tuple[float, str]:
    try:
        timestamp = float(event.get("raised_at") or 0.0)
    except (TypeError, ValueError):
        timestamp = 0.0
    return (timestamp, str(event.get("event_id") or ""))


def _coerce_event(raw: Any) -> Dict[str, Any]:
    """Accept a plain dict (JSONL / snapshot) or any object with ``to_dict()``."""
    if isinstance(raw, Mapping):
        return dict(raw)
    to_dict = getattr(raw, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    raise TypeError(
        f"event must be a mapping or expose to_dict(), got {type(raw).__name__}"
    )


def _event_xy(event: Mapping[str, Any]) -> Optional[Tuple[float, float]]:
    """World (x, y) of an event, or ``None`` when it carries no usable location."""
    location = event.get("location")
    if not isinstance(location, Mapping):
        return None
    try:
        return float(location["x"]), float(location["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _event_zone(event: Mapping[str, Any]) -> str:
    location = event.get("location")
    if isinstance(location, Mapping):
        return str(location.get("zone") or "")
    return ""


def _locations_items(locations: Any) -> List[Tuple[str, float, float]]:
    """``(name, x, y)`` from ``{name: {x,y,theta}}`` or ``{name: [x, y, ...]}``.

    Entries that cannot be parsed are skipped (tolerant, like
    :func:`zones_from_config`) so one typo cannot break the whole render.
    """
    if not isinstance(locations, Mapping):
        return []
    items: List[Tuple[str, float, float]] = []
    for name, value in locations.items():
        try:
            if isinstance(value, Mapping):
                x, y = float(value["x"]), float(value["y"])
            else:
                if isinstance(value, (str, bytes)):
                    raise TypeError("waypoint must be a mapping or sequence")
                seq = list(value)
                x, y = float(seq[0]), float(seq[1])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        items.append((str(name), x, y))
    return items


def _zones_items(zones: Optional[Iterable[Any]]) -> List[Dict[str, Any]]:
    """Normalise ``HazardZone`` objects / dicts; skip malformed entries."""
    out: List[Dict[str, Any]] = []
    for zone in zones or ():
        try:
            blob = zone.to_dict() if hasattr(zone, "to_dict") else dict(zone)
            out.append(
                {
                    "name": str(blob["name"]),
                    "x_min": float(blob["x_min"]),
                    "x_max": float(blob["x_max"]),
                    "y_min": float(blob["y_min"]),
                    "y_max": float(blob["y_max"]),
                    "severity": str(blob.get("severity") or "CRITICAL"),
                }
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return out


def _bounds(
    locations: Sequence[Tuple[str, float, float]],
    zone_blobs: Sequence[Mapping[str, Any]],
    points: Sequence[Tuple[float, float]],
) -> Tuple[float, float, float, float]:
    """World bounds ``(xmin, xmax, ymin, ymax)`` covering everything to draw."""
    xs: List[float] = []
    ys: List[float] = []
    for _, x, y in locations:
        xs.append(x)
        ys.append(y)
    for blob in zone_blobs:
        xs.extend((blob["x_min"], blob["x_max"]))
        ys.extend((blob["y_min"], blob["y_max"]))
    for x, y in points:
        xs.append(x)
        ys.append(y)
    if not xs:
        return _DEFAULT_BOUNDS
    xmin, xmax = min(xs) - 0.5, max(xs) + 0.5
    ymin, ymax = min(ys) - 0.5, max(ys) + 0.5
    # A single point (or a degenerate line) must still render as an area.
    if xmax - xmin < 1.0:
        centre = 0.5 * (xmin + xmax)
        xmin, xmax = centre - 0.5, centre + 0.5
    if ymax - ymin < 1.0:
        centre = 0.5 * (ymin + ymax)
        ymin, ymax = centre - 0.5, centre + 0.5
    return xmin, xmax, ymin, ymax


def _grid_step(xmin: float, xmax: float, ymin: float, ymax: float) -> float:
    """A 'nice' grid pitch targeting roughly six lines across the larger span."""
    raw = max(xmax - xmin, ymax - ymin) / 6.0
    for step in (0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0):
        if raw <= step + 1e-9:
            return step
    return 50.0


def _ticks(lo: float, hi: float, step: float) -> List[float]:
    """Multiples of ``step`` inside ``[lo, hi]`` (float-safe, deterministic)."""
    start = math.ceil(lo / step - 1e-9) * step
    out: List[float] = []
    value = start
    while value <= hi + 1e-9:
        out.append(round(value, 6))
        value += step
    return out


def _projector(
    bounds: Tuple[float, float, float, float],
    left: float,
    top: float,
    plot_w: float,
    plot_h: float,
):
    """World metres → pixels, aspect-preserving, +y up (SVG is y-down)."""
    xmin, xmax, ymin, ymax = bounds
    scale = min(plot_w / (xmax - xmin), plot_h / (ymax - ymin))
    content_w = (xmax - xmin) * scale
    content_h = (ymax - ymin) * scale
    origin_x = left + 0.5 * (plot_w - content_w)
    origin_y = top + 0.5 * (plot_h - content_h)

    def project(x: float, y: float) -> Tuple[float, float]:
        return (
            origin_x + (x - xmin) * scale,
            origin_y + content_h - (y - ymin) * scale,
        )

    return project


def events_from_snapshot(snapshot: Any) -> List[Dict[str, Any]]:
    """Flatten ``HazardManager.snapshot()`` into one de-duplicated event list.

    ``active_events`` and ``recent_events`` overlap; events are keyed by
    ``event_id`` (active copies win) and returned sorted oldest-first, so the
    renderer sees a deterministic sequence.
    """
    if not isinstance(snapshot, Mapping):
        return []
    merged: Dict[str, Dict[str, Any]] = {}
    for key in ("recent_events", "active_events"):  # active read second → wins
        for raw in snapshot.get(key) or ():
            try:
                event = _coerce_event(raw)
            except TypeError:
                continue
            event_id = str(event.get("event_id") or "")
            if event_id:
                merged[event_id] = event
    return sorted(merged.values(), key=_sort_key)


def render_map_svg(
    locations: Any,
    events: Iterable[Any] = (),
    *,
    zones: Optional[Iterable[Any]] = (),
    title: str = "Hazard Event Map",
    width: int = 780,
    height: int = 580,
) -> str:
    """Render the warehouse map with hazard events as a standalone SVG string.

    :param locations: ``config.warehouse.locations``-style mapping
        (``{name: {x, y, theta}}`` or ``{name: [x, y, theta]}``).
    :param events: dicts from :func:`read_events` / ``snapshot()`` or
        :class:`~amr.hazard.types.HazardEvent` objects.
    :param zones: :class:`~amr.hazard.sources.HazardZone` objects or dicts.
    :returns: a complete SVG document (deterministic for identical inputs).
    """
    waypts = _locations_items(locations)
    zone_blobs = _zones_items(zones)

    coerced: List[Dict[str, Any]] = []
    for raw in events:
        try:
            coerced.append(_coerce_event(raw))
        except TypeError:
            continue
    coerced.sort(key=_sort_key)

    located: List[Tuple[Dict[str, Any], float, float]] = []
    unlocated: List[Dict[str, Any]] = []
    for event in coerced:
        xy = _event_xy(event)
        if xy is None:
            unlocated.append(event)
        else:
            located.append((event, xy[0], xy[1]))

    bounds = _bounds(waypts, zone_blobs, [(x, y) for _, x, y in located])
    xmin, xmax, ymin, ymax = bounds

    # Canvas layout: title band on top, legend/event panel on the right.
    margin = 24.0
    plot_left = margin + 32.0
    plot_top = margin + 56.0
    plot_w = width - plot_left - _PANEL_W - _PANEL_GAP - margin
    plot_h = height - plot_top - margin - 36.0
    project = _projector(bounds, plot_left, plot_top, plot_w, plot_h)

    step = _grid_step(*bounds)
    active = sum(1 for e in coerced if not e.get("resolved"))

    out: List[str] = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
        f' viewBox="0 0 {width} {height}" font-family="{_FONT}">'
    )
    out.append(f'<rect width="{width}" height="{height}" fill="{_BG}"/>')
    out.append(
        f'<text x="{margin}" y="{margin + 24}" fill="{_TEXT}" font-size="22"'
        f' font-weight="700">{_esc(title)}</text>'
    )
    out.append(
        f'<text x="{margin}" y="{margin + 44}" fill="{_MUTED}" font-size="13">'
        f'{len(coerced)} events ({active} active) · '
        f'{len(unlocated)} without location · world frame, metres</text>'
    )

    # -- grid + axis ticks --------------------------------------------------
    out.append(f'<g stroke="{_GRID}" stroke-width="1">')
    for gx in _ticks(xmin, xmax, step):
        px, _ = project(gx, ymin)
        out.append(
            f'<line x1="{_px(px)}" y1="{_px(plot_top)}"'
            f' x2="{_px(px)}" y2="{_px(plot_top + plot_h)}"/>'
        )
    for gy in _ticks(ymin, ymax, step):
        _, py = project(xmin, gy)
        out.append(
            f'<line x1="{_px(plot_left)}" y1="{_px(py)}"'
            f' x2="{_px(plot_left + plot_w)}" y2="{_px(py)}"/>'
        )
    out.append("</g>")
    out.append(f'<g fill="{_MUTED}" font-size="11">')
    for gx in _ticks(xmin, xmax, step):
        px, _ = project(gx, ymin)
        out.append(
            f'<text x="{_px(px)}" y="{_px(plot_top + plot_h + 16)}"'
            f' text-anchor="middle">{gx:g}</text>'
        )
    for gy in _ticks(ymin, ymax, step):
        _, py = project(xmin, gy)
        out.append(
            f'<text x="{_px(plot_left - 6)}" y="{_px(py + 4)}"'
            f' text-anchor="end">{gy:g}</text>'
        )
    out.append(
        f'<text x="{_px(plot_left + plot_w / 2)}"'
        f' y="{_px(plot_top + plot_h + 32)}" text-anchor="middle">x (m)</text>'
    )
    out.append("</g>")

    # -- restricted zones ---------------------------------------------------
    for blob in zone_blobs:
        zx, zy = project(blob["x_min"], blob["y_max"])
        rx, ry = project(blob["x_max"], blob["y_min"])
        out.append(
            f'<rect x="{_px(zx)}" y="{_px(zy)}" width="{_px(rx - zx)}"'
            f' height="{_px(ry - zy)}" fill="{_ZONE_STROKE}" fill-opacity="0.10"'
            f' stroke="{_ZONE_STROKE}" stroke-width="1.5"'
            f' stroke-dasharray="6 4"/>'
        )
        out.append(
            f'<text x="{_px(zx + 5)}" y="{_px(zy + 14)}"'
            f' fill="{_ZONE_STROKE}" font-size="11" font-weight="600">'
            f'{_esc(blob["name"])}</text>'
        )

    # -- waypoints ----------------------------------------------------------
    for name, wx, wy in waypts:
        px, py = project(wx, wy)
        stroke = _DOCK_STROKE if name == "dock" else _WAYPOINT_STROKE
        out.append(
            f'<circle cx="{_px(px)}" cy="{_px(py)}" r="7"'
            f' fill="{_WAYPOINT_FILL}" stroke="{stroke}" stroke-width="2"/>'
        )
        out.append(
            f'<text x="{_px(px + 11)}" y="{_px(py + 4)}" fill="{_TEXT}"'
            f' font-size="12" font-weight="600">{_esc(name)}</text>'
        )

    _append_markers(out, located, project)
    _append_panel(out, unlocated, width, plot_top)

    out.append("</svg>")
    return "\n".join(out)


def _append_markers(
    out: List[str],
    located: Sequence[Tuple[Dict[str, Any], float, float]],
    project: Any,
) -> None:
    """Draw hazard markers; co-located events fan out deterministically."""
    clusters: Dict[Tuple[float, float], int] = {}
    for event, ex, ey in located:
        key = (round(ex, 2), round(ey, 2))
        index = clusters.get(key, 0)
        clusters[key] = index + 1
        # First event sits on the point; later ones ring around it.
        if index:
            angle = 2.0 * math.pi * (index - 1) / 6.0
            ox = _CLUSTER_RADIUS_PX * math.cos(angle)
            oy = _CLUSTER_RADIUS_PX * math.sin(angle)
        else:
            ox = oy = 0.0
        px, py = project(ex, ey)
        state = HazardState.parse(event.get("state"))
        colour = STATE_COLORS[state.value]
        resolved = bool(event.get("resolved"))
        opacity = "0.45" if resolved else "1"
        ring = state.value == "EMERGENCY" and not resolved
        stroke_colour = "#ffffff" if ring else colour
        stroke_width = "4" if ring else "1.5"
        resolved_flag = "true" if resolved else "false"
        where = _event_zone(event)
        zone = f" @ {where}" if where else ""
        out.append(
            f'<circle class="hazard-event" data-state="{state.value}"'
            f' data-resolved="{resolved_flag}"'
            f' cx="{_px(px + ox)}" cy="{_px(py + oy)}" r="6"'
            f' fill="{colour}" fill-opacity="{opacity}"'
            f' stroke="{stroke_colour}" stroke-width="{stroke_width}">'
            f'<title>{_esc(event.get("kind", "UNKNOWN"))}{zone}'
            f' {state.value}: {_esc(event.get("message", ""))}</title>'
            f"</circle>"
        )


def _append_panel(
    out: List[str],
    unlocated: Sequence[Mapping[str, Any]],
    width: int,
    top: float,
) -> None:
    """Right-hand panel: legend plus events that carry no usable location."""
    x = width - _PANEL_W - 8.0
    y = top
    out.append(
        f'<text x="{_px(x)}" y="{_px(y)}" fill="{_TEXT}" font-size="13"'
        f' font-weight="700">Legend</text>'
    )
    y += 8.0
    for state in HazardState:
        y += 20.0
        colour = STATE_COLORS[state.value]
        out.append(
            f'<circle cx="{_px(x + 7)}" cy="{_px(y - 4)}" r="6"'
            f' fill="{colour}" stroke="{colour}" stroke-width="1.5"/>'
        )
        out.append(
            f'<text x="{_px(x + 20)}" y="{_px(y)}" fill="{_MUTED}"'
            f' font-size="12">{state.value}</text>'
        )
    y += 26.0
    out.append(
        f'<text x="{_px(x)}" y="{_px(y)}" fill="{_TEXT}" font-size="13"'
        f' font-weight="700">Without location'
        f' ({len(unlocated)})</text>'
    )
    if not unlocated:
        y += 20.0
        out.append(
            f'<text x="{_px(x)}" y="{_px(y)}" fill="{_MUTED}"'
            f' font-size="12">none</text>'
        )
    for event in unlocated[:_MAX_PANEL_LINES]:
        y += 18.0
        kind = str(event.get("kind", "UNKNOWN"))
        state = HazardState.parse(event.get("state"))
        label = f"{kind} [{state.value}]"
        out.append(
            f'<text x="{_px(x)}" y="{_px(y)}" fill="{STATE_COLORS[state.value]}"'
            f' font-size="11">{_esc(label)}</text>'
        )
    remaining = len(unlocated) - _MAX_PANEL_LINES
    if remaining > 0:
        y += 18.0
        out.append(
            f'<text x="{_px(x)}" y="{_px(y)}" fill="{_MUTED}"'
            f' font-size="11">… and {remaining} more</text>'
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI: render a JSONL event export onto the configured warehouse map.

    Reads ``config/warehouse.yaml`` (waypoints) and ``config/hazard.yaml``
    (zones); ``--events`` defaults to ``hazard.event_log_path`` when set.
    Writes SVG to ``--out`` (default ``hazard-map.svg``) and exits 0 on
    success. Never touches the robot — read-only, offline.
    """
    parser = argparse.ArgumentParser(
        prog="python -m amr.hazard.visualisation",
        description="Render recorded hazard events onto the warehouse map (SVG).",
    )
    parser.add_argument(
        "--events",
        default=None,
        help="JSONL hazard event export (default: hazard.event_log_path)",
    )
    parser.add_argument(
        "--out",
        default="hazard-map.svg",
        help="output SVG path, or '-' for stdout (default: hazard-map.svg)",
    )
    parser.add_argument(
        "--title",
        default="Hazard Event Map",
        help="document title (default: 'Hazard Event Map')",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        help="config directory (default: <repo>/config or $AMR_CONFIG_DIR)",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config_dir)
    except ConfigError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1

    events_path = args.events or config.hazard.event_log_path
    events = read_events(str(events_path)) if events_path else ()
    if events_path and len(events) == 0:
        # Honest: a typo'd path must not look like "no hazards happened".
        print(f"note: no events read from {events_path}", file=sys.stderr)
    svg = render_map_svg(
        config.warehouse.locations,
        events,
        zones=zones_from_config(config.hazard),
        title=args.title,
    )

    if args.out == "-":
        print(svg)
        return 0
    try:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(svg)
    except OSError as exc:
        print(f"FATAL: cannot write {args.out}: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {args.out} ({len(svg)} bytes, {len(events)} events)")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    sys.exit(main())