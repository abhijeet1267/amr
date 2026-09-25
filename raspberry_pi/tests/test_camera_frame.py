"""C8 — camera monitoring contract, simulation, and Raspberry Pi adapter.

No test here requires a Raspberry Pi, camera hardware, GPIO, libcamera,
OpenCV, NumPy or ``picamera2``. The hardware adapter is exercised through
injected fakes, and the simulation is deterministic, so the whole file runs in
CI on a laptop.

The invariants under test are the ones that keep the dashboard honest: a
simulated frame is never reported as ``LIVE``, a missing camera reports
``UNAVAILABLE`` rather than crashing the runtime, and a failed capture yields
an ``ERROR`` frame instead of raising into the control loop.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import zlib

import pytest

from amr.camera.frame import (
    CameraFrame,
    CameraSource,
    CameraStatus,
    RaspberryPiCameraSource,
    SimulatedCameraSource,
    UnavailableCameraSource,
)


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
def _png_bytes(width: int = 4, height: int = 3) -> bytes:
    """A tiny, structurally valid PNG used as fake capture output."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class _FakeCamera:
    """Stands in for a ``picamera2.Picamera2`` instance."""

    def __init__(self, width=640, height=480, read_error=None):
        self.width, self.height = width, height
        self._read_error = read_error
        self.started = 0
        self.stopped = 0
        self.configured = {}

    def configure(self, **kwargs):
        self.configured = dict(kwargs)
        return None

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def capture_array(self, **kwargs):
        if self._read_error is not None:
            raise self._read_error
        return b"\x00\x00\x00"

    def capture_file(self, path, **kwargs):
        with open(path, "wb") as handle:
            handle.write(_png_bytes(self.width, self.height))
        return str(path)

    def close(self):
        self.stopped += 1


class _FakeLibrary:
    """Stands in for the lazily imported ``picamera2`` module.

    The adapter does ``from picamera2 import Picamera2`` and calls it, so the
    injected double is the *callable* itself, not a module.
    """

    def __init__(self, devices=("cam0",), raises=None, read_error=None):
        self._devices = tuple(devices)
        self._raises = raises
        self._read_error = read_error
        self.cameras: list = []

    def __call__(self, *args, **kwargs):
        """``library()`` mirrors ``Picamera2()`` from the real ``picamera2``."""
        if self._raises is not None:
            raise self._raises
        if not self._devices:
            raise RuntimeError("no camera detected")
        camera = _FakeCamera(read_error=self._read_error)
        self.cameras.append(camera)
        return camera

    @property
    def start_count(self) -> int:
        return len(self.cameras)

    @property
    def stop_count(self) -> int:
        return sum(camera.stopped for camera in self.cameras)


def _modules_imported_by_camera_frame() -> set:
    """Top-level modules newly imported as a side effect of the camera frame.

    Run in a subprocess so this test cannot be fooled by modules the rest of
    the suite already imported.
    """
    import json
    import subprocess as sp

    code = (
        "import sys, json;"
        "before=set(sys.modules);"
        "import amr.camera.frame;"
        "print(json.dumps(sorted(m.split('.')[0] for m in set(sys.modules)-before)))"
    )
    out = sp.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return set(json.loads(out.stdout))


