"""C15b — a real camera frame reaching the existing vision pipeline.

The gap this module fills
-------------------------
The project already had a :class:`~amr.camera.frame.RaspberryPiCameraSource`
(C8) and a :class:`~amr.hazard.vision.VisionDetector` protocol, but **nothing
connected them**: :class:`~amr.hazard.sources.VisionHazardSource` called its
detector with no arguments, so a detector that needed pixels could never be
used. C15b closes that gap with :class:`CameraFrameDetector`, which

    CameraSource.read()  ->  CameraFrame  ->  inference  ->  VisionDetection

and then feeds the detections through the *existing*, unmodified
``VisionDetection -> VisionHazardSource -> HazardManager`` path. No parallel
hazard route is introduced.

No model is hard-coded
---------------------
Object-detection inference is a separate, **injected** callable. The project has
no validated detector, so inventing one — or pulling in YOLO/TensorFlow/PyTorch —
would manufacture an accuracy claim. ``inference=None`` therefore reports **no
detections**, which is the honest answer for "frame acquisition without a
validated model". Adding a real model later means passing a callable; nothing
here changes.

Image space
-----------
A detection's ``bbox`` stays in **pixels** and is stamped with the frame's own
width/height, so the C13 overlay can scale it. It is never converted to world
coordinates: this class has no calibration, and inventing one is exactly the
fabrication the project rules forbid.

Hardware status
---------------
**NOT TESTED.** The Pi camera has not been connected. See
``docs/camera_backend.md`` for the 15-pin -> 22-pin adapter requirement on a
Raspberry Pi 5.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..hazard.vision import (
    VisionBoundingBox,
    VisionClass,
    VisionDetection,
    VisionDetector,
)
from ..logging import get_logger

#: Identity reported when the caller declares no ``camera_id``. This is a *name*,
#: never a status: ``LIVE``/``SIMULATION`` come from the camera, not from here.
DEFAULT_CAMERA_ID = "camera_frame"


def _accepts_argument(fn: Any) -> bool:
    """Can ``fn`` be called with one positional argument? (See sources.py.)"""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    for param in sig.parameters.values():
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD,
                          param.VAR_POSITIONAL):
            return True
    return False


class CameraFrameDetector:
    """A :class:`~amr.hazard.vision.VisionDetector` fed by a real camera.

    Implements the existing protocol: ``detect(frame=None)`` returns
    :class:`~amr.hazard.vision.VisionDetection` objects. When no frame is passed,
    one is acquired from the configured :class:`CameraSource`.

    :param camera: any :class:`~amr.camera.frame.CameraSource`. On a developer
        machine this can be a :class:`SimulatedCameraSource`; on the Pi it is
        the :class:`RaspberryPiCameraSource`. Same contract either way.
    :param inference: ``inference(frame) -> detections``. ``None`` (the default)
        means "no validated model is configured", so the detector reports **no
        detections** instead of guessing. This is where a real model would go.
    :param camera_id: the **detection identity** stamped on every detection
        (matching ``CameraConfig.camera_id`` and what the C13 overlay pairs on).
        It is deliberately distinct from ``CameraFrame.source``, which names the
        backend (``"RaspberryPiCamera"``).
    :param classes: optional allow-list of detector labels to keep.
    :param stamp_frame_metadata: attach ``frame_id`` / image size to each
        detection's metadata so an overlay can scale the box.
    """

    def __init__(
        self,
        camera: Any,
        *,
        inference: Optional[Callable[[Any], Any]] = None,
        camera_id: Optional[str] = None,
        name: Optional[str] = None,
        classes: Optional[Tuple[str, ...]] = None,
        stamp_frame_metadata: bool = True,
    ) -> None:
        self.camera = camera
        self.inference = inference
        self.camera_id = camera_id or getattr(camera, "name", None) \
            or DEFAULT_CAMERA_ID
        self.name = name or "camera_frame_detector"
        self._classes = tuple(c.upper() for c in classes) if classes else None
        self._stamp = bool(stamp_frame_metadata)
        self.log = get_logger("vision.detector")
        #: Counters for honest reporting; never used to make a claim.
        self.frames_seen = 0
        self.detections_made = 0
        self.inference_errors = 0

    # -- status ------------------------------------------------------------- #
    @property
    def available(self) -> bool:
        """True when a model is configured *and* the camera has a frame."""
        return self.inference is not None

    def describe(self) -> Dict[str, Any]:
        """Honest description: what is wired, and what is genuinely absent."""
        camera_status = None
        describe = getattr(self.camera, "describe", None)
        if callable(describe):
            try:
                camera_status = describe()
            except Exception:  # noqa: BLE001 - description must never raise
                camera_status = None
        return {
            "name": self.name,
            "camera_id": self.camera_id,
            "inference_configured": self.inference is not None,
            "frames_seen": self.frames_seen,
            "detections_made": self.detections_made,
            "inference_errors": self.inference_errors,
            "classes": list(self._classes) if self._classes else None,
            "camera": camera_status,
        }

    # -- detection ---------------------------------------------------------- #
    def detect(self, frame: Any = None) -> Tuple[VisionDetection, ...]:
        """Detections for one frame, acquiring one from the camera if needed.

        Never raises: a camera that cannot deliver a frame, or a model that
        throws, yields **no detections** plus an error counter. It does not yield
        "all clear" — an unusable pipeline is not evidence of safety, and the
        surrounding :class:`~amr.hazard.sources.VisionHazardSource` reports a
        fault reading in that case.
        """
        if frame is None:
            frame = self._acquire()
        if frame is None:
            return ()
        self.frames_seen += 1
        if self.inference is None:
            # No validated model: frame acquisition only. Reporting nothing is
            # the honest answer; inventing a "no hazards" verdict is not.
            return ()
        try:
            raw = self.inference(frame)
        except Exception as exc:  # noqa: BLE001 - a bad model must not crash us
            self.inference_errors += 1
            self.log.warning("inference failed: %s", exc)
            return ()
        out: List[VisionDetection] = []
        for item in raw or ():
            det = self._coerce(item, frame)
            if det is not None:
                out.append(det)
        self.detections_made += len(out)
        return tuple(out)

    def _acquire(self) -> Any:
        """One frame from the camera, or ``None`` when it cannot be read."""
        read = getattr(self.camera, "read", None)
        if not callable(read):
            return None
        try:
            return read()
        except Exception as exc:  # noqa: BLE001
            self.log.warning("camera read failed: %s", exc)
            return None

    def _coerce(self, item: Any, frame: Any) -> Optional[VisionDetection]:
        """Validate one model output into a :class:`VisionDetection`.

        Anything malformed is dropped individually, so one bad box cannot hide
        the other valid detections.
        """
        det = (item if isinstance(item, VisionDetection)
               else VisionDetection.from_any(item))
        if det is None:
            return None
        if self._classes is not None and \
                det.vision_class.value not in self._classes:
            return None
        # Stamp the camera identity so the C13 overlay pairs a detection with the
        # frame it actually came from, not merely with "a" camera.
        if det.source == "unknown":
            det = _replace(det, source=self.camera_id)
        if det.timestamp is None:
            ts = _frame_timestamp(frame)
            if ts is not None:
                det = _replace(det, timestamp=ts)
        if self._stamp:
            det = _replace(det, metadata=self._metadata(det, frame))
        return det

    def _metadata(self, det: VisionDetection, frame: Any) -> Dict[str, Any]:
        """Attach image-space frame context, never a world coordinate."""
        meta = dict(det.metadata or {})
        meta.setdefault("vision_class", det.vision_class.value)
        meta.setdefault("confidence", det.confidence)
        width = _frame_number(frame, "width")
        height = _frame_number(frame, "height")
        if width and height:
            # The bbox is only interpretable against the image it came from.
            meta.setdefault("image_size", [int(width), int(height)])
        frame_id = _frame_number(frame, "frame_id")
        if frame_id is not None:
            meta.setdefault("frame_id", int(frame_id))
        return meta


def _replace(det: VisionDetection, **changes: Any) -> VisionDetection:
    import dataclasses

    return dataclasses.replace(det, **changes)


def _frame_number(frame: Any, attr: str) -> Optional[float]:
    value = getattr(frame, attr, None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value != value:                       # NaN
        return None
    return value


def _frame_timestamp(frame: Any) -> Optional[float]:
    return _frame_number(frame, "timestamp")


__all__ = ["CameraFrameDetector", "DEFAULT_CAMERA_ID", "VisionClass",
           "VisionDetector"]
