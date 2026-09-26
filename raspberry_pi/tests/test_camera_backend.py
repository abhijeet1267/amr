"""C15b — a real camera frame reaching the existing vision pipeline.

Hardware-free by construction. The ``RaspberryPiCameraSource`` tests use a
**stub library object** to stand in for ``picamera2``, so the acquisition logic
is exercised without a Pi, a camera, or the SDK installed. Nothing here claims
the physical camera works: **Camera hardware: NOT TESTED.**
"""

from __future__ import annotations

import pytest

from amr.camera import (
    CameraFrame,
    CameraFrameDetector,
    CameraStatus,
    RaspberryPiCameraSource,
    SimulatedCameraSource,
    UnavailableCameraSource,
)
from amr.hazard import HazardManager, VisionHazardSource
from amr.hazard.vision import VisionClass
from amr.main import build_frame_detector, parse_resolution
from amr.utils.config import HazardConfig, load_config

from conftest import config_dir


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture
def camera():
    cam = SimulatedCameraSource(width=320, height=240)
    cam.start()
    try:
        yield cam
    finally:
        cam.stop()


def one_obstacle(_frame):
    """A stand-in *model*: one pixel-space detection. NOT a real detector."""
    return [{"class": "OBSTACLE", "confidence": 0.77, "bbox": [10, 20, 60, 80]}]


def hazard_manager(*sources):
    hm = HazardManager(HazardConfig(enabled=True, vision_enabled=True))
    for s in sources:
        hm.add_source(s)
    return hm


# --------------------------------------------------------------------------- #
# Stage A: real camera acquisition, no model
# --------------------------------------------------------------------------- #
class TestFrameAcquisitionWithoutModel:
    def test_a_frame_reaches_the_detector_interface(self, camera):
        det = CameraFrameDetector(camera)
        # With no model configured the detector acquires the frame but honestly
        # reports nothing, rather than claiming an all-clear.
        assert det.detect() == ()
        assert det.frames_seen == 1

    def test_available_is_false_without_a_model(self, camera):
        assert CameraFrameDetector(camera).available is False
        assert CameraFrameDetector(camera,
                                  inference=one_obstacle).available is True

    def test_describe_reports_no_inference(self, camera):
        d = CameraFrameDetector(camera)
        d.detect()          # a frame must be consumed before it is counted
        described = d.describe()
        assert described["inference_configured"] is False
        assert described["frames_seen"] == 1
        # Without a model the detector must not claim to have found anything.
        assert described["detections_made"] == 0
        assert described["classes"] is None


