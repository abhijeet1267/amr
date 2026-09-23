"""Unit tests for the camera / vision manager (Phase 11).

The camera must degrade gracefully in every state: disabled, unavailable
hardware, and backends that raise. No test may require real imaging
hardware or third-party libraries (cv2/numpy tests skip cleanly).
"""

from __future__ import annotations

import importlib.util

import pytest

from amr.camera import CameraManager, PiCameraBackend
from amr.mocks import MockCamera
from amr.utils.config import CameraConfig


class _ExplodingBackend:
    """A backend that raises from every method (simulates a broken camera)."""

    def is_available(self) -> bool:
        raise RuntimeError("boom")

    def capture(self):
        raise RuntimeError("boom")


def test_mock_capture_returns_valid_jpeg():
    cam = CameraManager(MockCamera(), CameraConfig())
    frame = cam.capture()
    assert isinstance(frame, (bytes, bytearray))
    assert bytes(frame)[:2] == b"\xff\xd8"  # JPEG SOI
    assert bytes(frame)[-2:] == b"\xff\xd9"  # JPEG EOI
    assert cam.capture_jpeg() == bytes(frame)


def test_disabled_camera_never_captures():
    cam = CameraManager(MockCamera(), CameraConfig(enabled=False))
    assert cam.enabled is False
    assert cam.is_available() is False
    assert cam.capture() is None
    assert cam.capture_jpeg() is None
    assert cam.describe()["available"] is False


def test_unavailable_backend_degrades_to_none():
    cam = CameraManager(MockCamera(available=False), CameraConfig())
    assert cam.is_available() is False
    assert cam.capture() is None
    assert cam.capture_jpeg() is None


def test_backend_exceptions_never_propagate():
    cam = CameraManager(_ExplodingBackend(), CameraConfig())
    assert cam.is_available() is False
    assert cam.capture() is None
    assert cam.capture_jpeg() is None


def test_describe_reports_config():
    cam = CameraManager(
        MockCamera(), CameraConfig(device="pi", resolution="640x480")
    )
    d = cam.describe()
    assert d["enabled"] is True
    assert d["available"] is True
    assert d["device"] == "pi"
    assert d["resolution"] == "640x480"


def test_pi_backend_unknown_device_unavailable():
    be = PiCameraBackend(CameraConfig(device="not-a-device"))
    assert be.is_available() is False
    assert be.capture() is None


def test_create_real_never_raises_without_camera():
    # Whatever camera hardware (or lack of it) exists on this machine, the
    # real factory + capture path must never raise.
    cam = CameraManager.create_real(CameraConfig(device="pi"))
    frame = cam.capture()
    assert frame is None or isinstance(frame, (bytes, bytearray))


def test_numpy_frame_encoded_when_cv2_available():
    pytest.importorskip("cv2")
    import numpy as np

    class _NpBackend:
        def is_available(self) -> bool:
            return True

        def capture(self):
            return np.full((16, 16, 3), 200, dtype=np.uint8)

    cam = CameraManager(_NpBackend(), CameraConfig())
    jpeg = cam.capture_jpeg()
    assert isinstance(jpeg, bytes)
    assert jpeg[:2] == b"\xff\xd8" and jpeg[-2:] == b"\xff\xd9"


def test_non_jpeg_frame_without_cv2_degrades_to_none():
    np = pytest.importorskip("numpy")
    if importlib.util.find_spec("cv2") is not None:
        pytest.skip("cv2 installed; encoding path covered by the other test")

    class _NpBackend:
        def is_available(self) -> bool:
            return True

        def capture(self):
            return np.zeros((4, 4, 3), dtype=np.uint8)

    cam = CameraManager(_NpBackend(), CameraConfig())
    assert cam.capture() is not None  # the frame itself is fine
    assert cam.capture_jpeg() is None  # but it cannot be encoded
