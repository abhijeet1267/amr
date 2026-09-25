"""Camera / vision (Phase 11) — see :mod:`amr.camera.camera_manager`.

C8 adds the stable monitoring contract in :mod:`amr.camera.frame`: a frozen
:class:`CameraFrame`, a :class:`CameraStatus` that can never confuse a simulated
frame for a live one, and interchangeable backends
(:class:`SimulatedCameraSource`, :class:`RaspberryPiCameraSource`,
:class:`UnavailableCameraSource`).

The Raspberry Pi backend imports ``picamera2`` lazily, so importing this package
— and running the whole test suite — works on a laptop with no camera software
and no hardware.
"""

from .camera_manager import (
    CameraBackend,
    CameraError,
    CameraManager,
    PiCameraBackend,
)
from .frame import (
    CameraFrame,
    CameraSource,
    CameraStatus,
    RaspberryPiCameraSource,
    SimulatedCameraSource,
    UnavailableCameraSource,
)

__all__ = [
    "CameraBackend",
    "CameraError",
    "CameraManager",
    "PiCameraBackend",
    "CameraFrame",
    "CameraSource",
    "CameraStatus",
    "RaspberryPiCameraSource",
    "SimulatedCameraSource",
    "UnavailableCameraSource",
]
