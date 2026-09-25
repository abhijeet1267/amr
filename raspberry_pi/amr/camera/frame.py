"""Stable camera-frame contract (C8).

The dashboard needs to know *what the camera is doing* without ever holding a
raw image in a telemetry snapshot. This module therefore separates two things
the pre-C8 code had conflated:

* :class:`CameraStatus` — an honest verdict: is this **real hardware**, a
  **simulation**, **absent**, or **broken**? A simulated frame is never
  reported as live footage.
* :class:`CameraFrame` — one captured frame plus metadata genuinely true of
  it. The pixel payload is carried *by reference* and is deliberately **not**
  in :meth:`CameraFrame.to_dict`, so a snapshot stays small enough to ship to a
  Raspberry Pi browser on every poll.

The payload is bytes in an encoded container (JPEG/PNG). The repo has no image
dependency by design, so a frame is a transport envelope, not an ndarray.

Typical wiring::

    CameraSource  ->  CameraFrame  ->  (VisionDetector)  ->  HazardManager
                         |
                         +-> CameraTelemetry  ->  GET /telemetry

Real-hardware sources import their SDK **lazily** inside :meth:`read`; this
module itself is pure standard library so the package imports anywhere.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import time
import zlib
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Dict,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)


class CameraStatus(Enum):
    """How a camera backend is *actually* running — never aspirational.

    ``LIVE`` is only ever used for a real device that just produced a frame.
    """

    LIVE = "LIVE"              # real hardware, frames available
    SIMULATION = "SIMULATION"  # deterministic stand-in, NOT real footage
    UNAVAILABLE = "UNAVAILABLE"  # no camera / disabled / SDK missing
    ERROR = "ERROR"            # present but failing

    @property
    def available(self) -> bool:
        """``True`` when a camera is configured and usable in this state.

        ``ERROR`` is a camera that *exists but is failing*, so it is not
        reported as available for monitoring purposes.
        """
        return self in (CameraStatus.LIVE, CameraStatus.SIMULATION)

    @classmethod
    def parse(cls, value: Any,
              default: Optional["CameraStatus"] = None) -> "CameraStatus":
        """Tolerant parse used for external / legacy callers."""
        default = cls.UNAVAILABLE if default is None else default
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().upper())
        except (ValueError, AttributeError):
            return default


@dataclass(frozen=True)
class CameraFrame:
    """One captured frame plus metadata that is genuinely known about it.

    :param timestamp: capture time (epoch seconds); ``None`` means "unknown",
        never "now" as a fabricated value.
    :param source: human-readable backend identity, e.g. ``"SimulatedCamera"``
        or ``"RaspberryPiCamera"``. This is a *name*, not a status.
    :param width: pixel width, or ``None`` if the backend did not report one.
    :param height: pixel height, or ``None`` if unknown.
    :param format: container of :attr:`data` (e.g. ``"jpeg"``/``"png"``).
    :param frame_id: monotonically increasing frame counter.
    :param data: encoded image bytes, or ``None`` for a metadata-only frame.
    :param status: the honest :class:`CameraStatus` for this capture.
    :param metadata: free-form, non-safety-critical context.

    Every optional field is genuinely optional: a source that cannot measure
    its resolution leaves ``width``/``height`` as ``None`` rather than copying
    a configured-but-unverified value.
    """

    timestamp: Optional[float] = None
    source: str = "unknown"
    width: Optional[int] = None
    height: Optional[int] = None
    format: Optional[str] = None
    frame_id: int = 0
    data: Optional[bytes] = None
    status: CameraStatus = CameraStatus.UNAVAILABLE
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", CameraStatus.parse(self.status))
        if self.data is not None and not isinstance(self.data, (bytes, bytearray)):
            raise TypeError("CameraFrame.data must be bytes or None")
        object.__setattr__(self, "data", bytes(self.data) if self.data else None)
        # A non-positive or non-integer dimension is a broken reading, not a
        # measurement: null it so telemetry reports "unknown" rather than a size
        # no camera could have produced.
        for name in ("width", "height"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                object.__setattr__(self, name, None)
        # Copy so a caller mutating its dict cannot change an already-captured
        # frame, which is what makes the frozen contract actually frozen.
        object.__setattr__(
            self, "metadata",
            dict(self.metadata) if isinstance(self.metadata, Mapping) else {},
        )

    @property
    def available(self) -> bool:
        """``True`` only for a status that can actually produce frames."""
        return self.status in (CameraStatus.LIVE, CameraStatus.SIMULATION)

    @property
    def simulated(self) -> bool:
        """``True`` when this frame came from a simulation, not a camera."""
        return self.status is CameraStatus.SIMULATION

    @property
    def size(self) -> Optional[Tuple[int, int]]:
        """``(width, height)`` when both are known, else ``None``."""
        if self.width is None or self.height is None:
            return None
        return int(self.width), int(self.height)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-friendly metadata **without** the image payload.

        ``has_data`` reports presence, so a client can tell "no frame yet" from
        "frame withheld", while snapshot size stays independent of image size.
        """
        return {
            "timestamp": self.timestamp,
            "source": self.source,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "frame_id": self.frame_id,
            "status": self.status.value,
            "available": self.available,
            "simulated": self.simulated,
            "has_data": self.data is not None,
            "byte_size": len(self.data) if self.data is not None else None,
            "metadata": dict(self.metadata),
        }