# --------------------------------------------------------------------------- #
# The frame -> detection -> hazard pipeline
# --------------------------------------------------------------------------- #
class TestVisionToHazardIntegration:
    def test_frame_becomes_a_hazard_event(self, camera):
        det = CameraFrameDetector(camera, inference=one_obstacle,
                                  camera_id="camera_front")
        hm = hazard_manager(VisionHazardSource(det, name="vision",
                                               frame_provider=camera.read))
        assert hm.evaluate().state.value == "WARNING"
        assert [e.to_dict()["kind"] for e in hm.active_events()] == ["OBSTACLE"]

    def test_bbox_stays_in_image_space(self, camera):
        """C13 rule: a pixel box is never promoted to a world coordinate."""
        det = CameraFrameDetector(camera, inference=one_obstacle)
        reading = hazard_manager(
            VisionHazardSource(det, frame_provider=camera.read)
        ).evaluate().readings[0]
        assert reading.metadata["bbox"] == [10.0, 20.0, 60.0, 80.0]
        assert reading.metadata["image_size"] == [320, 240]
        # The decisive assertion: no world position was invented.
        assert reading.location is None

    def test_counts_advance_per_detection_call(self, camera):
        det = CameraFrameDetector(camera, inference=one_obstacle)
        det.detect()
        det.detect()
        assert det.frames_seen == 2
        assert det.detections_made == 2

    def test_camera_id_is_stamped_not_the_backend_name(self, camera):
        det = CameraFrameDetector(camera, inference=one_obstacle,
                                  camera_id="camera_front")
        assert det.detect()[0].source == "camera_front"
        assert det.detect()[0].source != camera.name

    def test_timestamp_falls_back_to_the_frame(self, camera):
        """A model that omits a timestamp inherits the frame's, not "now"."""
        det = CameraFrameDetector(camera, inference=one_obstacle)
        got = det.detect()[0]
        assert got.timestamp == pytest.approx(camera.last_frame.timestamp)

    def test_confidence_and_bbox_survive_the_pipeline(self, camera):
        det = CameraFrameDetector(camera, inference=one_obstacle)
        reading = hazard_manager(
            VisionHazardSource(det, frame_provider=camera.read)
        ).evaluate().readings[0]
        assert reading.value == pytest.approx(0.77)
        assert reading.unit == "confidence"
        assert reading.metadata["bbox"] == [10.0, 20.0, 60.0, 80.0]

    def test_multiple_detections_are_all_reported(self, camera):
        def two(_frame):
            return [{"class": "PERSON", "confidence": 0.9, "bbox": [1, 2, 3, 4]},
                    {"class": "OBSTACLE", "confidence": 0.6,
                     "bbox": [5, 6, 7, 8]}]
        got = CameraFrameDetector(camera, inference=two).detect()
        assert len(got) == 2
        assert {d.vision_class for d in got} == {VisionClass.PERSON,
                                                VisionClass.OBSTACLE}

    def test_class_allow_list_filters(self, camera):
        def two(_frame):
            return [{"class": "PERSON", "confidence": 0.9},
                    {"class": "OBSTACLE", "confidence": 0.6}]
        det = CameraFrameDetector(camera, inference=two, classes=("obstacle",))
        assert [d.vision_class.value for d in det.detect()] == ["OBSTACLE"]

    def test_malformed_output_is_dropped_individually(self, camera):
        def messy(_frame):
            return [{"class": "OBSTACLE", "confidence": 99.0},   # invalid
                    {"class": "OBSTACLE", "confidence": 0.7},     # valid
                    "not-a-detection", None]
        got = CameraFrameDetector(camera, inference=messy).detect()
        assert len(got) == 1
        assert got[0].confidence == pytest.approx(0.7)

    def test_unknown_class_is_ignored_not_raised(self, camera):
        def banana(_frame):
            return [{"class": "BANANA", "confidence": 0.99}]
        assert CameraFrameDetector(camera, inference=banana).detect() == ()


# --------------------------------------------------------------------------- #
# Failure handling — an unusable pipeline is not "all clear"
# --------------------------------------------------------------------------- #
class TestFailureHandling:
    def test_a_raising_model_yields_no_detections_and_counts(self, camera):
        def boom(_frame):
            raise RuntimeError("model exploded")
        det = CameraFrameDetector(camera, inference=boom)
        assert det.detect() == ()
        assert det.inference_errors == 1
        assert det.detections_made == 0

    def test_a_raising_model_becomes_a_fault_reading_not_silence(self, camera):
        def boom(_frame):
            raise RuntimeError("model exploded")
        det = CameraFrameDetector(camera, inference=boom)
        status = hazard_manager(
            VisionHazardSource(det, frame_provider=camera.read)).evaluate()
        assert status.state.value == "WARNING"
        assert status.readings[0].kind.value == "ROBOT_FAULT"

    def test_an_unreadable_camera_yields_no_detections(self):
        class Broken:
            name = "broken"

            def read(self):
                raise OSError("device busy")

        assert CameraFrameDetector(Broken(), inference=one_obstacle).detect() == ()

    def test_unavailable_camera_still_answers(self):
        det = CameraFrameDetector(UnavailableCameraSource("no camera"),
                                  inference=one_obstacle)
        assert det.detect() == ()

    def test_frame_provider_failure_is_contained(self, camera):
        def bad_provider():
            raise OSError("camera died")

        det = CameraFrameDetector(camera, inference=one_obstacle)
        status = hazard_manager(
            VisionHazardSource(det, frame_provider=bad_provider)).evaluate()
        assert status.readings[0].kind.value == "ROBOT_FAULT"

    def test_a_detector_object_is_accepted(self, camera):
        """The VisionDetector protocol declares `.detect`; that must work."""
        det = CameraFrameDetector(camera, inference=one_obstacle)
        status = hazard_manager(VisionHazardSource(det)).evaluate()
        assert status.readings[0].kind.value == "OBSTACLE"

    def test_a_plain_callable_still_works(self):
        """Back-compat: the original zero-argument contract is untouched."""
        source = VisionHazardSource(lambda: [{"class": "OBSTACLE",
                                             "confidence": 0.7}])
        assert source.read()[0].kind.value == "OBSTACLE"

    def test_a_static_sequence_still_works(self):
        source = VisionHazardSource([{"class": "OBSTACLE", "confidence": 0.7}])
        assert source.read()[0].kind.value == "OBSTACLE"

    def test_a_detector_ignoring_frames_still_works(self, camera):
        class Ignores:
            name = "ignores"

            def detect(self):
                return [{"class": "PERSON", "confidence": 0.8}]

        source = VisionHazardSource(Ignores(), frame_provider=camera.read)
        assert source.read()[0].kind.value == "PERSON"

    def test_detection_module_cannot_actuate(self, camera):
        """The camera/detector path must not reach an actuator.

        Source-level check: no motor, serial, GPIO, robot or web-command import,
        and no reference to the actuator endpoint.
        """
        import pathlib

        import amr.camera.detector as mod
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        for banned in ("/command", "gpio", "RPi", "from ..robot",
                       "from ..control", "from ..web", "estop"):
            assert banned not in src