# --------------------------------------------------------------------------- #
# 1. Camera contract — valid frame, metadata, serialization, optional fields
# --------------------------------------------------------------------------- #
class TestCameraContract:
    def test_minimal_frame_is_valid(self):
        frame = CameraFrame(source="TestCamera")
        assert frame.source == "TestCamera"
        assert frame.status is CameraStatus.UNAVAILABLE
        assert frame.width is None and frame.height is None
        assert frame.data is None
        assert frame.frame_id == 0

    def test_full_frame_carries_every_declared_field(self):
        frame = CameraFrame(
            timestamp=123.5,
            source="RaspberryPiCamera",
            width=1280,
            height=720,
            format="jpeg",
            frame_id=1245,
            data=b"\xff\xd8\xff\xd9",
            status=CameraStatus.LIVE,
            metadata={"backend": "picamera2"},
        )
        assert frame.timestamp == 123.5
        assert frame.size == (1280, 720)
        assert frame.format == "jpeg"
        assert frame.frame_id == 1245
        assert frame.data == b"\xff\xd8\xff\xd9"
        assert frame.available is True
        assert frame.simulated is False
        assert frame.metadata["backend"] == "picamera2"

    def test_frame_is_frozen(self):
        frame = CameraFrame(source="TestCamera")
        with pytest.raises(Exception):
            frame.source = "other"  # type: ignore[misc]

    def test_metadata_defaults_to_an_independent_dict(self):
        a = CameraFrame(source="A")
        b = CameraFrame(source="B")
        a.metadata["k"] = "v"
        assert b.metadata == {}

    def test_serialisation_never_leaks_image_bytes(self):
        frame = CameraFrame(
            source="TestCamera", width=64, height=48, format="png",
            frame_id=7, data=b"\x89PNG" * 500, status=CameraStatus.LIVE,
        )
        payload = frame.to_dict()
        assert b"\x89PNG" not in str(payload).encode()
        assert "data" not in payload
        assert payload["width"] == 64 and payload["height"] == 48
        assert payload["frame_id"] == 7
        assert payload["status"] == "LIVE"

    def test_serialisation_is_json_safe(self):
        import json

        json.dumps(CameraFrame(source="C", metadata={"a": 1}).to_dict())

    @pytest.mark.parametrize("bad", ["not-a-status", "", None, 3])
    def test_unknown_status_degrades_to_unavailable(self, bad):
        frame = CameraFrame(source="C", status=bad)
        assert frame.status is CameraStatus.UNAVAILABLE

    @pytest.mark.parametrize("broken, value", [
        ("width", 0), ("width", -1), ("height", 0), ("height", -1),
    ])
    def test_broken_dimension_is_nulled_but_the_valid_one_survives(self, broken, value):
        # A frame claiming 0x480 or -1x5 is a broken reading, not a measurement.
        # Only the impossible field is nulled, so real information is preserved.
        frame = CameraFrame(
            source="C",
            width=value if broken == "width" else 640,
            height=value if broken == "height" else 480,
        )
        assert getattr(frame, broken) is None
        other = "height" if broken == "width" else "width"
        assert getattr(frame, other) in (480, 640)
        assert frame.size is None  # incomplete geometry -> unknown overall

    def test_metadata_is_copied_not_aliased(self):
        meta = {"backend": "picamera2"}
        frame = CameraFrame(source="C", metadata=meta)
        meta["backend"] = "changed"
        assert frame.metadata["backend"] == "picamera2"

    def test_source_protocol_is_runtime_checkable(self):
        for source in (SimulatedCameraSource(), RaspberryPiCameraSource(),
                       UnavailableCameraSource()):
            assert isinstance(source, CameraSource)


# --------------------------------------------------------------------------- #
# 2. Simulation — deterministic, clearly self-identified, hardware-free
# --------------------------------------------------------------------------- #
class TestSimulatedCamera:
    def test_source_is_simulated_never_live(self):
        cam = SimulatedCameraSource()
        cam.start()
        frame = cam.read()
        assert frame.status is CameraStatus.SIMULATION
        assert frame.simulated is True
        assert cam.status() is CameraStatus.SIMULATION

    def test_source_name_identifies_the_simulation(self):
        cam = SimulatedCameraSource()
        cam.start()
        assert cam.read().source == "SimulatedCamera"
        assert cam.describe()["simulated"] is True

    def test_two_cameras_produce_identical_bytes(self):
        a, b = SimulatedCameraSource(), SimulatedCameraSource()
        a.start(); b.start()
        assert a.read().data == b.read().data

    def test_frame_ids_increment_deterministically(self):
        cam = SimulatedCameraSource()
        cam.start()
        assert [cam.read().frame_id for _ in range(3)] == [1, 2, 3]

    def test_a_fresh_camera_repeats_the_same_sequence(self):
        a = SimulatedCameraSource()
        a.start()
        first = [a.read().data for _ in range(3)]
        b = SimulatedCameraSource()
        b.start()
        assert [b.read().data for _ in range(3)] == first

    def test_data_is_a_real_png_of_the_advertised_size(self):
        cam = SimulatedCameraSource(width=32, height=24)
        cam.start()
        data = cam.read().data
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        # IHDR carries the true dimensions; telemetry must match the pixels.
        w, h = struct.unpack(">II", data[16:24])
        assert (w, h) == (32, 24)

    def test_png_chunk_crcs_are_valid(self):
        cam = SimulatedCameraSource(width=16, height=16)
        cam.start()
        data = cam.read().data
        pos, seen = 8, 0
        while pos < len(data):
            length = struct.unpack(">I", data[pos:pos + 4])[0]
            tag = data[pos + 4:pos + 8]
            body = data[pos + 8:pos + 8 + length]
            crc = struct.unpack(
                ">I", data[pos + 8 + length:pos + 12 + length]
            )[0]
            assert crc == zlib.crc32(tag + body) & 0xFFFFFFFF
            seen += 1
            pos += 12 + length
        assert seen >= 2  # at least IHDR + IDAT

    def test_a_fixed_clock_keeps_timestamps_reproducible(self):
        cam = SimulatedCameraSource(clock=lambda: 100.0)
        cam.start()
        assert cam.read().timestamp == 100.0

    def test_consecutive_frames_are_visually_distinct(self):
        cam = SimulatedCameraSource(width=8, height=8)
        cam.start()
        assert cam.read().data != cam.read().data

    def test_read_before_start_carries_no_pixels(self):
        cam = SimulatedCameraSource()
        frame = cam.read()
        assert frame.data is None
        assert frame.status is CameraStatus.SIMULATION

    def test_describe_reports_the_simulation_not_hardware(self):
        cam = SimulatedCameraSource()
        cam.start()
        cam.read()
        d = cam.describe()
        assert d["backend"] == "simulated"
        assert d["simulated"] is True
        assert d["status"] == "SIMULATION"

    def test_lifecycle_is_idempotent(self):
        cam = SimulatedCameraSource()
        cam.start(); cam.start()
        assert cam.start_count == 2  # explicit calls are recorded
        cam.stop(); cam.stop()
        assert cam.status() is CameraStatus.SIMULATION

    def test_stop_then_start_keeps_working(self):
        cam = SimulatedCameraSource()
        cam.start()
        first = cam.read().frame_id
        cam.stop()
        cam.start()
        assert cam.read().data is not None
        assert first == 1

    def test_an_injected_start_failure_is_reported_as_error(self):
        cam = SimulatedCameraSource(start_error=RuntimeError("boom"))
        cam.start()  # must not raise
        assert cam.status() is CameraStatus.ERROR
        assert "boom" in cam.describe()["reason"]