@runtime_checkable
class CameraSource(Protocol):
    """Structural interface every camera backend satisfies.

    The lifecycle is explicit so resources have an owner: a source holding a
    device handle must release it in :meth:`stop`. Implementations must be
    safe to call ``start()`` twice and ``stop()`` twice.
    """

    #: Short, stable identity surfaced to the dashboard (never a status).
    name: str

    def start(self) -> None:
        """Acquire the device. Idempotent; must not raise on repeat calls."""

    def read(self) -> CameraFrame:
        """Return one frame. Must not raise: failures become an ERROR frame."""

    def stop(self) -> None:
        """Release the device. Idempotent; safe to call without ``start``."""

    def status(self) -> CameraStatus:
        """Current honest status."""



class RaspberryPiCameraSource:
    """Real Raspberry Pi camera adapter — **NOT_VERIFIED** until hardware is run.

    The module is pure standard library: ``picamera2`` is imported **lazily**
    inside :meth:`start`, so importing :mod:`amr.camera` on a laptop or in CI
    never touches Raspberry Pi software. The resulting state is always honest:

    ==========================  ==========================================
    Situation                   status
    ==========================  ==========================================
    ``picamera2`` + camera OK   :attr:`~CameraStatus.LIVE`
    ``picamera2`` missing       :attr:`~CameraStatus.UNAVAILABLE`
    camera present but failing  :attr:`~CameraStatus.ERROR`
    camera disabled / stopped   :attr:`~CameraStatus.UNAVAILABLE`
    ==========================  ==========================================

    ``picamera2`` is the current Raspberry Pi OS stack (``libcamera-still`` is
    legacy and removed from recent images), so it is tried first; the older
    helper stays as a fallback so an existing Pi image still works.

    Every failure path is contained: :meth:`start` and :meth:`read` never raise
    for a real-world problem, they only record status. That is what keeps a
    missing camera from crashing the AMR runtime.

    :param library: a pre-injected stand-in for the ``picamera2`` module, so the
        live path is testable with no hardware. ``None`` (the default) imports
        the real module lazily.
    :param fallback_command: argv prefix for the legacy one-shot capture, or
        ``None`` to disable the fallback.
    """

    name = "RaspberryPiCamera"

    def __init__(
        self,
        width: int = 1280,
        height: int = 720,
        clock=time.time,
        library: Any = None,
        fallback_command: Optional[Sequence[str]] = ("libcamera-still",),
        start_error: Optional[Exception] = None,
        read_error: Optional[Exception] = None,
        capture_timeout_s: float = 5.0,
    ):
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self._clock = clock
        self._library = library
        self._fallback_command = tuple(fallback_command or ())
        #: Injected failures let the ERROR path be tested deterministically.
        self._start_error = start_error
        self._read_error = read_error
        self._capture_timeout_s = capture_timeout_s
        self._camera: Any = None
        self._running = False
        self._status = CameraStatus.UNAVAILABLE
        self._reason: Optional[str] = None
        self._backend: Optional[str] = None
        self._frame_id = 0
        #: Latest captured frame; retaining exactly one bounds image memory.
        self._last_frame: Optional[CameraFrame] = None

    # -- lifecycle ---------------------------------------------------------- #
    def start(self) -> None:
        """Acquire the camera. Idempotent; never raises for a real failure."""
        if self._running:
            return
        if self._start_error is not None:
            # A present-but-failing camera is ERROR, not a crash: the AMR
            # runtime must keep running with the camera section marked broken.
            self._reason = f"start failed: {self._start_error}"
            self._status = CameraStatus.ERROR
            self._running = False
            return
        library = self._load_library()
        if library is not None:
            self._open_picamera2(library)
            if self._running:
                return
        if self._fallback_command and shutil.which(self._fallback_command[0]):
            # A one-shot CLI has no persistent handle: it is "running" whenever
            # the binary exists, and each read shells out for a single frame.
            self._running = True
            self._status = CameraStatus.LIVE
            self._backend = "libcamera-still"
            self._reason = None
            return
        if not self._reason:
            self._reason = (
                f"neither picamera2 nor {self._fallback_command[0] or 'the fallback'}"
                " is available"
            )
        self._status = CameraStatus.UNAVAILABLE
        self._running = False

    def stop(self) -> None:
        """Release the device handle. Idempotent; never raises."""
        camera, self._camera = self._camera, None
        self._running = False
        self._status = CameraStatus.UNAVAILABLE
        # Drop the retained frame so a stopped camera holds no image memory.
        self._last_frame = None
        if camera is None:
            return
        for method in ("stop", "close"):
            closer = getattr(camera, method, None)
            if callable(closer):
                try:
                    closer()
                except Exception as exc:  # noqa: BLE001 - teardown is best-effort
                    self._reason = f"{method}() failed: {exc}"
                return

    def status(self) -> CameraStatus:
        return self._status

    @property
    def last_frame(self) -> Optional[CameraFrame]:
        """Most recent frame, or ``None``. Reading it never captures."""
        return self._last_frame

    def read(self) -> CameraFrame:
        """Capture one frame. Never raises: failure yields an ERROR frame."""
        if not self._running:
            return CameraFrame(
                source=self.name,
                status=CameraStatus.UNAVAILABLE,
                metadata={"reason": self._reason or "camera not started",
                          "backend": self._backend},
            )
        try:
            data, width, height, fmt = self._capture()
        except Exception as exc:  # noqa: BLE001 - a camera fault is data, not a crash
            self._status = CameraStatus.ERROR
            self._reason = f"capture failed: {exc}"
            return CameraFrame(
                source=self.name,
                status=CameraStatus.ERROR,
                metadata={"reason": self._reason, "backend": self._backend},
            )
        self._status = CameraStatus.LIVE
        self._frame_id += 1
        frame = CameraFrame(
            timestamp=float(self._clock()),
            source=self.name,
            width=width,
            height=height,
            format=fmt,
            frame_id=self._frame_id,
            data=data,
            status=CameraStatus.LIVE,
            metadata={"backend": self._backend, "simulated": False},
        )
        # Retain only the latest frame (bounded memory; no frame history).
        self._last_frame = frame
        return frame

    def describe(self) -> Dict[str, Any]:
        """Status metadata for telemetry — no image bytes, ever."""
        return {
            "name": self.name,
            "status": self._status.value,
            "running": self._running,
            "backend": self._backend,
            "reason": self._reason,
            "frame_id": self._frame_id,
            "simulated": False,
        }

    # -- internals ---------------------------------------------------------- #
    def _load_library(self) -> Any:
        """Import ``picamera2`` on demand; ``None`` when it is not installed."""
        if self._library is not None:
            return self._library
        try:
            from picamera2 import Picamera2  # noqa: PLC0415 - lazy on purpose
        except Exception as exc:  # noqa: BLE001 - missing SDK is not fatal
            self._reason = f"picamera2 unavailable: {exc}"
            return None
        self._library = Picamera2
        return self._library

    def _open_picamera2(self, library: Any) -> None:
        """Acquire the device through the modern Pi stack, if it is usable."""
        try:
            camera = library()
            camera.configure(
                main={"size": (self.width, self.height), "format": "RGB888"}
            )
            camera.start()
        except Exception as exc:  # noqa: BLE001 - no camera / bad config
            self._reason = f"picamera2 could not start: {exc}"
            closer = getattr(library, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:  # noqa: BLE001 - best-effort cleanup
                    pass
            return
        self._camera = camera
        self._running = True
        self._status = CameraStatus.LIVE
        self._backend = "picamera2"
        self._reason = None

    def _capture(self) -> Tuple[bytes, Optional[int], Optional[int], Optional[str]]:
        """Grab encoded bytes from whichever backend is currently active."""
        if self._backend == "picamera2" and self._camera is not None:
            array = self._camera.capture_array()
            # picamera2 hands back a raw RGB ndarray; encode it losslessly so
            # the frame stays a self-describing transport envelope.
            png = self._array_to_png(array)
            return png, self.width, self.height, "png"
        if self._fallback_command:
            out = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [*self._fallback_command, "--encoding=jpeg", "-"],
                capture_output=True, timeout=self._capture_timeout_s,
            )
            if out.returncode != 0 or not out.stdout:
                raise RuntimeError(
                    (out.stderr or b"capture failed").decode(errors="replace")
                    .strip() or "libcamera-still failed"
                )
            return out.stdout, self.width, self.height, "jpeg"
        raise RuntimeError(self._reason or "no capture backend")

    @staticmethod
    def _array_to_png(array: Any) -> bytes:
        """Encode an RGB ndarray-shaped object as a PNG, stdlib only.

        Kept dependency-free and deliberately minimal: it reads the buffer
        through the buffer protocol instead of importing NumPy, so the camera
        path does not add a third-party import to the runtime.
        """
        raw = bytes(memoryview(array).cast("B"))
        height, width, channels = array.shape[0], array.shape[1], array.shape[2]
        if channels != 3:
            raise ValueError(f"expected 3-channel RGB, got {channels}")
        stride = width * 3
        scanlines = b"".join(
            b"\x00" + raw[y * stride:(y + 1) * stride] for y in range(height)
        )
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n"
                + _png_chunk(b"IHDR", ihdr)
                + _png_chunk(b"IDAT", zlib.compress(scanlines, 6))
                + _png_chunk(b"IEND", b""))


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    """One PNG chunk: length, type, data, CRC32 (RFC 2083)."""
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def solid_png(width: int, height: int, rgb: Tuple[int, int, int]) -> bytes:
    """Build a real, valid PNG of a solid colour — pure standard library.

    The output is a genuine image at the advertised size (not a 1x1 stand-in
    advertised as 1280x720), so a dashboard preview and a decoder test both
    get something meaningful, and it costs no third-party dependency.
    """
    width, height = max(1, int(width)), max(1, int(height))
    red, green, blue = (max(0, min(255, int(c))) for c in rgb)
    # Each scanline is prefixed with filter byte 0 (None).
    raw = b"".join(
        b"\x00" + bytes((red, green, blue)) * width for _ in range(height)
    )
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(raw, 6))
            + _png_chunk(b"IEND", b""))