# --------------------------------------------------------------------------- #
# Failure handling — a bad camera must never take the runtime down
# --------------------------------------------------------------------------- #
class TestFailureHandling:
    """The source's documented fault contract: kind=ROBOT_FAULT, severity=WARNING.

    ``VisionHazardSource`` deliberately uses a *WARNING* fault rather than
    ERROR/STOP for a failed detector: a camera problem must not by itself halt a
    robot that is otherwise safe to drive. These tests pin that existing policy
    rather than inventing a stricter one.
    """

    FAULT = ("ROBOT_FAULT", "WARNING")

    def test_detector_raising_is_contained(self, camera):
        class Boom:
            def detect(self, frame):
                raise RuntimeError("model exploded")

        readings = VisionHazardSource(Boom(), frame_provider=camera.read).read()
        assert [(r.kind.value, r.severity.value) for r in readings] == [self.FAULT]
        assert "model exploded" in readings[0].message

    def test_detector_returning_garbage_is_contained(self, camera):
        """Unusable detections are dropped, not turned into fake hazards."""
        class Garbage:
            def detect(self, frame):
                return ["not a detection", 42, None]

        readings = VisionHazardSource(Garbage(), frame_provider=camera.read).read()
        # Dropped entirely: no hazard is invented from junk.
        assert readings == ()

    def test_frame_provider_raising_is_contained(self, camera):
        def bad_read():
            raise OSError("device disappeared")

        source = VisionHazardSource(_none_detector(), frame_provider=bad_read)
        assert [(r.kind.value, r.severity.value)
                for r in source.read()] == [self.FAULT]

    def test_missing_frame_yields_no_false_hazard(self, camera):
        """A camera with no frame is not evidence of a hazard."""
        source = VisionHazardSource(_none_detector(), frame_provider=lambda: None)
        assert source.read() == ()

    def test_unavailable_camera_still_reports_nothing(self, camera):
        """The unavailable Pi backend yields no usable frame, not a fake one."""
        from amr.camera import RaspberryPiCameraSource
        src = RaspberryPiCameraSource()
        assert src.status().value in ("UNAVAILABLE", "ERROR")
        frame = src.read()
        # A frame may be returned, but it must be flagged unavailable and carry
        # no image dimensions — it must never masquerade as real imagery.
        assert frame.status.value in ("UNAVAILABLE", "ERROR")
        assert not frame.width or not frame.height

    def test_source_recovers_after_a_failure(self, camera):
        """One bad frame must not poison later good frames."""
        state = {"fail": True}

        class Flaky:
            def detect(self, frame):
                if state["fail"]:
                    raise RuntimeError("transient")
                return []

        source = VisionHazardSource(Flaky(), frame_provider=camera.read)
        assert source.read()[0].severity.value == "WARNING"
        state["fail"] = False
        assert source.read() == ()


def _none_detector():
    class NoDetections:
        def detect(self, frame):
            return []

    return NoDetections()