# --------------------------------------------------------------------------- #
# Hardware adapter -- all of these run with NO Pi, NO camera, NO libcamera
# --------------------------------------------------------------------------- #
class TestRaspberryPiCameraSource:
    def test_missing_library_degrades_to_unavailable(self):
        cam = RaspberryPiCameraSource(library=None, fallback_command=None)
        cam.start()  # must not raise
        assert cam.status() is CameraStatus.UNAVAILABLE
        assert "picamera2" in cam.describe()["reason"].lower()
        # A status-only frame, carrying the reason -- never an exception.
        frame = cam.read()
        assert frame.status is CameraStatus.UNAVAILABLE
        assert frame.data is None
        assert "picamera2" in frame.metadata["reason"]

    def test_absent_hardware_degrades_to_unavailable(self):
        # A library that imports fine but cannot see a camera is UNAVAILABLE,
        # not ERROR: nothing is broken, the robot simply has no camera.
        lib = _FakeLibrary(devices=())
        cam = RaspberryPiCameraSource(library=lib, fallback_command=None)
        cam.start()
        assert cam.status() is CameraStatus.UNAVAILABLE
        assert cam.read().data is None

    def test_initialisation_failure_is_reported_as_error(self):
        cam = RaspberryPiCameraSource(start_error=OSError("i2c bus error"))
        cam.start()
        assert cam.status() is CameraStatus.ERROR
        assert "i2c bus error" in cam.describe()["reason"]

    def test_library_init_failure_is_unavailable_not_error(self):
        # "No camera found" is an absent device, not a broken runtime.
        lib = _FakeLibrary(devices=())
        cam = RaspberryPiCameraSource(library=lib, fallback_command=None)
        cam.start()
        assert cam.status() is not CameraStatus.ERROR

    def test_live_camera_reports_the_pi_identity(self):
        cam = RaspberryPiCameraSource(library=_FakeLibrary(devices=("cam0",)),
                                      fallback_command=None)
        cam.start()
        assert cam.status() is CameraStatus.LIVE
        described = cam.describe()
        assert described["name"] == "RaspberryPiCamera"
        assert described["simulated"] is False
        assert described["backend"] == "picamera2"

    def test_read_failure_degrades_without_crashing_the_runtime(self):
        cam = RaspberryPiCameraSource(
            library=_FakeLibrary(devices=("cam0",), read_error=OSError("eof")),
            fallback_command=None,
        )
        cam.start()
        frame = cam.read()
        assert frame.data is None
        assert frame.status is CameraStatus.ERROR
        assert cam.status() is CameraStatus.ERROR
        assert "eof" in cam.describe()["reason"]

    def test_legacy_fallback_is_used_when_the_binary_exists(self, monkeypatch):
        monkeypatch.setattr(shutil, "which",
                            lambda name: "/usr/bin/libcamera-still")
        cam = RaspberryPiCameraSource(library=None,
                                      fallback_command=("libcamera-still",))
        cam.start()
        # picamera2 is genuinely absent here, so the legacy path must take over.
        assert cam.describe()["backend"] == "libcamera-still"
        assert cam.status() is CameraStatus.LIVE

    def test_stop_is_idempotent_and_releases_the_device(self):
        lib = _FakeLibrary(devices=("cam0",))
        cam = RaspberryPiCameraSource(library=lib, fallback_command=None)
        cam.start()
        cam.stop()
        cam.stop()  # safe to repeat
        assert cam.status() is CameraStatus.UNAVAILABLE
        assert cam.read().data is None

    def test_repeated_start_stop_cycles_release_every_handle(self):
        lib = _FakeLibrary(devices=("cam0",))
        cam = RaspberryPiCameraSource(library=lib, fallback_command=None)
        for _ in range(5):
            cam.start()
            cam.stop()
        # Every acquired device is released: starts == stops, no leak.
        assert lib.start_count == 5
        assert lib.stop_count == 5

    def test_double_start_is_a_no_op(self):
        lib = _FakeLibrary(devices=("cam0",))
        cam = RaspberryPiCameraSource(library=lib, fallback_command=None)
        cam.start()
        cam.start()
        assert lib.start_count == 1

    def test_read_before_start_reports_unavailable(self):
        cam = RaspberryPiCameraSource(library=_FakeLibrary(devices=("cam0",)),
                                      fallback_command=None)
        assert cam.read().status is CameraStatus.UNAVAILABLE
        assert cam.read().data is None

    def test_read_after_stop_reports_unavailable(self):
        cam = RaspberryPiCameraSource(library=_FakeLibrary(devices=("cam0",)),
                                      fallback_command=None)
        cam.start()
        cam.stop()
        assert cam.read().status is CameraStatus.UNAVAILABLE

    def test_simulation_is_never_labelled_live(self):
        # The honesty rule: a simulated source reports SIMULATION, full stop.
        sim = SimulatedCameraSource()
        sim.start()
        assert sim.status() is CameraStatus.SIMULATION
        assert sim.describe()["name"] == "SimulatedCamera"
        assert sim.describe()["simulated"] is True
        assert sim.describe()["status"] != "LIVE"

    def test_simulation_and_real_sources_share_one_interface(self):
        # The dashboard must work with either backend unchanged -- that is the
        # whole point of the abstraction.
        real = RaspberryPiCameraSource(
            library=_FakeLibrary(devices=("cam0",)), fallback_command=None)
        for source in (SimulatedCameraSource(), real):
            assert isinstance(source, CameraSource)
            source.start()
            frame = source.read()
            assert isinstance(frame, CameraFrame)
            assert frame.source in ("SimulatedCamera", "RaspberryPiCamera")
            source.stop()

    def test_importing_the_module_does_not_import_picamera2(self):
        # Lazy import: picamera2 must not be pulled in merely by importing amr.
        assert "picamera2" not in _modules_imported_by_camera_frame()

    def test_no_hardware_modules_are_imported_at_module_import(self):
        names = _modules_imported_by_camera_frame()
        for forbidden in ("picamera2", "RPi", "cv2", "numpy"):
            assert forbidden not in names