class SimulatedCameraSource:
    """Deterministic in-process camera stand-in (C8) — **not** a camera.

    Produces real PNG frames of the configured size, so the dashboard preview
    shows the advertised dimensions and ``frame_id`` is meaningful, while the
    output stays byte-for-byte reproducible for a given ``frame_id``/size. It
    requires no hardware, no OpenCV and no network.

    It reports :attr:`~CameraStatus.SIMULATION` — the dashboard must never
    present these pixels as Raspberry Pi footage.
    """

    #: Distinct identity from any real backend, so logs are unambiguous.
    name = "SimulatedCamera"

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        clock=time.time,
        start_error: Optional[Exception] = None,
    ):
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self._clock = clock
        #: Injected failure used to exercise the ERROR path deterministically.
        self._start_error = start_error
        self._reason: Optional[str] = None
        self._running = False
        self._frame_id = 0
        self.start_count = 0
        self.stop_count = 0
        #: Latest captured frame (metadata only is ever serialised). Retaining
        #: exactly one keeps memory bounded on a Raspberry Pi.
        self._last_frame: Optional[CameraFrame] = None

    def start(self) -> None:
        if self._start_error is not None:
            # Contained like the real backend: a broken camera is reported as
            # such, never allowed to take the AMR runtime down with it.
            self._reason = f"start failed: {self._start_error}"
            self._running = False
            return
        self._running = True
        self.start_count += 1

    def read(self) -> CameraFrame:
        if not self._running:
            return CameraFrame(
                source=self.name, status=CameraStatus.SIMULATION,
                width=self.width, height=self.height, format="png",
                metadata={"reason": self._reason or "not started"},
            )
        self._frame_id += 1
        # Hue rotates per frame so consecutive previews are visually distinct,
        # but deterministically: no RNG, no wall-clock dependence.
        shade = (self._frame_id * 7) % 256
        frame = CameraFrame(
            timestamp=float(self._clock()),
            source=self.name,
            width=self.width,
            height=self.height,
            format="png",
            frame_id=self._frame_id,
            data=solid_png(self.width, self.height, (shade, 64, 128)),
            status=CameraStatus.SIMULATION,
            metadata={"simulated": True,
                      "note": "generated placeholder, not a camera"},
        )
        # Retain only the latest frame: telemetry and the dashboard can report
        # real metadata without re-capturing, and no history accumulates.
        self._last_frame = frame
        return frame

    def stop(self) -> None:
        self._running = False
        self.stop_count += 1
        # Release the retained frame's image memory.
        self._last_frame = None

    @property
    def last_frame(self) -> Optional[CameraFrame]:
        """Most recent frame, or ``None``. Reading it never captures."""
        return self._last_frame

    def status(self) -> CameraStatus:
        # A configured simulated source is always SIMULATION: reporting
        # UNAVAILABLE while stopped would hide the fact that simulation was
        # deliberately selected. Only a genuine start failure is an ERROR.
        if self._start_error is not None:
            return CameraStatus.ERROR
        return CameraStatus.SIMULATION

    def describe(self) -> Dict[str, Any]:
        """Status metadata for telemetry — no image bytes, ever."""
        return {
            "name": self.name,
            "status": self.status().value,
            "running": self._running,
            "backend": "simulated",
            "reason": self._reason,
            "frame_id": self._frame_id,
            "width": self.width,
            "height": self.height,
            "format": "png",
            "simulated": True,
        }


class UnavailableCameraSource:
    """The honest "there is no camera here" source.

    Used as the default so a runtime with no camera still reports a complete,
    well-formed snapshot instead of ``None`` or a fabricated frame.
    """

    name = "UnavailableCamera"

    def __init__(self, reason: str = "no camera configured"):
        self.reason = reason

    def start(self) -> None:
        return None

    def read(self) -> CameraFrame:
        return CameraFrame(
            source=self.name,
            status=CameraStatus.UNAVAILABLE,
            metadata={"reason": self.reason},
        )

    def stop(self) -> None:
        return None

    def status(self) -> CameraStatus:
        return CameraStatus.UNAVAILABLE

    def describe(self) -> Dict[str, Any]:
        """Status metadata for telemetry — no image bytes, ever."""
        return {
            "name": self.name,
            "status": CameraStatus.UNAVAILABLE.value,
            "running": False,
            "backend": None,
            "reason": self.reason,
            "frame_id": 0,
            "width": None,
            "height": None,
            "simulated": False,
        }

