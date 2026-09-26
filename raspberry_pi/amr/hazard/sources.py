"""Hazard sources — adapters that turn external signals into readings.

Every source implements the tiny :class:`HazardSource` protocol::

    class HazardSource(Protocol):
        name: str
        def read(self) -> Tuple[HazardReading, ...]: ...

Sources are **thin and dependency-injected**: none of them touch hardware, a
camera or a bus directly. They wrap a *callable* supplied by the caller (a GPIO
read, a vision detector, a state getter), which keeps the whole hazard layer
testable with no hardware attached — the same philosophy as ``amr/mocks``.

Import hygiene
--------------
This module deliberately imports nothing from :mod:`amr.robot` or
:mod:`amr.navigation`. Robot/navigation objects are read through duck typing so
``amr.hazard`` can be imported from the robot manager without a circular import.

Fail-safe default
-----------------
A source that has *no data* reports a ``WARNING`` reading rather than silence:
on a safety layer, "the gas sensor is not answering" is not the same as "the air
is clean". Pass ``missing_is_warning=False`` to opt out for a source that is
genuinely optional.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, List, Optional, Protocol, Sequence, Tuple

from .types import (
    HazardKind,
    HazardLocation,
    HazardReading,
    HazardSeverity,
)


def severity_for(
    value: float,
    warn_at: float,
    critical_at: float,
) -> HazardSeverity:
    """Map a numeric measurement onto a severity using two thresholds.

    ``value >= critical_at`` -> ``CRITICAL``; ``value >= warn_at`` -> ``WARNING``;
    otherwise ``INFO``. A non-positive ``critical_at`` disables the critical band
    (a source that can only ever warn).
    """
    if critical_at > 0 and value >= critical_at:
        return HazardSeverity.CRITICAL
    if value >= warn_at:
        return HazardSeverity.WARNING
    return HazardSeverity.INFO


class HazardSource(Protocol):
    """Structural interface every hazard input must satisfy."""

    name: str

    def read(self) -> Tuple[HazardReading, ...]:
        """Return the readings observed right now (empty when nothing to say)."""
        ...


class GasSensorSource:
    """Gas / smoke sensor (e.g. MQ-2) driven by an injected reader callable.

    ``reader()`` returns the raw concentration in ``unit`` (or ``None`` when the
    sensor cannot be read). Thresholds come from ``config/hazard.yaml``.
    """

    def __init__(
        self,
        reader: Callable[[], Optional[float]],
        name: str = "gas",
        kind: HazardKind = HazardKind.GAS,
        unit: str = "ppm",
        warn_at: float = 300.0,
        critical_at: float = 1000.0,
        missing_is_warning: bool = True,
    ):
        self.name = name
        self._reader = reader
        self._kind = HazardKind.parse(kind)
        self._unit = unit
        self._warn_at = float(warn_at)
        self._critical_at = float(critical_at)
        self._missing_is_warning = bool(missing_is_warning)

    def read(self) -> Tuple[HazardReading, ...]:
        try:
            raw = self._reader()
        except Exception as exc:  # noqa: BLE001 - a bad reader must not crash us
            return (self._fault(f"{self.name} reader failed: {exc}"),)

        if raw is None:
            if not self._missing_is_warning:
                return ()
            return (
                HazardReading(
                    kind=self._kind,
                    severity=HazardSeverity.WARNING,
                    source=self.name,
                    message=f"{self.name} sensor reported no data",
                ),
            )

        value = float(raw)
        severity = severity_for(value, self._warn_at, self._critical_at)
        if severity is HazardSeverity.INFO:
            return ()
        if severity is HazardSeverity.CRITICAL:
            band = f"critical >= {self._critical_at:g}{self._unit}"
        else:
            band = f"warn >= {self._warn_at:g}{self._unit}"
        return (
            HazardReading(
                kind=self._kind,
                value=value,
                unit=self._unit,
                severity=severity,
                source=self.name,
                message=f"{self.name} {value:g}{self._unit} ({band})",
            ),
        )

    def _fault(self, message: str) -> HazardReading:
        return HazardReading(
            kind=HazardKind.ROBOT_FAULT,
            severity=HazardSeverity.WARNING,
            source=self.name,
            message=message,
        )


def _accepts_argument(fn: Any) -> bool:
    """Can ``fn`` be called with one positional argument?

    C15b uses this to tell a frame-based :class:`VisionDetector` apart from the
    original zero-argument callable. It inspects the signature rather than
    trusting a flag, so both styles keep working. Anything whose signature cannot
    be read (``*args``/builtin/C extension) is assumed to accept the frame, which
    is the safe direction: passing an unexpected frame is harmless for a
    detector that ignores it, whereas never passing one would silently starve a
    detector that needs it.
    """
    import inspect

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    for param in sig.parameters.values():
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD,
                          param.VAR_POSITIONAL):
            return True
    return False


class VisionHazardSource:
    """Visual hazards from a vision detector callback (C5 evidence adapter).

    ``detector()`` returns an iterable of detections (a static iterable of
    detections may be supplied directly instead of a callable, for replay and
    tests). Each detection may be

    * a :class:`~amr.hazard.vision.VisionDetection` (the canonical C5 contract:
      class, confidence, bbox, timestamp, source, optional world location) --
      validated and mapped through :mod:`amr.hazard.vision`, or
    * a :class:`HazardReading` (passed through, with ``source`` re-stamped when
      it is still ``"unknown"``), or
    * a ``(kind, confidence)`` pair, where ``confidence`` is 0..1 and is mapped
      to a severity via ``warn_at`` / ``critical_at``.

    An optional third element is a message string. A detector that returns
    nothing means "no visual hazard". This source only *produces evidence* --
    it never decides a safety state and never drives motors.

    **C15b — frames.** The detector may be one of two shapes:

    * a zero-argument callable (the original contract, used by
      :class:`~amr.hazard.vision.SimulatedVisionDetector`), or
    * a :class:`~amr.hazard.vision.VisionDetector` whose ``detect`` accepts a
      frame, which is what a real camera backend needs.

    :meth:`call_detector` distinguishes them by inspecting the callable's
    signature, so both keep working unchanged. When a detector needs frames, pass
    a ``frame_provider`` (typically ``camera.read``); the frame is then acquired
    here, at the same point the hazard verdict is produced, so the detections are
    guaranteed to describe *this* evaluation.
    """

    def __init__(
        self,
        detector: Any,
        name: str = "vision",
        warn_at: float = 0.5,
        critical_at: float = 0.8,
        fault_kind: HazardKind = HazardKind.ROBOT_FAULT,
        fault_severity: HazardSeverity = HazardSeverity.WARNING,
        frame_provider: Optional[Callable[[], Any]] = None,
    ):
        self.name = name
        self._detector = detector
        self._warn_at = float(warn_at)
        self._critical_at = float(critical_at)
        #: C15b: supplies the current camera frame to a frame-based detector.
        #: ``None`` keeps the original zero-argument behaviour.
        self._frame_provider = frame_provider
        #: Detector failures are reported as a fault reading. The defaults
        #: keep the pre-C5 behaviour (``ROBOT_FAULT`` / ``WARNING``); a
        #: deployment may opt into the dedicated ``VISION_FAULT`` kind.
        self.fault_kind = HazardKind.parse(fault_kind)
        self.fault_severity = HazardSeverity.parse(fault_severity)

    def call_detector(self) -> Any:
        """Invoke the detector, passing a frame only if it can accept one.

        Three shapes are accepted, in this order:

        1. an object with a ``detect`` method — i.e. a real
           :class:`~amr.hazard.vision.VisionDetector` (C15b);
        2. a plain callable — the original contract, where
           ``VisionHazardSource(detector.detect)`` was passed;
        3. a materialised sequence of detections (replay, recorded frames).

        A frame is passed only where the callable actually accepts one, decided
        by inspecting its signature, so an existing zero-argument callable keeps
        working untouched. The frame is acquired here, at the same moment the
        hazard verdict is produced, so the returned detections are guaranteed to
        describe *this* evaluation.
        """
        detector = self._detector
        if not callable(detector):
            detect = getattr(detector, "detect", None)
            if not callable(detect):
                return detector          # a plain sequence of detections
            detector = detect
        if not _accepts_argument(detector):
            return detector()
        frame = None
        if self._frame_provider is not None:
            try:
                frame = self._frame_provider()
            except Exception as exc:  # noqa: BLE001
                # A camera that cannot deliver a frame is a *detector* failure and
                # is reported as a fault reading, never as "no hazard detected".
                raise RuntimeError(
                    f"{self.name} frame provider failed: {exc}") from exc
        return detector(frame)

    def read(self) -> Tuple[HazardReading, ...]:
        try:
            # The detector may be a zero-argument callback (the original live
            # case), a frame-based VisionDetector (C15b), or an already-
            # materialised sequence of detections (handy for replay, recorded
            # frames and tests). Supporting all three keeps the adapter
            # backend-agnostic without adding a second class.
            detections = self.call_detector()
        except Exception as exc:  # noqa: BLE001 - a bad detector must not crash us
            return (
                HazardReading(
                    kind=self.fault_kind,
                    severity=self.fault_severity,
                    source=self.name,
                    message=f"{self.name} detector failed: {exc}",
                ),
            )

        readings: List[HazardReading] = []
        for detection in detections or ():
            reading = self._convert(detection)
            if reading is not None:
                readings.append(reading)
        return tuple(readings)

    def _convert(self, detection: Any) -> Optional[HazardReading]:
        # C5 canonical contract: validate + map a VisionDetection. The import
        # is local so amr.hazard.sources stays importable on its own and the
        # vision module is never loaded unless vision evidence is in use.
        if not isinstance(detection, (HazardReading, tuple, list)):
            try:
                from .vision import make_vision_reading
            except Exception:  # pragma: no cover - defensive
                return None
            reading = make_vision_reading(
                detection,
                name=self.name,
                warn_at=self._warn_at,
                critical_at=self._critical_at,
            )
            if reading is None:
                return None
            # Keep the *source* identity of the camera (multi-camera support)
            # when the detection names one; otherwise fall back to our name.
            if reading.source not in ("unknown", self.name):
                return reading
            return replace(reading, source=self.name)

        if isinstance(detection, HazardReading):
            if detection.source != "unknown":
                return detection
            return replace(detection, source=self.name)
        if isinstance(detection, (tuple, list)) and len(detection) >= 2:
            kind = HazardKind.parse(detection[0])
            confidence = float(detection[1])
            message = str(detection[2]) if len(detection) > 2 else ""
            severity = severity_for(confidence, self._warn_at, self._critical_at)
            if severity is HazardSeverity.INFO:
                return None
            text = message or (
                f"{kind.value} detected by {self.name} "
                f"(confidence {confidence:.2f})"
            )
            return HazardReading(
                kind=kind,
                value=confidence,
                unit="confidence",
                severity=severity,
                source=self.name,
                message=text,
            )
        return None


def _status_text(value: Any) -> str:
    """Normalise a status enum/string to an upper-case token."""
    if value is None:
        return ""
    inner = getattr(value, "value", value)
    return str(inner).strip().upper()


class RobotStateSource:
    """Robot / navigation state as a hazard input.

    Inputs are duck-typed, so no import of :mod:`amr.robot` is needed:

    * ``state_provider()`` -> object with ``connected`` (bool), ``mode``
      (enum or str) and ``last_error`` (str or ``None``)
    * ``nav_provider()`` -> optional object with ``status`` (enum or str, where
      ``FAILED``/``CANCELLED`` are unhealthy) and ``error``

    A lost controller link is reported ``CRITICAL`` (motion must stop); a stale
    robot error or a failed navigation attempt is reported ``WARNING``. At most
    one reading is emitted, worst-first, to avoid duplicate events.
    """

    def __init__(
        self,
        state_provider: Callable[[], Any],
        nav_provider: Optional[Callable[[], Any]] = None,
        name: str = "robot_state",
    ):
        self.name = name
        self._state_provider = state_provider
        self._nav_provider = nav_provider

    def read(self) -> Tuple[HazardReading, ...]:
        state = self._safe(self._state_provider)
        if state is _UNAVAILABLE:
            return (self._fault("state unavailable", HazardSeverity.WARNING),)

        if state is not None and getattr(state, "connected", True) is False:
            return (self._fault("controller link down", HazardSeverity.CRITICAL),)

        if state is not None and getattr(state, "last_error", None):
            return (
                self._fault(
                    f"robot error: {state.last_error}", HazardSeverity.WARNING
                ),
            )

        if self._nav_provider is not None:
            nav = self._safe(self._nav_provider)
            if nav is _UNAVAILABLE:
                return (self._fault("nav unavailable", HazardSeverity.WARNING),)
            if nav is not None:
                status = _status_text(getattr(nav, "status", None))
                if status in ("FAILED", "CANCELLED"):
                    detail = getattr(nav, "error", None) or status.lower()
                    return (
                        self._fault(
                            f"navigation {status.lower()}: {detail}",
                            HazardSeverity.WARNING,
                        ),
                    )

        return ()

    def _fault(self, message: str, severity: HazardSeverity) -> HazardReading:
        return HazardReading(
            kind=HazardKind.ROBOT_FAULT,
            severity=severity,
            source=self.name,
            message=f"{self.name}: {message}",
        )

    @staticmethod
    def _safe(provider: Callable[[], Any]) -> Any:
        try:
            return provider()
        except Exception:  # noqa: BLE001 - a bad provider must not crash us
            return _UNAVAILABLE


#: Sentinel distinguishing "provider raised" from "provider returned None".
_UNAVAILABLE = object()


@dataclass(frozen=True)
class HazardZone:
    """An axis-aligned rectangular area of interest in the world frame (metres).

    Zones give the hazard layer *context*: the same air quality reading means
    different things in a battery-charging bay than in an open aisle. A robot
    whose location falls inside a zone raises a zone reading, which the future
    spatial hazard visualisation can also draw directly.
    """

    name: str
    x_min: float = 0.0
    x_max: float = 0.0
    y_min: float = 0.0
    y_max: float = 0.0
    severity: HazardSeverity = HazardSeverity.CRITICAL
    kind: HazardKind = HazardKind.ZONE_BREACH

    def __post_init__(self) -> None:
        # Tolerate swapped bounds and string values from YAML. The originals must
        # be read before any assignment, otherwise the second setattr would see
        # the already-clamped value.
        xs = sorted((float(self.x_min), float(self.x_max)))
        ys = sorted((float(self.y_min), float(self.y_max)))
        object.__setattr__(self, "x_min", xs[0])
        object.__setattr__(self, "x_max", xs[1])
        object.__setattr__(self, "y_min", ys[0])
        object.__setattr__(self, "y_max", ys[1])
        object.__setattr__(self, "severity", HazardSeverity.parse(self.severity))
        object.__setattr__(self, "kind", HazardKind.parse(self.kind))

    def contains(self, location: Any) -> bool:
        """``True`` when ``location`` (pose-like) lies inside this rectangle."""
        pos = HazardLocation.from_any(location)
        if pos is None:
            return False
        return (
            self.x_min <= pos.x <= self.x_max and self.y_min <= pos.y <= self.y_max
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "x_min": self.x_min,
            "x_max": self.x_max,
            "y_min": self.y_min,
            "y_max": self.y_max,
            "severity": self.severity.value,
            "kind": self.kind.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HazardZone":
        """Build a zone from a YAML/JSON mapping (``name`` is required)."""
        blob = dict(data or {})
        if "name" not in blob:
            raise ValueError("hazard zone requires a name")
        return cls(
            name=str(blob["name"]),
            x_min=float(blob.get("x_min", 0.0)),
            x_max=float(blob.get("x_max", 0.0)),
            y_min=float(blob.get("y_min", 0.0)),
            y_max=float(blob.get("y_max", 0.0)),
            severity=blob.get("severity", HazardSeverity.CRITICAL),
            kind=blob.get("kind", HazardKind.ZONE_BREACH),
        )


class RestrictedZoneSource:
    """Raises a reading when the robot's location is inside a configured zone.

    The pose is fetched through an injected ``pose_provider`` (duck-typed: any
    object with ``x``/``y``). With no pose available the source stays silent —
    a missing location must never invent a hazard.
    """

    def __init__(
        self,
        zones: Sequence[HazardZone],
        pose_provider: Optional[Callable[[], Any]] = None,
        name: str = "zones",
    ):
        self.name = name
        self._zones = tuple(zones or ())
        self._pose_provider = pose_provider

    @property
    def zones(self) -> Tuple[HazardZone, ...]:
        return self._zones

    def read(self) -> Tuple[HazardReading, ...]:
        if self._pose_provider is None:
            return ()
        try:
            pose = self._pose_provider()
        except Exception as exc:  # noqa: BLE001 - a bad provider must not crash us
            return (
                HazardReading(
                    kind=HazardKind.ROBOT_FAULT,
                    severity=HazardSeverity.WARNING,
                    source=self.name,
                    message=f"{self.name} pose unavailable: {exc}",
                ),
            )

        location = HazardLocation.from_any(pose)
        if location is None:
            return ()

        readings: List[HazardReading] = []
        for zone in self._zones:
            if zone.contains(location):
                readings.append(
                    HazardReading(
                        kind=zone.kind,
                        value=1.0,
                        unit="bool",
                        severity=zone.severity,
                        source=self.name,
                        message=(
                            f"robot inside zone '{zone.name}' "
                            f"({location.x:.2f}, {location.y:.2f})"
                        ),
                    )
                )
        return tuple(readings)


def zones_from_config(config: Any) -> Tuple[HazardZone, ...]:
    """Build :class:`HazardZone` objects from ``hazard.zones`` config entries.

    Invalid entries are skipped rather than raising, so one typo in a YAML file
    cannot prevent the robot from starting.
    """
    zones: List[HazardZone] = []
    for entry in getattr(config, "zones", None) or ():
        if isinstance(entry, HazardZone):
            zones.append(entry)
            continue
        if isinstance(entry, dict):
            try:
                zones.append(HazardZone.from_dict(entry))
            except (TypeError, ValueError):
                continue
    return tuple(zones)
