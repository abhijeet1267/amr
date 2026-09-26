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

# C13: the display-only overlay model. It reuses the C5 VisionBoundingBox, so
# it is imported after .frame to keep the dependency direction obvious.
from .overlay import (
    KIND_COLORS,
    OVERLAY_SCHEMA_VERSION,
    CameraOverlay,
    OverlayBox,
    build_camera_overlay,
)

# C15b: the frame -> detection bridge. Imported last: it depends on both the
# camera contract above and the C5 vision contract.
from .detector import CameraFrameDetector

__all__ = [
    "CameraBackend",
    "CameraError",
    "CameraManager",
    "PiCameraBackend",
    "CameraFrame",
    "CameraFrameDetector",
    "CameraSource",
    "CameraStatus",
    "RaspberryPiCameraSource",
    "SimulatedCameraSource",
    "UnavailableCameraSource",
]