# --------------------------------------------------------------------------- #
# 6. Runtime wiring — the factory the CLI actually calls
# --------------------------------------------------------------------------- #
class TestBuildCameraWiring:
    """Guards :func:`amr.main.build_camera`, the real entry point.

    Constructing the sources directly (as most tests here do) does *not* cover
    the factory, which is where a wrong keyword argument can crash
    ``python -m amr.main --web`` while every unit test still passes. These
    tests call the factory exactly as the CLI does.
    """

    def test_mock_mode_builds_a_simulated_source(self, config_dir):
        from amr.main import build_camera
        from amr.utils.config import load_config

        cam = build_camera(load_config(config_dir), mock=True)
        assert isinstance(cam, SimulatedCameraSource)
        assert cam.name == "SimulatedCamera"

    def test_hardware_mode_builds_the_raspberry_pi_adapter(self, config_dir):
        from amr.main import build_camera
        from amr.utils.config import load_config

        cam = build_camera(load_config(config_dir), mock=False)
        assert isinstance(cam, RaspberryPiCameraSource)
        assert cam.name == "RaspberryPiCamera"

    def test_built_source_is_usable_after_start(self, config_dir):
        # The exact lifecycle run_web() performs: start -> read -> stop.
        from amr.main import build_camera
        from amr.utils.config import load_config

        cam = build_camera(load_config(config_dir), mock=True)
        cam.start()
        frame = cam.read()
        cam.stop()
        # A frame captured while started must actually carry pixels, otherwise
        # GET /camera/frame would answer 503 for the whole session.
        assert frame.data is not None
        assert frame.status is CameraStatus.SIMULATION
        assert frame.simulated is True
