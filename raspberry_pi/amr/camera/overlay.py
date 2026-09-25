"""C13 — camera-frame hazard overlays (display-only).

This module turns the bbox already carried in :class:`HazardEvent` metadata into
a description an operator UI can draw **on top of a camera image**. It is
pure presentation: it reads a :class:`~amr.camera.frame.CameraFrame` and a list
of hazard event dicts, and returns a description. It captures no frames, issues
no commands, and has no path to a motor, GPIO or serial port.

The coordinate rule
-------------------
A detector's bounding box is **image space** — pixels in the camera frame. It is
never a warehouse coordinate. This module therefore:

* reuses the existing validated
  :class:`~amr.hazard.vision.VisionBoundingBox` rather than inventing a second
  box representation, and
* exposes boxes as :class:`OverlayBox`, which carries ``image_bbox`` and
  explicitly *not* a world position.

There is no image → world transform in this project (no camera calibration is
stored anywhere), so none is performed or implied. An event that carries a real
world ``location`` is reported separately in :attr:`CameraOverlay.world_located`
so the UI can show that it went to the warehouse map, and that is a *different*
fact from where it sits inside the image.

Frame association
-----------------
With several cameras live, painting ``camera_rear`` detections onto a
``camera_front`` image would be a straightforward lie. An event is therefore
only drawn on a frame when its ``source`` matches that frame's source, unless
the frame's source is unknown (then the association is reported as
``unmatched`` rather than guessed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..hazard.vision import VisionBoundingBox

#: Overlay payload schema version.
OVERLAY_SCHEMA_VERSION = "1.0"

#: Colour hints per hazard kind. Presentation only — the renderer may ignore
#: them; they exist so every client draws the same hazard the same way.
KIND_COLORS: Dict[str, str] = {
    "PERSON": "#38bdf8",
    "FIRE": "#f97316",
    "SMOKE": "#a78bfa",
    "OBSTACLE": "#facc15",
    "GAS": "#4ade80",
}

#: Severities that should be drawn as urgent.
CRITICAL_SEVERITIES = ("EMERGENCY", "CRITICAL", "STOP", "SEVERE")


def _num(value: Any) -> Optional[float]:
    """Finite float or ``None``; never NaN/inf leaking into a drawing command."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")):
        return None
    return n


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    out = str(value).strip()
    return out or None


@dataclass(frozen=True)
class OverlayBox:
    """One detection to draw in **image space**.

    ``image_bbox`` is pixels. This type has no world-position field by design:
    adding one later would require a calibration this project does not have.
    """

    kind: str
    severity: Optional[str] = None
    confidence: Optional[float] = None
    label: Optional[str] = None
    source: Optional[str] = None
    event_id: Optional[str] = None
    raised_at: Optional[float] = None
    object_id: Optional[str] = None
    image_bbox: Optional[VisionBoundingBox] = None
    #: False when the box extends past the frame, or its origin is negative.
    fully_visible: bool = True

    @property
    def critical(self) -> bool:
        return (self.severity or "").upper() in CRITICAL_SEVERITIES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "confidence": self.confidence,
            "label": self.label or self.kind,
            "source": self.source,
            "event_id": self.event_id,
            "raised_at": self.raised_at,
            "object_id": self.object_id,
            # Named for its space on purpose. Never rename this to "bbox" and
            # never feed it to a world-coordinate consumer.
            "image_bbox": self.image_bbox.to_dict() if self.image_bbox else None,
            "space": "image",
            "fully_visible": self.fully_visible,
            "color": KIND_COLORS.get(self.kind, "#94a3b8"),
        }


@dataclass(frozen=True)
class CameraOverlay:
    """Everything needed to draw overlays for **one** frame. Display only."""

    image_width: Optional[int] = None
    image_height: Optional[int] = None
    #: Detection identity detections must match to be drawn on this frame.
    camera_source: Optional[str] = None
    #: Backend name from the frame (e.g. "RaspberryPiCamera"). Distinct from
    #: ``camera_source``; published so a UI can show both without conflating them.
    frame_source: Optional[str] = None
    frame_id: Optional[int] = None
    frame_timestamp: Optional[float] = None
    camera_status: Optional[str] = None
    boxes: List[OverlayBox] = field(default_factory=list)
    #: Events with a real world location. They belong on the C9 map, not here —
    #: listed separately so the UI never draws a world pose as if it were pixels.
    world_located: List[Dict[str, Any]] = field(default_factory=list)
    #: Events carrying no usable bbox: they cannot be drawn on the image.
    without_bbox: List[Dict[str, Any]] = field(default_factory=list)
    #: Events from a different camera than the frame being displayed.
    other_source: List[Dict[str, Any]] = field(default_factory=list)
    schema_version: str = OVERLAY_SCHEMA_VERSION

    @property
    def drawable(self) -> bool:
        """Can a box be positioned? Requires both a bbox and image dimensions."""
        return bool(self.boxes) and bool(self.image_width) and bool(self.image_height)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "space": "image",
            "units": "pixels",
            "world_transform": None,
            "image": {
                "width": self.image_width,
                "height": self.image_height,
                "camera_id": self.camera_source,
                "backend": self.frame_source,
                "frame_id": self.frame_id,
                "timestamp": self.frame_timestamp,
                "status": self.camera_status,
            },
            "boxes": [b.to_dict() for b in self.boxes],
            "box_count": len(self.boxes),
            "world_located": [dict(w) for w in self.world_located],
            "without_bbox": [dict(w) for w in self.without_bbox],
            "other_source": [dict(w) for w in self.other_source],
            "drawable": self.drawable,
        }