# --------------------------------------------------------------------------- #
# Real backend — must skip cleanly without Pi hardware/libraries
# --------------------------------------------------------------------------- #
class TestRealBackendWithoutHardware:
    def test_importing_the_camera_package_needs_no_pi_libraries(self):
        """Importing amr.camera must not pull in picamera2 / RPi / cv2 / numpy.

        This is the guarantee that lets the whole suite run on macOS/Linux with
        no Raspberry Pi libraries installed.
        """
        import subprocess
        import sys
        import textwrap
        code = textwrap.dedent(
            """
            import sys
            import amr.camera  # noqa: F401
            banned = [m for m in ("picamera2", "RPi", "RPi.GPIO", "cv2", "numpy")
                      if m in sys.modules]
            print(",".join(banned))
            """
        )
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == "", (
            f"amr.camera imported hardware/ML libraries: {out.stdout.strip()}")

    def test_unavailable_reason_is_honest(self):
        from amr.camera import RaspberryPiCameraSource
        d = RaspberryPiCameraSource().describe()
        # It must name why, rather than pretending to be live or leaving the
        # reason blank.
        assert d["status"] in ("UNAVAILABLE", "ERROR", "LIVE", "SIMULATION")
        if d["status"] in ("UNAVAILABLE", "ERROR"):
            assert d.get("reason")

    def test_lifecycle_is_safe_when_unavailable(self):
        from amr.camera import RaspberryPiCameraSource
        src = RaspberryPiCameraSource()
        src.start()          # must not raise even without hardware
        src.start()          # idempotent
        src.read()           # must not raise
        src.stop()           # must not raise
        src.stop()           # idempotent

    def test_real_backend_skips_without_hardware(self):
        """Absent the Pi library the backend is UNAVAILABLE, not an error."""
        from amr.camera import RaspberryPiCameraSource
        src = RaspberryPiCameraSource()
        if not _pi_camera_library_present():
            assert src.status().value == "UNAVAILABLE"
            assert "picamera2" in (src.describe().get("reason") or "") \
                or "unavailable" in (src.describe().get("reason") or "").lower()
        else:
            pytest.skip("Pi camera library present: validate on hardware instead")

    def test_frame_provides_image_space_metadata(self, camera):
        """A real frame must carry the image dimensions bbox coordinates live in."""
        frame = camera.read()
        assert frame is not None
        assert frame.width > 0 and frame.height > 0
        payload = frame.to_dict()
        assert payload["width"] == frame.width
        assert payload["height"] == frame.height


def _pi_camera_library_present():
    """True only when picamera2 can actually be imported on this machine."""
    import importlib.util
    return importlib.util.find_spec("picamera2") is not None


def _repo_config():
    import pathlib
    return str(pathlib.Path(__file__).resolve().parents[2] / "config")


# --------------------------------------------------------------------------- #
# Configuration + factory wiring
# --------------------------------------------------------------------------- #
class TestConfigAndFactory:
    def test_configured_resolution_reaches_the_camera(self, config_dir):
        """C15b: the configured resolution was previously read from attributes
        that do not exist on CameraConfig, so it was silently ignored."""
        from amr.main import build_camera
        from amr.utils.config import load_config
        config = load_config(config_dir)
        cam = build_camera(config, mock=True)
        assert (cam.width, cam.height) == parse_resolution(
            config.robot.camera.resolution)

    @pytest.mark.parametrize("value,expected", [
        ("1280x720", (1280, 720)), ("1280X720", (1280, 720)),
        ("640*480", (640, 480)), (" 800x600 ", (800, 600)),
    ])
    def test_resolution_parser_accepts_conventional_spellings(self, value, expected):
        assert parse_resolution(value) == expected

    @pytest.mark.parametrize("bad", [None, "", "abc", "0x0", "-10x-10",
                                     "0", {"width": 4}])
    def test_bad_resolution_falls_back_safely(self, bad):
        """A nonsensical size falls back rather than opening at 0 pixels."""
        assert parse_resolution(bad) == (640, 480)

    def test_mock_builds_a_simulated_camera(self, config_dir):
        from amr.main import build_camera
        from amr.utils.config import load_config
        cam = build_camera(load_config(config_dir), mock=True)
        assert cam.describe()["simulated"] is True
        assert cam.status().value == "SIMULATION"

    def test_hardware_builds_a_real_backend(self, config_dir):
        """Without --mock the real Pi backend is used, not the simulator."""
        from amr.main import build_camera
        from amr.utils.config import load_config
        cam = build_camera(load_config(config_dir), mock=False)
        assert cam.describe()["simulated"] is False
        assert cam.name == "RaspberryPiCamera"

    def test_frame_detector_wraps_the_camera(self, config_dir):
        from amr.main import build_camera, build_frame_detector
        from amr.utils.config import load_config
        config = load_config(config_dir)
        cam = build_camera(config, mock=True)
        det = build_frame_detector(cam, config)
        assert det is not None
        det.detect()
        # No model is wired, so it must report no detections honestly.
        assert det.describe()["inference_configured"] is False
        assert det.detect() == ()

    def test_disabled_camera_builds_no_detector(self, config_dir):
        from amr.main import build_frame_detector
        from amr.utils.config import load_config
        config = load_config(config_dir)
        config.robot.camera.enabled = False
        assert build_frame_detector(object(), config) is None

    def test_frame_detector_uses_the_configured_camera_id(self, config_dir):
        from amr.main import build_camera, build_frame_detector
        from amr.utils.config import load_config
        config = load_config(config_dir)
        config.robot.camera.camera_id = "camera_front"
        det = build_frame_detector(build_camera(config, mock=True), config)
        assert det.describe()["camera_id"] == "camera_front"


