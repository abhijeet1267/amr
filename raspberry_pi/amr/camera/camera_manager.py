"""Camera / vision access (Phase 11).

Camera cable compatibility is **NOT yet confirmed** (see
``config/robot.yaml``). The design rule is: *everything must keep working
with the camera unavailable*. This module therefore:

* wraps any backend that implements ``is_available()`` / ``capture()``;
* treats every camera failure as "unavailable right now", never as a crash;
* keeps mock mode fully dependency-free (:class:`MockCamera`).

The real :class:`PiCameraBackend` prefers ``libcamera-still`` (Raspberry Pi)
and falls back to OpenCV for V4L2 devices (lazy import). It is marked
NOT_VERIFIED until tested against the actual camera.

Vision *algorithms* (marker detection, docking, etc.) are a later phase and
will consume frames from :meth:`CameraManager.capture`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Optional, Protocol, runtime_checkable

from ..logging import get_logger
from ..utils.config import CameraConfig


class CameraError(Exception):
    """Raised for hard camera misconfiguration (not for transient failure)."""


#: Backend class names that produce stand-in frames rather than real footage.
#: Anything listed here is reported as ``SIMULATION`` and never as ``LIVE``.
#: Matched by class name so this module keeps no import-time dependency on
#: :mod:`amr.mocks` (and cannot create a circular import).
_SIMULATED_BACKENDS = frozenset({"MockCamera", "SimulatedCameraSource"})


@runtime_checkable
class CameraBackend(Protocol):
    """Structural interface for camera backends (Mock + Pi both fit)."""

    def is_available(self) -> bool:
        ...

    def capture(self) -> Optional[object]:
        """Return a frame, or ``None`` when nothing could be captured."""
        ...


class PiCameraBackend:
    """Real Pi camera backend. **NOT_VERIFIED** — degrades gracefully.

    * ``device: "pi"``    — one-shot ``libcamera-still`` JPEG (stdout).
    * ``device: "v4l2"``  — OpenCV (lazy import) on ``/dev/video0``.

    Both paths return JPEG bytes or a NumPy array respectively, or ``None``
    on any failure.
    """

    def __init__(self, config: CameraConfig):
        self._config = config
        self.log = get_logger("camera")

    # -- pi (libcamera) ---------------------------------------------------- #
    def _libcamera_available(self) -> bool:
        return shutil.which("libcamera-still") is not None

    def _libcamera_capture(self) -> Optional[bytes]:
        w, h = self._parse_resolution()
        cmd = [
            "libcamera-still",
            "-t", "200",          # 200 ms exposure: fast snapshot
            "-w", str(w),
            "-h", str(h),
            "--nopreview",
            "-o", "-",            # JPEG to stdout
        ]
        try:
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.log.warning("libcamera capture failed: %s", exc)
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout or None

    # -- v4l2 (OpenCV, lazy) ------------------------------------------------ #
    def _v4l2_available(self) -> bool:
        if not os.path.exists("/dev/video0"):
            return False
        try:
            import cv2  # noqa: F401  (lazy, optional dependency)

            return True
        except ImportError:
            return False

    def _v4l2_capture(self) -> Optional[object]:
        try:
            import cv2
        except ImportError:
            return None
        cap = cv2.VideoCapture(0)
        try:
            ok, frame = cap.read()
            return frame if ok else None
        finally:
            cap.release()

    # -- helpers ------------------------------------------------------------- #
    def _parse_resolution(self) -> tuple:
        try:
            w, h = self._config.resolution.lower().split("x")
            return int(w), int(h)
        except (ValueError, AttributeError):
            return 1280, 720

    # -- protocol -------------------------------------------------------------- #
    def is_available(self) -> bool:
        if self._config.device == "pi":
            return self._libcamera_available()
        if self._config.device == "v4l2":
            return self._v4l2_available()
        self.log.warning("unknown camera device type: %s", self._config.device)
        return False

    def capture(self) -> Optional[object]:
        if self._config.device == "pi":
            return self._libcamera_capture()
        if self._config.device == "v4l2":
            return self._v4l2_capture()
        return None


class CameraManager:
    """Camera facade used by the web UI and later vision stages.

    ``capture()`` returns ``None`` (never raises) when the camera is disabled
    or unavailable — callers must code for that.
    """

    def __init__(self, backend: CameraBackend, config: CameraConfig):
        self._backend = backend
        self._config = config
        self.log = get_logger("camera")

    @classmethod
    def create_real(cls, config: CameraConfig) -> "CameraManager":
        return cls(PiCameraBackend(config), config)

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def is_available(self) -> bool:
        """``True`` only when enabled AND the backend reports a device."""
        if not self.enabled:
            return False
        try:
            return bool(self._backend.is_available())
        except Exception as exc:  # noqa: BLE001 - camera must never crash the app
            self.log.warning("camera is_available failed: %s", exc)
            return False

    def capture(self) -> Optional[object]:
        """One frame, or ``None``. Never raises."""
        if not self.is_available():
            return None
        try:
            return self._backend.capture()
        except Exception as exc:  # noqa: BLE001
            self.log.warning("camera capture failed: %s", exc)
            return None

    def capture_jpeg(self) -> Optional[bytes]:
        """One frame normalised to JPEG bytes, or ``None``. Never raises.

        * ``libcamera`` (``device: "pi"``) and :class:`MockCamera` already
          produce JPEG bytes — returned as-is.
        * V4L2 (OpenCV) frames are encoded with ``cv2.imencode`` (lazy).
        * Any other frame type or failure degrades to ``None``.
        """
        frame = self.capture()
        if frame is None:
            return None
        if isinstance(frame, (bytes, bytearray)):
            return bytes(frame)
        try:
            import cv2  # noqa: F401  (lazy, optional dependency)
        except ImportError:
            self.log.warning(
                "camera frame is not JPEG and cv2 is unavailable; "
                "cannot encode"
            )
            return None
        try:
            ok, buf = cv2.imencode(".jpg", frame)
            return bytes(buf.tobytes()) if ok else None
        except Exception as exc:  # noqa: BLE001
            self.log.warning("JPEG encoding failed: %s", exc)
            return None

    def describe(self) -> dict:
        """JSON-friendly status for the web UI.

        Also publishes the C8 camera keys (``status``/``simulated``/``name``)
        so the telemetry collector and dashboard can label the camera honestly.
        A :class:`~amr.mocks.MockCamera` backend is reported as ``SIMULATION``,
        never ``LIVE`` — a stand-in frame must not look like camera hardware.
        """
        available = self.is_available()
        simulated = type(self._backend).__name__ in _SIMULATED_BACKENDS
        if not available:
            status = "UNAVAILABLE"
        else:
            status = "SIMULATION" if simulated else "LIVE"
        return {
            "enabled": self.enabled,
            "available": available,
            "device": self._config.device,
            "resolution": self._config.resolution,
            "status": status,
            "simulated": simulated,
            "name": type(self._backend).__name__,
            # Retained for the pre-C8 web UI, which only ever read `available`.
            "hardware_verified": available and not simulated,
        }
