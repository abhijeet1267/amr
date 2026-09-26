"""Vision detections - the detector contract feeding the hazard layer (C5).

Camera/vision produces *evidence*; the hazard/safety system stays
authoritative. This module holds **only data + small adapters**: stdlib only,
no OpenCV/YOLO/torch at import. It never touches motors or Arduino.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Protocol, Tuple
from .types import (
    HazardKind,
    HazardLocation,
    HazardReading,
    HazardSeverity,
    VISION_CLASS_TO_KIND,
)
from .sources import severity_for


class VisionClass(str, Enum):
    """Detector output classes with a defined hazard mapping.

    ``UNKNOWN`` is the catch-all for labels with no hazard meaning; detections
    of that class are ignored rather than raising a hazard.
    """

    PERSON = "PERSON"
    FIRE = "FIRE"
    SMOKE = "SMOKE"
    OBSTACLE = "OBSTACLE"
    RESTRICTED_ZONE = "RESTRICTED_ZONE"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, value: Any) -> "VisionClass":
        if isinstance(value, VisionClass):
            return value
        if value is None:
            return cls.UNKNOWN
        # Tolerate a *different* VisionClass enum object. This happens whenever
        # the module is loaded twice (e.g. `python -m amr.hazard.vision` also
        # imports it as `amr.hazard.vision`), in which case isinstance() is
        # False. A str-mixin enum is resolved by its ``value`` so the mapping
        # below still finds the member instead of silently becoming UNKNOWN.
        if isinstance(value, Enum):
            value = getattr(value, "value", value)
        text = str(value).strip().upper()
        aliases = {"HUMAN": cls.PERSON, "PEOPLE": cls.PERSON,
                   "FLAME": cls.FIRE}
        if text in aliases:
            return aliases[text]
        for member in cls:
            if member.value == text or member.name == text:
                return member
        return cls.UNKNOWN


#: The canonical class -> hazard mapping is :data:`VISION_CLASS_TO_KIND` in
#: :mod:`amr.hazard.types`, so it is shared with every other hazard source and
#: can be extended in exactly one place.


def kind_for_class(value: Any) -> Optional[HazardKind]:
    """Hazard kind for a detector label (None = ignore)."""
    try:
        return VISION_CLASS_TO_KIND.get(VisionClass.parse(value).value)
    except Exception:
        return None


def make_vision_reading(
    detection: Any,
    *,
    name: str = "vision",
    warn_at: float = 0.5,
    critical_at: float = 0.8,
) -> Optional[HazardReading]:
    """Translate one detection into a :class:`HazardReading`.

    Accepts a validated :class:`VisionDetection` or a raw dict (which is
    validated first). Anything else -- a stray string, ``None``, a malformed
    object -- is ignored rather than raising, so one bad detector output can
    never take down the AMR's safety loop.
    """
    if not isinstance(detection, VisionDetection):
        # Duck-typed acceptance (see from_any): a detection object created by a
        # different module instance is rebuilt into the local dataclass.
        detection = VisionDetection.from_any(detection)
    if detection is None:
        return None

    kind = kind_for_class(detection.vision_class)
    if kind is None:
        return None
    severity = severity_for(detection.confidence, warn_at, critical_at)
    if severity is HazardSeverity.INFO:
        return None
    source = detection.source or name
    label = detection.vision_class.value
    # Build the evidence context once: bbox / object_id / confidence then reach
    # the event log, the C3 renderer and the C2 web API unchanged. These fields
    # are recorded for audit only and never influence the safety decision.
    metadata = dict(detection.metadata)
    metadata.setdefault("confidence", detection.confidence)
    metadata.setdefault("vision_class", label)
    if detection.object_id is not None:
        metadata.setdefault("object_id", detection.object_id)
    if detection.bbox is not None:
        metadata.setdefault("bbox", detection.bbox.to_list())
    return HazardReading(
        kind=kind,
        value=detection.confidence,
        unit="confidence",
        severity=severity,
        source=source,
        message=(f"{label} detected by {source} "
                 f"(confidence {detection.confidence:.2f})"),
        timestamp=detection.timestamp,
        # Image-space data (bbox) stays in metadata; only a *supplied* world
        # pose is propagated. An absent location stays None so the manager can
        # fall back to the robot pose -- a bbox is never treated as metres.
        location=detection.location,
        metadata=metadata,
    )


def make_vision_readings(
    detections: Any,
    *,
    name: str = "vision",
    warn_at: float = 0.5,
    critical_at: float = 0.8,
) -> Tuple[HazardReading, ...]:
    """Translate detections (or raw dicts) into readings; skip invalid.

    Malformed entries are dropped individually so one bad detection can never
    stop the other valid ones from reaching the hazard layer.
    """
    if detections is None:
        return ()
    out = []
    for item in detections:
        det = (item if isinstance(item, VisionDetection)
               else VisionDetection.from_any(item))
        if det is None:
            continue
        reading = make_vision_reading(det, name=name, warn_at=warn_at,
                                      critical_at=critical_at)
        if reading is not None:
            out.append(reading)
    return tuple(out)


@dataclass(frozen=True)
class VisionBoundingBox:
    """Bounding box in image pixel space (never a warehouse coordinate)."""

    x: float
    y: float
    width: float
    height: float

    @classmethod
    def from_any(cls, value: Any) -> Optional["VisionBoundingBox"]:
        try:
            if isinstance(value, Mapping):
                x = float(value["x"])
                y = float(value["y"])
                w = float(value["width"])
                h = float(value["height"])
            elif isinstance(value, (tuple, list)) and len(value) == 4:
                x, y, w, h = (float(v) for v in value)
            else:
                return None
        except (KeyError, TypeError, ValueError):
            return None
        for v in (x, y, w, h):
            if v != v or v in (float("inf"), float("-inf")):
                return None
        if w <= 0 or h <= 0 or x < 0 or y < 0:
            return None
        return cls(x=x, y=y, width=w, height=h)

    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y,
                "width": self.width, "height": self.height}

    # ``w``/``h`` are the conventional detector-backend spellings, so expose
    # them as read-only aliases rather than duplicating the stored fields.
    @property
    def w(self) -> float:
        return self.width

    @property
    def h(self) -> float:
        return self.height

    def to_list(self) -> Tuple[float, float, float, float]:
        """Compact ``(x, y, width, height)`` form, for JSONL / metadata."""
        return (self.x, self.y, self.width, self.height)


@dataclass(frozen=True)
class VisionDetection:
    """One validated vision detection: evidence, not a safety verdict."""

    vision_class: VisionClass = VisionClass.UNKNOWN
    confidence: float = 0.0
    bbox: Optional[VisionBoundingBox] = None
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"
    location: Optional[HazardLocation] = None
    object_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_any(cls, value: Any) -> Optional["VisionDetection"]:
        """Coerce detector output into a detection; None when invalid."""
        try:
            if isinstance(value, cls):
                return value
            if isinstance(value, Mapping):
                klass = value.get("class", value.get("vision_class",
                                  value.get("label", value.get("kind"))))
                conf = value.get("confidence", value.get("score"))
                ts = value.get("timestamp", time.time())
                src = value.get("source", value.get("camera", "unknown"))
                bbox_raw = value.get("bbox", value.get("bounding_box"))
                loc_raw = value.get("location",
                                    value.get("world_location"))
                oid = value.get("object_id", value.get("track_id"))
                meta = value.get("metadata", {})
            elif isinstance(value, (tuple, list)) and len(value) == 2:
                klass, conf = value
                ts, src = time.time(), "unknown"
                bbox_raw, loc_raw, oid, meta = None, None, None, {}
            else:
                # Duck-typed object. This deliberately does NOT require
                # isinstance(value, VisionDetection): a detector built in
                # another module instance (or an entirely separate package
                # supplying its own detection class) must still be accepted.
                klass = getattr(value, "vision_class",
                        getattr(value, "kind",
                        getattr(value, "label", getattr(value, "cls", None))))
                conf = getattr(value, "confidence",
                       getattr(value, "score", None))
                if klass is None and conf is None:
                    return None
                ts = getattr(value, "timestamp", None)
                if ts is None:
                    ts = time.time()
                src = getattr(value, "source",
                      getattr(value, "camera", "unknown"))
                bbox_raw = getattr(value, "bbox",
                           getattr(value, "bounding_box", None))
                loc_raw = getattr(value, "location",
                          getattr(value, "world_location", None))
                oid = getattr(value, "object_id",
                      getattr(value, "track_id", None))
                meta = getattr(value, "metadata", {})
                if klass is None and conf is None:
                    return None
            vision_class = VisionClass.parse(klass)
            # A label with no defined hazard meaning is *rejected*, not coerced
            # to UNKNOWN: silently reinterpreting "BANANA" as UNKNOWN would
            # hide a real detector/backend integration bug. UNKNOWN is only
            # used for a detection that is explicitly constructed as such,
            # and kind_for_class() maps it to "ignore".
            if vision_class is VisionClass.UNKNOWN and klass is not None \
                    and str(getattr(klass, "value", klass)).strip().upper() \
                    not in ("UNKNOWN", ""):
                return None
            if vision_class is VisionClass.UNKNOWN and klass is None:
                return None
            confidence = float(conf)
            if not 0.0 <= confidence <= 1.0 or confidence != confidence:
                return None
            timestamp = float(ts)
            if timestamp != timestamp:
                return None
            source = str(src) if src else "unknown"
            bbox = (VisionBoundingBox.from_any(bbox_raw)
                    if bbox_raw is not None else None)
            if bbox_raw is not None and bbox is None:
                # A bbox that was supplied but is malformed (wrong arity,
                # non-positive w/h, negative origin) is a detector bug, not a
                # missing field -- reject so it cannot be mistaken for a
                # detection with no geometry.
                return None
            location = (HazardLocation.from_any(loc_raw)
                        if loc_raw is not None else None)
            object_id = str(oid) if oid is not None else None
            metadata = dict(meta) if isinstance(meta, Mapping) else {}
            if bbox is not None:
                # Keep image-space geometry as a *list* under an explicit
                # "bbox" key. It is evidence, never a world coordinate: nothing
                # downstream reads it to produce metres.
                metadata.setdefault("bbox", [bbox.x, bbox.y,
                                             bbox.width, bbox.height])
            return cls(vision_class=vision_class, confidence=confidence,
                       bbox=bbox, timestamp=timestamp, source=source,
                       location=location, object_id=object_id,
                       metadata=metadata)
        except (TypeError, ValueError, AttributeError):
            return None

    @property
    def kind(self) -> Optional[HazardKind]:
        """Hazard kind (None = ignore); uses the canonical table."""
        return kind_for_class(self.vision_class)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "class": self.vision_class.value,
            "confidence": self.confidence,
            "bbox": self.bbox.to_dict() if self.bbox else None,
            "timestamp": self.timestamp,
            "source": self.source,
            "location": self.location.to_dict() if self.location else None,
            "object_id": self.object_id,
            "metadata": dict(self.metadata),
        }


class CameraFrame(Protocol):
    """Structural interface for one captured frame.

    C15b corrected this protocol: it declared ``data()`` as a **method**, but the
    project's real :class:`amr.camera.frame.CameraFrame` carries ``data`` as a
    frozen *attribute* holding the encoded bytes. Nothing ever called
    ``frame.data()`` (it would have raised ``TypeError: 'bytes' object is not
    callable``), so the mismatch was dormant — but it made the real frame fail
    this protocol and would have blocked any frame-based detector.

    Both spellings are now accepted, so a real frame satisfies the protocol and a
    lazy accessor-style frame still works. ``amr.camera.overlay`` reads the same
    attribute directly, so this is a type-level fix only: no behaviour changes.
    """

    frame_id: Any

    @property
    def data(self) -> Any:
        """Encoded frame payload (bytes), or ``None`` for a metadata-only frame."""
        ...


class VisionDetector(Protocol):
    """Structural interface every detector backend must satisfy.

    ``detect`` may take the frame or ignore it. That is deliberate: a real
    detector needs the pixels, while a scripted or already-decoded one does not.
    :class:`~amr.hazard.sources.VisionHazardSource` inspects the callable and
    passes the frame only where it is actually accepted, so both styles work
    through the same hazard pipeline.
    """

    name: str

    def detect(self, frame: Any = None) -> Tuple[VisionDetection, ...]:
        """Return validated detections for frame (empty when none)."""
        ...


# --------------------------------------------------------------------------- #
# Deterministic simulation
# --------------------------------------------------------------------------- #
#: Named, frozen scenarios for reproducible tests and the offline demo. Every
#: value here is SIMULATED INPUT, not a real camera result, and implies no
#: detection accuracy. Timestamps are fixed so runs are byte-for-byte stable.
SIMULATED_SCENARIOS: Dict[str, Tuple[Dict[str, Any], ...]] = {
    "normal": (),
    "person": (
        {"class": "PERSON", "confidence": 0.91, "object_id": "p-1"},
    ),
    "fire": (
        {"class": "FIRE", "confidence": 0.93, "object_id": "f-1"},
    ),
    "smoke": (
        {"class": "SMOKE", "confidence": 0.72, "object_id": "s-1"},
    ),
    "obstacle": (
        {"class": "OBSTACLE", "confidence": 0.88, "object_id": "o-1"},
    ),
    "low_confidence": (
        # Below the default warn threshold -> INFO -> no hazard reading.
        {"class": "PERSON", "confidence": 0.20},
    ),
    "multiple_objects": (
        {"class": "PERSON", "confidence": 0.90, "object_id": "p-1"},
        {"class": "OBSTACLE", "confidence": 0.77, "object_id": "o-1"},
        {"class": "SMOKE", "confidence": 0.65, "object_id": "s-1"},
    ),
    "with_location": (
        # A world pose is supplied explicitly (e.g. from a calibrated
        # detector / localiser). It is never derived from the bbox.
        {
            "class": "FIRE", "confidence": 0.95, "object_id": "f-1",
            "location": {"x": 12.3, "y": 4.7, "frame": "world"},
        },
    ),
    "without_location": (
        {"class": "HUMAN", "confidence": 0.85, "bbox": [10, 20, 60, 120]},
    ),
    "malformed": (
        # Invalid confidence / negative bbox -> rejected by from_any().
        {"class": "PERSON", "confidence": 7.5},
        {"class": "FIRE", "confidence": "not-a-number"},
    ),
    "unknown_class": (
        {"class": "BANANA", "confidence": 0.99},
    ),
    "multiple_cameras": (
        {"class": "PERSON", "confidence": 0.90, "source": "camera_front"},
        {"class": "FIRE", "confidence": 0.88, "source": "camera_rear"},
    ),
    # --- C13: image-space geometry for camera overlays -------------------- #
    # Every bbox below is a pixel rectangle in a 640x480 frame. None of them is
    # a warehouse coordinate, and none may be used as one.
    "person_bbox": (
        {"class": "PERSON", "confidence": 0.91, "object_id": "p-1",
         "bbox": [120, 140, 90, 180], "source": "simulated_camera"},
    ),
    "bbox_multiple": (
        {"class": "PERSON", "confidence": 0.90, "object_id": "p-1",
         "bbox": [60, 150, 80, 170], "source": "simulated_camera"},
        {"class": "FIRE", "confidence": 0.88, "object_id": "f-1",
         "bbox": [380, 120, 120, 150], "source": "simulated_camera"},
        {"class": "OBSTACLE", "confidence": 0.77, "object_id": "o-1",
         "bbox": [250, 330, 140, 70], "source": "simulated_camera"},
    ),
    "bbox_partially_outside": (
        # Deliberately overhanging the right edge, so the overlay can report a
        # partially-visible box instead of silently clipping it.
        {"class": "PERSON", "confidence": 0.86, "object_id": "p-2",
         "bbox": [580, 200, 120, 200], "source": "simulated_camera"},
    ),
    "bbox_world_and_image": (
        # Both spaces present at once: an image box AND an explicit world pose.
        # The image box stays in the overlay; the world pose belongs to the map.
        {"class": "FIRE", "confidence": 0.94, "object_id": "f-2",
         "bbox": [300, 100, 100, 120], "source": "simulated_camera",
         "location": {"x": 12.3, "y": 4.7, "frame": "world"}},
    ),
}


class SimulatedVisionDetector:
    """Deterministic, offline stand-in for a real detector (SIMULATION ONLY).

    Implements :class:`VisionDetector`. Frames are ignored -- output is a
    function of the scripted scenario alone, so the same call always yields the
    same detections. This exists to exercise the pipeline and the demo without
    a camera, ML runtime or model weights; it is **not** a vision system and
    carries no accuracy claim.

    :param scenario: a key of :data:`SIMULATED_SCENARIOS`, or an explicit
        sequence of detection dicts / :class:`VisionDetection` objects.
    :param source: camera identity stamped onto detections that have none
        (e.g. ``simulated_camera``, ``camera_front``).
    :param timestamp: fixed capture time for reproducible output; ``None``
        stamps each detection with the wall clock instead.
    """

    def __init__(
        self,
        scenario: Any = "normal",
        *,
        name: str = "simulated_detector",
        source: str = "simulated_camera",
        timestamp: Optional[float] = 1_700_000_000.0,
    ):
        self.name = name
        self.source = source
        self.timestamp = timestamp
        if isinstance(scenario, str):
            try:
                self._script: Tuple[Any, ...] = tuple(
                    SIMULATED_SCENARIOS[scenario]
                )
            except KeyError:
                raise ValueError(
                    f"unknown scenario {scenario!r}; "
                    f"expected one of {sorted(SIMULATED_SCENARIOS)}"
                ) from None
            self.scenario: Optional[str] = scenario
        else:
            self._script = tuple(scenario or ())
            self.scenario = None

    def detect(self, frame: Any = None) -> Tuple[VisionDetection, ...]:
        """Return the scripted detections; ``frame`` is deliberately unused."""
        out: List[VisionDetection] = []
        for item in self._script:
            det = (item if isinstance(item, VisionDetection)
                   else VisionDetection.from_any(item))
            if det is None:  # malformed entry -> skipped, never raises
                continue
            det = self._stamp(det)
            out.append(det)
        return tuple(out)

    def _stamp(self, det: VisionDetection) -> VisionDetection:
        """Apply this detector's source / timestamp when unset."""
        source = self.source if det.source == "unknown" else det.source
        timestamp = det.timestamp if self.timestamp is None else self.timestamp
        if source == det.source and timestamp == det.timestamp:
            return det
        return replace(
            det, source=source, timestamp=timestamp,
        )