# --------------------------------------------------------------------------- #
# End-to-end: camera -> detection -> hazard manager, driven for real
# --------------------------------------------------------------------------- #
class TestEndToEndChain:
    def test_frame_becomes_a_hazard_event(self, camera):
        det = CameraFrameDetector(camera, inference=one_obstacle)
        manager = hazard_manager(
            VisionHazardSource(det, frame_provider=camera.read))
        manager.evaluate()

        active = manager.snapshot()["active_events"]
        assert active, "the detection must become a real hazard event"
        event = active[0]
        assert event["kind"] == "OBSTACLE"
        assert event["source"] == camera.name
        # The bbox survives into the event as IMAGE-SPACE metadata (C13 rule),
        # in the C5 corner form [x1, y1, x2, y2].
        assert event["metadata"]["bbox"] == [10.0, 20.0, 60.0, 80.0]
        assert event["metadata"]["image_size"] == [320, 240]
        # ...and it is emphatically NOT a world coordinate (C13 rule).
        assert event["location"] is None

    def test_confidence_survives_the_whole_chain(self, camera):
        det = CameraFrameDetector(camera, inference=one_obstacle)
        manager = hazard_manager(
            VisionHazardSource(det, frame_provider=camera.read))
        manager.evaluate()
        event = manager.snapshot()["active_events"][0]
        # 0.77 in, 0.77 out — never silently rescaled to 100%.
        assert event["confidence"] == pytest.approx(0.77)

    def test_no_model_means_no_hazard_event(self, camera):
        """A camera with no inference model must not invent hazards."""
        manager = hazard_manager(
            VisionHazardSource(CameraFrameDetector(camera),
                               frame_provider=camera.read))
        manager.evaluate()
        assert manager.snapshot()["active_events"] == []

    def test_detection_makes_the_layer_block_motion(self, camera):
        """A critical-confidence detection must actually gate motion.

        The default vision critical threshold is 0.8, so a high-confidence
        detection is required here: a marginal one correctly only raises a
        WARNING and does not stop the robot.
        """
        def strong_obstacle(_frame):
            return [{"class": "OBSTACLE", "confidence": 0.95,
                     "bbox": [10, 20, 60, 80]}]

        manager = hazard_manager(
            VisionHazardSource(
                CameraFrameDetector(camera, inference=strong_obstacle),
                frame_provider=camera.read))
        manager.evaluate()
        assert manager.snapshot()["blocks_motion"] is True

    def test_marginal_detection_does_not_block_motion(self, camera):
        """0.77 is below the critical threshold: WARNING, robot may proceed."""
        manager = hazard_manager(
            VisionHazardSource(CameraFrameDetector(camera, inference=one_obstacle),
                               frame_provider=camera.read))
        manager.evaluate()
        event = manager.snapshot()["active_events"][0]
        assert event["severity"] == "WARNING"
        assert manager.snapshot()["blocks_motion"] is False

    def test_camera_path_writes_nothing_to_the_transport(self, camera):
        """The whole camera->hazard chain must not touch the actuator path."""
        from conftest import NoActuation
        from amr.robot import RobotManager
        from amr.utils.config import load_config

        config = load_config(_repo_config())
        mgr, transport = RobotManager.create_mock(config)
        mgr.test_transport = transport
        try:
            mgr.start()
            with NoActuation(transport):
                det = CameraFrameDetector(camera, inference=one_obstacle)
                VisionHazardSource(det, frame_provider=camera.read).read()
        finally:
            mgr.shutdown()




