"""C19 — spatial heat map: hazard density and traffic density.

The repository already records two things that are *spatial over time* and were
never visualised together:

* **where hazards happened** — :class:`amr.hazard.event_log.HazardEventLog` keeps
  a bounded, location-tagged history (``PROJECT_CONTEXT.md`` names "an auditable,
  location-tagged hazard event history feeding a future spatial hazard
  visualisation" as the project's novelty direction; this module is that view);
* **where the robot went** — :class:`~amr.map.snapshot.MapSnapshot.path`, the
  travelled trail the navigator already publishes.

This module is a **view**, in the same sense as ``amr/map/twin.py``: a pure
function over objects the runtime already owns. It reads no hardware, performs no
writes, calls no movement API, and holds no state. ``POST /command`` remains the
only path to the actuators.

Why binning happens in Python
-----------------------------
Every other view in this project resolves its geometry once, server-side, where
it is unit tested, so two clients cannot disagree about it (see the coordinate
rules in ``amr/map/twin.py``). The heat map follows that rule: the grids are
built here and shipped as data. A client colours cells; it never re-derives a
bin index, because an off-by-one in a bin index is invisible in a picture and
silent in a test.

The two grids
-------------
Both are binned over **one shared extent** so they can be compared directly:

``traffic``
    One sample per path point. The path is appended by the control loop, so a
    count is a *proxy for time spent* in a cell, **not** for distance travelled —
    the sampling rate is the clock, not the odometer.
``hazard``
    One weighted sample per recorded event **that carries a world location**.
    The weight is the severity weight below. An event whose evidence is
    image-space (a vision bounding box) or that has no location at all is
    **never placed** — it is counted in ``unlocated`` instead, preserving the C5
    rule that a pixel bounding box is not a warehouse coordinate.

Honesty rules encoded here
--------------------------
* **A stable extent.** The grid covers the *configured* geometry (waypoints and
  hazard zones) padded by a margin — not the current data extent. A heat map is
  read by comparing polls, and a frame that rescales itself every second cannot
  be compared with itself.
* **Nothing is silently dropped.** A sample outside the extent is counted in
  ``clipped`` and reported, so a reader can tell "no hazards here" from "hazards
  here were not drawn".
* **No invented floor plan.** Cells outside the configured geometry are simply
  empty; the module adds no shelves, racks or walls.
* **Severity weighting is a display choice.** It never feeds a safety decision —
  the hazard layer's verdict is computed from raw readings, not from this grid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .snapshot import (
    UNAVAILABLE,
    MapSnapshot,
    is_num,
)

#: Heat-map payload schema. Independent of the map schema it is derived from.
HEATMAP_SCHEMA_VERSION = "1.0"

#: Default square cell size in metres. Chosen so the demo warehouse (roughly
#: 4 x 3 m of configured geometry) lands on a ~20 x 16 grid: coarse enough to
#: read at a glance, fine enough that two shelves are not the same cell.
DEFAULT_CELL_M = 0.25

#: Default padding added around the configured geometry, in metres. Without it a
#: waypoint sitting exactly on the extent edge would occupy a half cell.
DEFAULT_MARGIN_M = 0.5

#: Severity -> display weight. A CRITICAL event is not "50% worse" than a
#: WARNING; it is the class an operator must act on, so it dominates a cell
#: rather than shading it slightly. These numbers are a *rendering* convention
#: and are documented in the payload so a client never has to guess them.
SEVERITY_WEIGHTS: Dict[str, float] = {
    "INFO": 1.0,
    "WARNING": 2.0,
    "CRITICAL": 4.0,
}

#: Weight used for a severity the table does not know. Deliberately the WARNING
#: weight: an unrecognised severity must not vanish from the picture (the same
#: reasoning as ``HazardSeverity.parse``).
UNKNOWN_SEVERITY_WEIGHT = 2.0

#: Shown beside the hazard graph so a sparse picture is never misread as "safe".
HAZARD_NOTE = (
    "counts recorded hazard events that carry a world location, weighted by "
    "severity; events with only image-space evidence are listed separately and "
    "are never placed on this grid"
)

#: Shown beside the traffic graph.
TRAFFIC_NOTE = (
    "one sample per recorded path point, so a cell's value is time spent there "
    "rather than distance travelled; the sampling rate is the control-loop clock"
)


def severity_weight(severity: Any) -> float:
    """Display weight for a severity value (enum, name or string)."""
    if severity is None:
        return UNKNOWN_SEVERITY_WEIGHT
    value = getattr(severity, "value", severity)
    key = str(value).strip().upper()
    return SEVERITY_WEIGHTS.get(key, UNKNOWN_SEVERITY_WEIGHT)


@dataclass(frozen=True)
class HeatGrid:
    """A square-celled density grid in world metres.

    ``cells`` is a **flat, row-major** tuple: ``index = row * cols + col``, with
    ``col 0`` at :attr:`x_min` and **``row 0`` at :attr:`y_min`** (the lowest y).
    The repository's world frame is y-up, so row 0 is the *bottom* row — stated
    here because a client that assumed row 0 was the top would draw every map
    vertically mirrored, which looks plausible and is wrong.
    """

    cols: int
    rows: int
    cell_m: float
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    cells: Tuple[float, ...] = ()
    max_value: float = 0.0
    total: float = 0.0
    samples: int = 0
    clipped: int = 0
    unlocated: int = 0
    source: str = UNAVAILABLE
    note: str = ""

    @property
    def cell_count(self) -> int:
        return self.cols * self.rows

    def at(self, col: int, row: int) -> float:
        """Value at ``(col, row)``; out-of-range reads return ``0.0``."""
        if not (0 <= col < self.cols and 0 <= row < self.rows):
            return 0.0
        return self.cells[row * self.cols + col]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cols": self.cols,
            "rows": self.rows,
            "cell_m": self.cell_m,
            "extent": {
                "x_min": self.x_min,
                "x_max": self.x_max,
                "y_min": self.y_min,
                "y_max": self.y_max,
            },
            # Row-major, row 0 = y_min. Published as a flat list so neither
            # client has to agree on a nesting convention.
            "cells": list(self.cells),
            "row_order": "row 0 is y_min (bottom); index = row * cols + col",
            "max_value": self.max_value,
            "total": self.total,
            "samples": self.samples,
            "clipped": self.clipped,
            "unlocated": self.unlocated,
            "source": self.source,
            "note": self.note,
        }


@dataclass(frozen=True)
class HeatmapState:
    """Both heat maps for one instant, over one shared extent."""

    hazard: Optional[HeatGrid] = None
    traffic: Optional[HeatGrid] = None
    source: str = UNAVAILABLE
    notes: Tuple[str, ...] = ()
    schema_version: str = HEATMAP_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "units": "metres",
            "frame": "warehouse",
            "y_axis": "up",
            "severity_weights": dict(SEVERITY_WEIGHTS),
            "hazard": self.hazard.to_dict() if self.hazard else None,
            "traffic": self.traffic.to_dict() if self.traffic else None,
            "notes": list(self.notes),
        }


def grid_geometry(
        bounds: Optional[Dict[str, float]],
        cell_m: float = DEFAULT_CELL_M) -> Optional[Tuple[int, int, float, float, float]]:
    """``(cols, rows, cell_m, x_min, y_min)`` for an extent, or ``None``.

    The grid is snapped *outwards* to whole cells, so the published extent
    always fully contains the configured geometry and every cell is a full
    ``cell_m`` square (a heat map with stretched cells misleads the eye about
    distance).
    """
    if not bounds:
        return None
    try:
        x_min = float(bounds["x_min"])
        x_max = float(bounds["x_max"])
        y_min = float(bounds["y_min"])
        y_max = float(bounds["y_max"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(is_num(v) for v in (x_min, x_max, y_min, y_max)):
        return None
    if x_max <= x_min or y_max <= y_min:
        return None
    size = float(cell_m)
    if not (is_num(size) and size > 0):
        size = DEFAULT_CELL_M
    cols = max(1, math.ceil((x_max - x_min) / size))
    rows = max(1, math.ceil((y_max - y_min) / size))
    return cols, rows, size, x_min, y_min


def _bin_samples(
        samples: Sequence[Tuple[float, float, float]],
        geometry: Tuple[int, int, float, float, float],
) -> Tuple[List[float], int, int, float]:
    """Bin ``(x, y, weight)`` samples; returns ``(cells, placed, clipped, max)``.

    A sample outside the grid is *counted*, never silently discarded.
    """
    cols, rows, cell_m, x_min, y_min = geometry
    cells = [0.0] * (cols * rows)
    placed = 0
    clipped = 0
    peak = 0.0
    for x, y, weight in samples:
        if not (is_num(x) and is_num(y)):
            continue
        col = math.floor((float(x) - x_min) / cell_m)
        row = math.floor((float(y) - y_min) / cell_m)
        if not (0 <= col < cols and 0 <= row < rows):
            clipped += 1
            continue
        index = row * cols + col
        cells[index] += float(weight)
        placed += 1
        peak = max(peak, cells[index])
    return cells, placed, clipped, peak


def _traffic_samples(snapshot: MapSnapshot) -> List[Tuple[float, float, float]]:
    """One unit sample per travelled path point."""
    return [(p.x, p.y, 1.0) for p in (snapshot.path or ())]


def _hazard_samples(
        events: Sequence[Any],
) -> Tuple[List[Tuple[float, float, float]], int]:
    """Severity-weighted samples for located events; also the unlocated count.

    ``events`` may be :class:`~amr.hazard.types.HazardEvent` objects or the
    plain dicts ``HazardEvent.to_dict()`` produces (the shape
    ``HazardEventLog.read_events`` returns), so a recorded JSONL file and a live
    manager are both accepted.
    """
    samples: List[Tuple[float, float, float]] = []
    unlocated = 0
    for ev in events or ():
        if isinstance(ev, dict):
            loc = ev.get("location")
            severity = ev.get("severity")
        else:
            loc = getattr(ev, "location", None)
            severity = getattr(ev, "severity", None)
            if loc is not None and not isinstance(loc, dict):
                loc = loc.to_dict()
        x = loc.get("x") if isinstance(loc, dict) else None
        y = loc.get("y") if isinstance(loc, dict) else None
        if not (is_num(x) and is_num(y)):
            # Image-space evidence or no location at all: the C5 rule says it is
            # never given warehouse coordinates.
            unlocated += 1
            continue
        samples.append((float(x), float(y), severity_weight(severity)))
    return samples, unlocated


def build_heatmap_state(
        snapshot: MapSnapshot,
        events: Sequence[Any] = (),
        *,
        cell_m: float = DEFAULT_CELL_M,
        margin_m: float = DEFAULT_MARGIN_M,
) -> HeatmapState:
    """Assemble both heat maps from an existing map snapshot and event history.

    ``snapshot`` is the same :class:`~amr.map.snapshot.MapSnapshot` the 2D map
    and the 3D twin render, so the three views cannot disagree about where the
    robot is. ``events`` is the hazard history (objects or dicts).

    Provenance is inherited from ``snapshot.source`` rather than passed in, so a
    simulated run cannot be labelled ``LIVE`` by a caller that forgot a flag.

    With no configured geometry the extent is unknowable, so both grids are
    ``None`` and the caller reports ``UNAVAILABLE`` rather than drawing an
    invented room — the same rule :func:`amr.map.snapshot.bounds_for` follows.
    """
    static = snapshot.static
    waypoints = static.waypoints if static is not None else ()
    zones = snapshot.zones or ()
    config_bounds = None
    if waypoints or zones:
        from .snapshot import bounds_for

        # Deliberately *without* the robot, goal or hazards: those move, and a
        # frame that rescales every second cannot be compared with itself.
        config_bounds = bounds_for(
            waypoints, zones, None, (), None,
            margin_m=margin_m,
        )

    geometry = grid_geometry(config_bounds, cell_m)
    if geometry is None:
        reason = ("no configured warehouse geometry, so no extent to bin over; "
                  "the project does not invent a floor plan")
        return HeatmapState(source=UNAVAILABLE, notes=(reason,))

    source = snapshot.source or UNAVAILABLE

    traffic_cells, traffic_placed, traffic_clipped, traffic_peak = _bin_samples(
        _traffic_samples(snapshot), geometry)
    hazard_samples, hazard_unlocated = _hazard_samples(events)
    hazard_cells, hazard_placed, hazard_clipped, hazard_peak = _bin_samples(
        hazard_samples, geometry)

    cols, rows, size, x_min, y_min = geometry
    x_max = x_min + cols * size
    y_max = y_min + rows * size

    traffic = HeatGrid(
        cols=cols, rows=rows, cell_m=size,
        x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max,
        cells=tuple(traffic_cells),
        max_value=traffic_peak,
        total=float(sum(traffic_cells)),
        samples=traffic_placed,
        clipped=traffic_clipped,
        source=source,
        note=TRAFFIC_NOTE,
    )
    hazard = HeatGrid(
        cols=cols, rows=rows, cell_m=size,
        x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max,
        cells=tuple(hazard_cells),
        max_value=hazard_peak,
        total=float(sum(hazard_cells)),
        samples=hazard_placed,
        clipped=hazard_clipped,
        unlocated=hazard_unlocated,
        source=source,
        note=HAZARD_NOTE,
    )

    notes: List[str] = []
    if hazard_unlocated:
        notes.append(
            f"{hazard_unlocated} recorded hazard event(s) carried no world "
            f"location and are not placed on the grid"
        )
    if hazard_clipped or traffic_clipped:
        notes.append(
            "samples outside the configured extent are counted in `clipped`, "
            "not dropped"
        )
    if not traffic.samples:
        notes.append("no travelled path recorded yet, so the traffic grid is empty")

    return HeatmapState(
        hazard=hazard,
        traffic=traffic,
        source=source,
        notes=tuple(notes),
    )