def simulate(
    scenario: Any = "normal", **kwargs: Any
) -> Tuple[HazardReading, ...]:
    """One-shot helper: run a scenario straight into :class:`HazardReading`."""
    detector = SimulatedVisionDetector(scenario, **kwargs)
    return make_vision_readings(detector.detect(None))


#: Backwards-compatible alias for the name used in earlier drafts.
FakeVisionDetector = SimulatedVisionDetector



# --------------------------------------------------------------------------- #
# Offline demonstration:  python -m amr.hazard.vision
# --------------------------------------------------------------------------- #
def _demo(scenarios: Optional[Sequence[str]] = None) -> int:
    """Run the full pipeline offline with SIMULATED detections only.

    Prints each detection, the hazard reading it produced, the safety verdict
    and the recorded event. No camera, no ML runtime, no robot is involved.
    """
    from ..utils.config import HazardConfig
    from .manager import HazardManager
    from .sources import VisionHazardSource

    names = list(scenarios or ("normal", "person", "fire", "smoke",
                               "low_confidence", "malformed", "unknown_class"))
    print("C5 vision -> hazard demo (SIMULATED detections; no camera, no ML)")
    print("=" * 72)

    recorded = 0
    for name in names:
        print(f"\n--- scenario: {name} ---")
        detector = SimulatedVisionDetector(name)
        try:
            raw = detector.detect(None)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"  detector error: {exc}")
            continue

        if not raw:
            print("  vision detection: none")
        for det in raw:
            loc = (f" @ world({det.location.x:.2f}, {det.location.y:.2f})"
                   if det.location else " @ image-only (no world pose)")
            print(f"  vision detection: {det.vision_class.value} "
                  f"confidence={det.confidence:.2f} source={det.source}{loc}")

        # One manager per scenario keeps the event log honest and deterministic.
        cfg = HazardConfig(enabled=True, vision_enabled=True)
        warn, crit = cfg.resolved_vision_thresholds()
        mgr = HazardManager(cfg)
        mgr.add_source(VisionHazardSource(detector.detect,
                                          name=name, warn_at=warn,
                                          critical_at=crit))
        status = mgr.evaluate()
        for reading in status.readings:
            print(f"  hazard reading: {reading.kind.value} "
                  f"severity={reading.severity.value} "
                  f"value={reading.value:.2f} source={reading.source}")
        if not status.readings:
            print("  hazard reading: none (below threshold or no hazard class)")

        print(f"  hazard state:   {status.state.value}"
              f" latched={status.latched} blocks_motion={status.blocks_motion}")
        for event in mgr.events.recent():
            recorded += 1
            conf = event.confidence
            conf_txt = f" confidence={conf:.2f}" if conf is not None else ""
            loc = (" @ world" if event.location else " @ image-only")
            print(f"  event recorded: {event.kind.value} "
                  f"state={event.state.value}{conf_txt} "
                  f"source={event.source}{loc}")

    print("\n" + "=" * 72)
    print(f"events_recorded={recorded}")
    print("SIMULATION ONLY: no camera was read and no robot was controlled.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m amr.hazard.vision",
        description=(
            "Deterministic vision->hazard demo using SIMULATED detections. "
            "No camera or ML backend is used and no accuracy is implied."
        ),
    )
    parser.add_argument(
        "scenarios", nargs="*", metavar="SCENARIO",
        help=f"scenarios to run (default: a few). Known: "
             f"{', '.join(sorted(SIMULATED_SCENARIOS))}",
    )
    args = parser.parse_args()
    known = [s for s in args.scenarios if s in SIMULATED_SCENARIOS]
    unknown = [s for s in args.scenarios if s not in SIMULATED_SCENARIOS]
    for name in unknown:
        print(f"unknown scenario {name!r} (skipped)", flush=True)
    raise SystemExit(_demo(known or None))

