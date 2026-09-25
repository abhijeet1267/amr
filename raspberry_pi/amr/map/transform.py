"""C9 — world-to-screen transform and bounded path history.

This module owns the **only** coordinate conversion in the map stack. The world
model (:mod:`amr.map.snapshot`) stays in the warehouse frame (metres, y-up) and
this layer converts to screen pixels. Keeping the conversion in one tested place
is what stops the SVG renderer and the future C10 3D twin from disagreeing, and
stops coordinate maths from leaking into the frontend.

Transform
---------
    screen_x = world_x * scale + offset_x
    screen_y = offset_y - world_y * scale

``scale`` is one value for both axes, so the aspect ratio is preserved: a square
metre stays square and a circle stays a circle. The ``y`` term is flipped because
the warehouse frame is **y-up** while SVG coordinates grow **downward**. That
single negation is the only difference between the frames, and it lives here
rather than in the drawing code.

Given identical inputs the transform is deterministic — it holds no state that
changes between calls, so the same snapshot always renders identically.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional, Sequence, Tuple

from .snapshot import MapPoint, is_num

#: Default travelled-path history length. Bounded on purpose: a dashboard polled
#: every second on a Raspberry Pi must not accumulate pose history forever.
#: 600 samples is 10 minutes at the 1 Hz dashboard poll.
DEFAULT_PATH_LIMIT = 600


@dataclass(frozen=True)
class MapTransform:
    """World metres -> screen pixels for one fixed viewport.

    :param bounds: world extent to fit, as produced by
        :func:`amr.map.snapshot.bounds_for`.
    :param width: viewport width in pixels.
    :param height: viewport height in pixels.
    :param padding: pixels reserved around the fitted content.
    :param zoom: multiplier applied to the fitted scale (1.0 = fit exactly).
    :param pan_x: horizontal offset in *world metres* (zoom/pan control).
    :param pan_y: vertical offset in world metres.

    A degenerate extent (zero or negative width/height, or a non-positive
    viewport) falls back to a square 1 m viewport centred on the origin rather
    than raising or dividing by zero, so a map holding a single point still
    draws.
    """

    bounds: Dict[str, float]
    width: int
    height: int
    padding: float = 24.0
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0

    def __post_init__(self) -> None:
        b = self.bounds if isinstance(self.bounds, dict) else {}

        def _num(key: str, default: float) -> float:
            value = b.get(key, default)
            return float(value) if is_num(value) else default

        # Normalise defensively: a caller may pass partial or inverted bounds,
        # and a renderer must not crash on them.
        x_min, x_max = _num("x_min", 0.0), _num("x_max", 1.0)
        y_min, y_max = _num("y_min", 0.0), _num("y_max", 1.0)
        if x_max <= x_min:
            x_min, x_max = x_min - 0.5, x_max + 0.5
        if y_max <= y_min:
            y_min, y_max = y_min - 0.5, y_max + 0.5
        object.__setattr__(self, "bounds", {
            "x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max,
        })
        object.__setattr__(self, "width", max(1, int(self.width)))
        object.__setattr__(self, "height", max(1, int(self.height)))
        object.__setattr__(self, "padding", max(0.0, float(self.padding)))
        zoom = float(self.zoom) if is_num(self.zoom) else 1.0
        object.__setattr__(self, "zoom", min(20.0, max(0.05, zoom)))

    # -- geometry ----------------------------------------------------------- #
    @property
    def world_width(self) -> float:
        return self.bounds["x_max"] - self.bounds["x_min"]

    @property
    def world_height(self) -> float:
        return self.bounds["y_max"] - self.bounds["y_min"]

    @property
    def scale(self) -> float:
        """Uniform pixels-per-metre: the smaller of the two fitting ratios."""
        usable_w = max(1.0, self.width - 2.0 * self.padding)
        usable_h = max(1.0, self.height - 2.0 * self.padding)
        return min(usable_w / self.world_width,
                   usable_h / self.world_height) * self.zoom

    @property
    def offset(self) -> Tuple[float, float]:
        """Pixel offset placing the world origin, after the y-flip."""
        s = self.scale
        return (self.padding - self.bounds["x_min"] * s + self.pan_x * s,
                self.padding + self.bounds["y_max"] * s - self.pan_y * s)

    def to_screen(self, x: float, y: float) -> Tuple[float, float]:
        """Convert world metres to pixels. Invalid input yields ``(nan, nan)``.

        Returning NaN rather than clamping keeps "not plottable" obvious: a
        caller that ignores it simply omits the shape instead of drawing a
        plausible-looking point at the origin.
        """
        if not (is_num(x) and is_num(y)):
            return (float("nan"), float("nan"))
        ox, oy = self.offset
        s = self.scale
        return (float(x) * s + ox, oy - float(y) * s)

    def to_world(self, px: float, py: float) -> Tuple[float, float]:
        """Inverse of :meth:`to_screen` (used by click-to-inspect)."""
        if not (is_num(px) and is_num(py)):
            return (float("nan"), float("nan"))
        ox, oy = self.offset
        s = self.scale or 1.0
        return ((float(px) - ox) / s, (oy - float(py)) / s)

    def yaw_to_degrees(self, yaw: float) -> float:
        """World yaw (rad) to SVG rotation (deg), negated for the y-flip.

        In the warehouse frame ``+x`` is right and ``+y`` is up, so a positive
        yaw turns counter-clockwise. Screen y grows downward, hence the minus.
        """
        if not is_num(yaw):
            return 0.0
        return -math.degrees(float(yaw))

    def rect(self, x_min: float, y_min: float,
             x_max: float, y_max: float) -> Optional[Dict[str, float]]:
        """Screen-space rectangle for a world axis-aligned rectangle."""
        x0, y0 = self.to_screen(x_min, y_min)
        x1, y1 = self.to_screen(x_max, y_max)
        if any(not math.isfinite(v) for v in (x0, y0, x1, y1)):
            return None
        return {"x": min(x0, x1), "y": min(y0, y1),
                "width": abs(x1 - x0), "height": abs(y1 - y0)}

    def polyline(self, points: Sequence[MapPoint]) -> str:
        """SVG ``points`` attribute for a world-space polyline.

        Non-finite points are dropped rather than emitting ``NaN`` into the
        markup, which would make the whole document unparseable.
        """
        out = []
        for p in points or ():
            x, y = self.to_screen(p.x, p.y)
            if math.isfinite(x) and math.isfinite(y):
                out.append(f"{x:.2f},{y:.2f}")
        return " ".join(out)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scale_px_per_m": round(self.scale, 4),
            "bounds": dict(self.bounds),
            "width": self.width,
            "height": self.height,
            "zoom": self.zoom,
            "y_flipped": True,
        }


class PathHistory:
    """Bounded, de-duplicated trail of visited poses.

    The dashboard samples the pose on every poll, so consecutive samples are
    usually identical. Storing each one wastes memory and turns a long straight
    run into thousands of identical points, so a pose is appended only when it
    actually moved by more than ``min_step_m`` (or the yaw changed). The buffer
    is a fixed-size deque: at the limit the **oldest** point is dropped, giving a
    rolling window instead of unbounded growth.
    """

    def __init__(self, limit: int = DEFAULT_PATH_LIMIT,
                 min_step_m: float = 0.01) -> None:
        self._points: Deque[MapPoint] = deque(maxlen=max(2, int(limit)))
        self._min_step = max(0.0, float(min_step_m))
        self._last_yaw: Optional[float] = None

    @property
    def limit(self) -> int:
        return self._points.maxlen or 0

    def __len__(self) -> int:
        return len(self._points)

    def add(self, x: float, y: float, yaw: Optional[float] = None) -> bool:
        """Append a pose if it moved enough. Returns ``True`` when stored."""
        if not (is_num(x) and is_num(y)):
            return False
        turned = (yaw is not None and is_num(yaw)
                  and (self._last_yaw is None
                       or abs(float(yaw) - self._last_yaw) > 1e-3))
        if self._points:
            last = self._points[-1]
            moved = math.hypot(float(x) - last.x, float(y) - last.y)
            if moved < self._min_step and not turned:
                return False
        self._points.append(MapPoint(float(x), float(y)))
        self._last_yaw = float(yaw) if yaw is not None and is_num(yaw) else None
        return True

    def points(self) -> Tuple[MapPoint, ...]:
        return tuple(self._points)

    def clear(self) -> None:
        self._points.clear()
        self._last_yaw = None