def _event_kind(event: Dict[str, Any], meta: Dict[str, Any]) -> Optional[str]:
    for key in ("kind", "hazard_kind", "type"):
        val = _text(event.get(key))
        if val:
            return val.upper()
    val = _text(meta.get("kind"))
    return val.upper() if val else None


def _bbox_from_event(event: Dict[str, Any]) -> Optional[VisionBoundingBox]:
    """Read the image-space bbox out of an event's metadata, defensively.

    C5 stores it as ``metadata["bbox"] == [x, y, w, h]``. Anything that is not a
    valid box yields ``None`` — a malformed box is never drawn, never guessed
    at, and never promoted to world space.
    """
    meta = event.get("metadata")
    if not isinstance(meta, dict):
        return None
    raw = meta.get("bbox", meta.get("image_bbox"))
    if raw is None:
        return None
    return VisionBoundingBox.from_any(raw)


def _confidence(event: Dict[str, Any], meta: Dict[str, Any]) -> Optional[float]:
    """Confidence from the event, falling back to metadata (C5 stores it there)."""
    for value in (event.get("confidence"), meta.get("confidence")):
        num = _num(value)
        if num is not None and 0.0 <= num <= 1.0:
            return num
    return None


def build_camera_overlay(
    frame: Any = None,
    events: Optional[Iterable[Any]] = None,
    *,
    camera_id: Optional[str] = None,
) -> CameraOverlay:
    """Assemble the display description for one frame.

    :param frame: a :class:`~amr.camera.frame.CameraFrame` (or anything exposing
        the same attributes). ``None`` is fine and yields an empty overlay, so a
        camera-less deployment still gets a valid response.
    :param events: hazard event dicts — typically
        ``HazardManager.snapshot()["active_events"]``. Anything that is not a
        mapping is skipped rather than crashing the dashboard.
    :param camera_id: the **detection identity** of this camera — the value a
        detector stamps onto :attr:`VisionDetection.source`.

        This is passed explicitly because it is *not* the same thing as
        :attr:`CameraFrame.source`, which names the backend that produced the
        frame (``"SimulatedCamera"``, ``"RaspberryPiCamera"``). Comparing those
        two would be a guess, and guessing here means drawing one camera's
        detections on another camera's picture. When omitted it falls back to
        the frame source, which is correct for a single-camera deployment whose
        detector uses the same identity.

    Three buckets come out, and they are deliberately distinct:

    * ``boxes`` — drawable, in image space, matched to this frame's camera.
    * ``world_located`` — has a real world position, so it belongs on the C9
      map. It is *not* drawn on the image.
    * ``without_bbox`` / ``other_source`` — cannot be drawn here, with the
      reason recorded.
    """
    width = height = None
    frame_source = frame_id = status = None
    timestamp = None
    if frame is not None:
        width = _num(getattr(frame, "width", None))
        height = _num(getattr(frame, "height", None))
        frame_source = _text(getattr(frame, "source", None))
        frame_id = _num(getattr(frame, "frame_id", None))
        timestamp = _num(getattr(frame, "timestamp", None))
        raw_status = getattr(frame, "status", None)
        status = _text(getattr(raw_status, "value", raw_status))
    # The identity detections must match to be drawable on this frame.
    source = _text(camera_id) or frame_source

    boxes: List[OverlayBox] = []
    world_located: List[Dict[str, Any]] = []
    without_bbox: List[Dict[str, Any]] = []
    other_source: List[Dict[str, Any]] = []

    for event in events or ():
        if not isinstance(event, dict):
            continue
        meta = event.get("metadata")
        meta = meta if isinstance(meta, dict) else {}
        kind = _event_kind(event, meta)
        if kind is None:
            continue

        ev_source = _text(event.get("source"))
        # Multi-camera honesty: never paint one camera's detection onto another
        # camera's image. An unknown frame source cannot disprove a match, but it
        # is not evidence for one either, so it is recorded, not assumed.
        if source and ev_source and ev_source != source:
            other_source.append({
                "kind": kind, "source": ev_source, "frame_source": source,
                "reason": "detection belongs to a different camera",
            })
            continue
        if not source or not ev_source:
            if ev_source:
                other_source.append({
                    "kind": kind, "source": ev_source, "frame_source": source,
                    "reason": "frame source unknown: association not assumed",
                })
                continue

        # A real world location is a map fact, not an image fact.
        if event.get("location") is not None:
            world_located.append({
                "kind": kind,
                "severity": _text(event.get("severity")),
                "location": event.get("location"),
                "note": "world located: shown on the 2D map, not on the image",
            })
            continue

        bbox = _bbox_from_event(event)
        if bbox is None:
            without_bbox.append({
                "kind": kind,
                "source": ev_source,
                "reason": "no image-space bounding box: cannot be drawn",
            })
            continue

        fully = True
        if width and height:
            fully = (bbox.x + bbox.width) <= width and \
                    (bbox.y + bbox.height) <= height
        boxes.append(OverlayBox(
            kind=kind,
            severity=_text(event.get("severity")),
            confidence=_confidence(event, meta),
            label=_text(meta.get("label")) or kind,
            source=ev_source,
            event_id=_text(event.get("event_id")),
            raised_at=_num(event.get("raised_at")),
            object_id=_text(event.get("object_id")) or _text(meta.get("object_id")),
            image_bbox=bbox,
            fully_visible=bool(fully),
        ))

    return CameraOverlay(
        image_width=int(width) if width else None,
        image_height=int(height) if height else None,
        camera_source=source,
        frame_source=frame_source,
        frame_id=int(frame_id) if frame_id is not None else None,
        frame_timestamp=timestamp,
        camera_status=status,
        boxes=boxes,
        world_located=world_located,
        without_bbox=without_bbox,
        other_source=other_source,
    )


