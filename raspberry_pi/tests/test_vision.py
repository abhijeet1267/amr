"""Tests for the vision -> hazard pipeline (C5, :mod:`amr.hazard.vision`).

Fully offline and deterministic: no camera, no ML runtime, no model weights and
no robot. Every detection here is **simulated input**; the assertions are about
plumbing, validation and policy, never about real-world detection accuracy.

Coverage map:

* ``VisionDetection`` / ``VisionBoundingBox`` — contract, validation, tolerant
  coercion of foreign dict / tuple / duck-typed detector output.
* ``VisionHazardSource`` — translation into the existing ``HazardReading``
  model, confidence survival, multi-camera identity, fail-safe on a raising or
  unavailable detector.
* ``SimulatedVisionDetector`` — all 12 named scenarios, determinism.
* Integration — the existing ``HazardManager`` state machine, the JSONL event
  log, the C3 SVG renderer and the C2 web snapshot.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from amr.hazard import (
    HazardKind,
    HazardManager,
    HazardSeverity,
    HazardState,
    VisionHazardSource,
)
from amr.hazard.event_log import read_events
from amr.hazard.types import HazardLocation
from amr.hazard.vision import (
    SIMULATED_SCENARIOS,
    SimulatedVisionDetector,
    VisionClass,
    VisionDetection,
    make_vision_reading,
    make_vision_readings,
    simulate,
)
from amr.hazard.visualisation import events_from_snapshot, render_map_svg
from amr.utils.config import HazardConfig


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _config(**overrides) -> HazardConfig:
    """Hazard config with the vision path enabled and fixed thresholds."""
    params = {"enabled": True, "vision_enabled": True}
    params.update(overrides)
    return HazardConfig(**params)


def _source(scenario="person", name="vision", **cfg) -> VisionHazardSource:
    """Wire a simulated detector into the production source adapter."""
    detector = SimulatedVisionDetector(scenario)
    warn, crit = _config(**cfg).resolved_vision_thresholds()
    return VisionHazardSource(detector.detect, name=name,
                              warn_at=warn, critical_at=crit)


def _evaluate(scenario="person", name="vision", **cfg):
    """Run a scenario through the real manager; return the status."""
    manager = HazardManager(_config(**cfg))
    manager.add_source(_source(scenario, name, **cfg))
    return manager.evaluate()


# --------------------------------------------------------------------------- #
# Contract: VisionDetection / VisionBoundingBox
# --------------------------------------------------------------------------- #
class TestDetectionContract:
    def test_confidence_is_preserved_exactly(self):
        det = VisionDetection(VisionClass.PERSON, 0.84, source="camera_front")
        assert det.confidence == 0.84
        assert det.to_dict()["confidence"] == 0.84

    @pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), "x", None])
    def test_invalid_confidence_is_rejected(self, bad):
        assert VisionDetection.from_any(
            {"class": "PERSON", "confidence": bad}) is None

    def test_unknown_class_is_rejected_gracefully(self):
        assert VisionDetection.from_any(
            {"class": "BANANA", "confidence": 0.9}) is None

    def test_missing_class_is_rejected(self):
        assert VisionDetection.from_any({"confidence": 0.9}) is None

    def test_nan_timestamp_is_rejected(self):
        assert VisionDetection.from_any(
            {"class": "FIRE", "confidence": 0.9, "timestamp": float("nan")}
        ) is None

    def test_bounding_box_round_trips(self):
        det = VisionDetection.from_any(
            {"class": "PERSON", "confidence": 0.9, "bbox": [1, 2, 30, 40]})
        assert det is not None
        assert det.bbox is not None
        assert (det.bbox.x, det.bbox.y, det.bbox.w, det.bbox.h) == (1, 2, 30, 40)

    @pytest.mark.parametrize("bad", [[10, 20, 0, 40], [-1, 2, 3, 4], [1, 2, 3]])
    def test_invalid_bounding_box_is_rejected(self, bad):
        assert VisionDetection.from_any(
            {"class": "PERSON", "confidence": 0.9, "bbox": bad}) is None

    def test_bbox_is_image_space_not_world_metres(self):
        """A bbox must never be laundered into a warehouse coordinate."""
        det = VisionDetection.from_any(
            {"class": "PERSON", "confidence": 0.9, "bbox": [10, 20, 60, 120]})
        assert det.location is None
        assert det.metadata["bbox"] == [10, 20, 60, 120]

    def test_duck_typed_backend_is_accepted(self):
        class Backend:
            confidence = 0.77
            label = "FIRE"
            source = "camera_top"

        det = VisionDetection.from_any(Backend())
        assert det is not None
        assert det.vision_class is VisionClass.FIRE
        assert det.source == "camera_top"

    def test_tuple_shorthand(self):
        det = VisionDetection.from_any(("PERSON", 0.6))
        assert det is not None and det.confidence == 0.6

    def test_garbage_input_never_raises(self):
        for junk in (None, 42, object(), {"class": {}}, []):
            assert VisionDetection.from_any(junk) is None


# --------------------------------------------------------------------------- #
# TEST 1: empty detection list -> no false hazard
# --------------------------------------------------------------------------- #
class TestEmpty:
    def test_empty_list_produces_no_reading(self):
        assert _source("normal").read() == ()

    def test_none_detections_produce_no_reading(self):
        assert make_vision_readings(None) == ()

    def test_empty_frame_keeps_state_normal(self):
        status = _evaluate("normal")
        assert status.state is HazardState.NORMAL
        assert status.readings == ()
        assert not status.blocks_motion


# --------------------------------------------------------------------------- #
# TEST 2/3/4: person / fire / smoke mapping
# --------------------------------------------------------------------------- #
class TestHazardMapping:
    def test_person_becomes_human_hazard(self):
        readings = _source("person").read()
        assert len(readings) == 1
        assert readings[0].kind is HazardKind.HUMAN
        assert readings[0].value == 0.91
        assert readings[0].unit == "confidence"
        assert readings[0].source == "simulated_camera"

    def test_person_is_not_automatically_emergency(self):
        """Policy decides: HUMAN is critical but only FIRE/GAS/SMOKE latch."""
        status = _evaluate("person")
        assert status.state is HazardState.STOP
        assert status.latched is False

    def test_fire_mapping(self):
        readings = _source("fire").read()
        assert readings[0].kind is HazardKind.FIRE
        assert readings[0].value == 0.93

    def test_fire_is_critical_and_latches_emergency(self):
        status = _evaluate("fire")
        assert status.state is HazardState.EMERGENCY
        assert status.latched is True
        assert status.blocks_motion is True

    def test_smoke_mapping(self):
        readings = _source("smoke").read()
        assert readings[0].kind is HazardKind.SMOKE
        assert readings[0].value == 0.72

    def test_obstacle_mapping(self):
        assert _source("obstacle").read()[0].kind is HazardKind.OBSTACLE

    def test_every_supported_class_maps(self):
        for vision_class, kind in (
            ("PERSON", HazardKind.HUMAN), ("HUMAN", HazardKind.HUMAN),
            ("FIRE", HazardKind.FIRE), ("SMOKE", HazardKind.SMOKE),
            ("OBSTACLE", HazardKind.OBSTACLE),
        ):
            reading = make_vision_reading(
                VisionDetection(VisionClass.parse(vision_class), 0.9))
            assert reading is not None and reading.kind is kind


# --------------------------------------------------------------------------- #
# TEST 5: multiple detections are deterministic
# --------------------------------------------------------------------------- #
class TestMultiple:
    def test_multiple_objects_map_in_stable_order(self):
        readings = _source("multiple_objects").read()
        assert [r.kind for r in readings] == [
            HazardKind.HUMAN, HazardKind.OBSTACLE, HazardKind.SMOKE]

    def test_repeated_calls_are_identical(self):
        detector = SimulatedVisionDetector("multiple_objects")
        first = detector.detect(None)
        second = detector.detect(None)
        assert [d.to_dict() for d in first] == [d.to_dict() for d in second]

    def test_one_bad_detection_does_not_hide_the_good_ones(self):
        readings = make_vision_readings([
            {"class": "PERSON", "confidence": 0.9},
            {"class": "FIRE", "confidence": 99},
            {"class": "SMOKE", "confidence": 0.7},
        ])
        assert [r.kind for r in readings] == [
            HazardKind.HUMAN, HazardKind.SMOKE]


# --------------------------------------------------------------------------- #
# TEST 6: low confidence follows configured policy
# --------------------------------------------------------------------------- #
class TestConfidenceThreshold:
    def test_low_confidence_is_dropped(self):
        assert _source("low_confidence").read() == ()

    def test_low_confidence_keeps_state_normal(self):
        assert _evaluate("low_confidence").state is HazardState.NORMAL

    def test_below_warn_band_yields_nothing(self):
        reading = make_vision_reading(
            VisionDetection(VisionClass.PERSON, 0.49),
            warn_at=0.5, critical_at=0.8)
        assert reading is None

    def test_warn_band_yields_warning(self):
        reading = make_vision_reading(
            VisionDetection(VisionClass.PERSON, 0.6),
            warn_at=0.5, critical_at=0.8)
        assert reading.severity is HazardSeverity.WARNING

    def test_critical_band_yields_critical(self):
        reading = make_vision_reading(
            VisionDetection(VisionClass.PERSON, 0.85),
            warn_at=0.5, critical_at=0.8)
        assert reading.severity is HazardSeverity.CRITICAL

    def test_configured_thresholds_are_honoured(self):
        """A stricter operator config raises the bar."""
        assert _source("low_confidence", vision_warn_at=0.1,
                       vision_critical_at=0.5).read() != ()

    def test_thresholds_fall_back_to_human_when_null(self):
        cfg = _config(vision_warn_at=None, vision_critical_at=None,
                      human_warn_at=0.55, human_critical_at=0.75)
        assert cfg.resolved_vision_thresholds() == (0.55, 0.75)


# --------------------------------------------------------------------------- #
# TEST 7/8: location handling -- never fabricated
# --------------------------------------------------------------------------- #
class TestLocation:
    def test_absent_location_stays_none(self):
        reading = _source("without_location").read()[0]
        assert reading.location is None

    def test_bbox_does_not_become_a_world_location(self):
        reading = _source("without_location").read()[0]
        assert reading.metadata["bbox"] == [10, 20, 60, 120]
        assert reading.location is None

    def test_supplied_location_is_preserved(self):
        reading = _source("with_location").read()[0]
        assert reading.location is not None
        assert reading.location.x == pytest.approx(12.3)
        assert reading.location.y == pytest.approx(4.7)

    def test_location_reaches_the_recorded_event(self):
        manager = HazardManager(_config())
        manager.add_source(_source("with_location"))
        manager.evaluate()
        event = manager.events.history()[0]
        assert event.location.x == pytest.approx(12.3)

    def test_event_location_prefers_hazard_over_robot_pose(self):
        manager = HazardManager(_config())
        manager.add_source(_source("with_location"))
        manager.evaluate(location=HazardLocation(0.0, 0.0))
        event = manager.events.history()[0]
        assert event.location.x == pytest.approx(12.3)

    def test_event_falls_back_to_robot_pose_when_unlocated(self):
        manager = HazardManager(_config())
        manager.add_source(_source("person"))
        manager.evaluate(location=HazardLocation(5.0, 6.0))
        event = manager.events.history()[0]
        assert event.location.x == pytest.approx(5.0)


# --------------------------------------------------------------------------- #
# TEST 10/11: malformed input, unknown class, multiple cameras
# --------------------------------------------------------------------------- #
class TestSourcesAndFailures:
    def test_malformed_scenario_yields_no_readings(self):
        assert _source("malformed").read() == ()

    def test_unknown_class_scenario_yields_no_readings(self):
        assert _source("unknown_class").read() == ()

    def test_multiple_cameras_keep_source_identity(self):
        readings = _source("multiple_cameras").read()
        assert {r.source for r in readings} == {"camera_front", "camera_rear"}
        assert {r.kind for r in readings} == {HazardKind.HUMAN, HazardKind.FIRE}

    def test_detector_exception_becomes_a_fault_reading(self):
        def boom():
            raise RuntimeError("inference crashed")

        readings = VisionHazardSource(boom, name="camera_front").read()
        assert len(readings) == 1
        assert "inference crashed" in readings[0].message

    def test_detector_exception_never_escapes_the_manager(self):
        def boom():
            raise RuntimeError("inference crashed")

        manager = HazardManager(_config())
        manager.add_source(VisionHazardSource(boom, name="camera_front"))
        status = manager.evaluate()
        # A dead detector degrades to a fault warning, not a crash.
        assert any(r.kind is HazardKind.ROBOT_FAULT for r in status.readings)
        assert status.blocks_motion is False

    def test_a_live_detector_survives_next_to_a_dead_one(self):
        def boom():
            raise RuntimeError("inference crashed")

        manager = HazardManager(_config())
        manager.add_source(VisionHazardSource(boom, name="camera_rear"))
        manager.add_source(_source("fire", name="camera_front"))
        status = manager.evaluate()
        assert any(r.kind is HazardKind.FIRE for r in status.readings)
        assert status.state is HazardState.EMERGENCY


# --------------------------------------------------------------------------- #
# TEST 12: event logging
# --------------------------------------------------------------------------- #
class TestEventLogIntegration:
    def test_vision_hazard_becomes_a_recorded_event(self):
        manager = HazardManager(_config())
        manager.add_source(_source("fire"))
        manager.evaluate()
        events = manager.events.history()
        assert len(events) == 1
        assert events[0].kind is HazardKind.FIRE
        assert events[0].state is HazardState.EMERGENCY

    def test_confidence_survives_into_the_event(self):
        manager = HazardManager(_config())
        manager.add_source(_source("person"))
        manager.evaluate()
        event = manager.events.history()[0]
        assert event.confidence == 0.91
        assert event.metadata["confidence"] == 0.91

    def test_confidence_is_not_rescaled_to_one(self):
        manager = HazardManager(_config())
        manager.add_source(VisionHazardSource(
            lambda: [{"class": "SMOKE", "confidence": 0.84}], name="cam"))
        manager.evaluate()
        assert manager.events.history()[0].confidence == 0.84

    def test_event_is_written_to_the_jsonl_log(self, tmp_path):
        path = tmp_path / "events.jsonl"
        manager = HazardManager(_config(event_log_path=str(path)))
        manager.add_source(_source("fire"))
        manager.evaluate()
        assert path.exists()
        events = read_events(path)
        assert events[0]["kind"] == "FIRE"
        assert events[0]["confidence"] == 0.93

    def test_resolved_event_still_keeps_its_evidence(self):
        manager = HazardManager(_config())
        live = [VisionDetection(VisionClass.FIRE, 0.9)]
        manager.add_source(VisionHazardSource(lambda: live, name="cam"))
        manager.evaluate()
        live.clear()  # detector no longer sees the hazard
        manager.evaluate()
        event = manager.events.history()[0]
        assert event.resolved is True
        assert event.confidence == 0.9


# --------------------------------------------------------------------------- #
# TEST 13: C3 spatial visualisation integration
# --------------------------------------------------------------------------- #
class TestVisualisationIntegration:
    #: Minimal warehouse locations so the renderer has a real plot frame.
    LOCATIONS = {"dock": {"x": 0.0, "y": 0.0, "theta": 0.0},
                 "shelf_a": {"x": 4.0, "y": 2.0, "theta": 0.0}}

    def _manager_with_event(self, scenario):
        manager = HazardManager(_config())
        manager.add_source(_source(scenario))
        manager.evaluate()
        return manager

    def _svg(self, scenario):
        manager = self._manager_with_event(scenario)
        return render_map_svg(self.LOCATIONS,
                              events_from_snapshot(manager.snapshot()))

    def test_vision_event_reaches_the_svg_renderer(self):
        svg = self._svg("with_location")
        assert ET.fromstring(svg).tag.endswith("svg")
        assert "FIRE" in svg
        assert 'class="hazard-event"' in svg

    def test_unlocated_vision_event_is_listed_in_the_panel(self):
        svg = self._svg("person")
        assert "HUMAN" in svg
        assert "1 without location" in svg

    def test_vision_metadata_never_becomes_a_world_coordinate(self):
        """A bbox-only detection must stay in the unlocated panel."""
        manager = self._manager_with_event("without_location")
        events = events_from_snapshot(manager.snapshot())
        assert events[0]["location"] is None
        assert events[0]["metadata"]["bbox"] == [10, 20, 60, 120]

    def test_svg_stays_well_formed_with_detection_metadata(self):
        ET.fromstring(self._svg("without_location"))

    def test_svg_is_deterministic(self):
        manager = self._manager_with_event("multiple_objects")
        events = events_from_snapshot(manager.snapshot())
        first = render_map_svg(self.LOCATIONS, events)
        second = render_map_svg(self.LOCATIONS, events)
        assert first == second

    def test_world_location_is_preserved_on_the_event(self):
        manager = self._manager_with_event("with_location")
        event = manager.events.history()[0]
        assert event.location is not None
        assert event.location.x == pytest.approx(12.3)
        assert event.location.y == pytest.approx(4.7)



# --------------------------------------------------------------------------- #
# TEST 14: safety state machine integration
# --------------------------------------------------------------------------- #
class TestSafetyIntegration:
    def test_warning_band_only_warns(self):
        # 0.93 sits between the warn (0.50) and critical (0.95) bands.
        status = _evaluate("fire", vision_warn_at=0.50,
                           vision_critical_at=0.95)
        assert status.state is HazardState.WARNING
        assert status.blocks_motion is False

    def test_below_warn_threshold_produces_no_hazard(self):
        # 0.93 is below the warn band -> filtered out entirely (NORMAL).
        status = _evaluate("fire", vision_warn_at=0.95,
                           vision_critical_at=0.99)
        assert status.state is HazardState.NORMAL
        assert status.readings == ()

    def test_person_is_not_forced_to_emergency(self):
        """PERSON maps to STOP, not EMERGENCY -- no auto-escalation."""
        status = _evaluate("person")
        assert status.state is HazardState.STOP
        assert status.latched is False

    def test_emergency_caps_speed_and_blocks_motion(self):
        status = _evaluate("fire")
        assert status.state is HazardState.EMERGENCY
        assert status.speed_scale == 0.0
        assert status.blocks_motion is True

    def test_vision_module_does_not_touch_motor_control(self):
        """The vision module must not import motor or Arduino code."""
        import amr.hazard.vision as vision

        path = (vision.__file__ or "").lower()
        assert path.endswith("hazard/vision.py")
        assert not any(word in path for word in
                       ("control", "communication", "arduino"))

    def test_evidence_falls_back_to_robot_pose_for_the_status(self):
        manager = HazardManager(_config())
        manager.add_source(_source("person"))
        status = manager.evaluate(location=HazardLocation(2.0, 3.0))
        assert status.location.x == pytest.approx(2.0)


# --------------------------------------------------------------------------- #
# C2 web compatibility
# --------------------------------------------------------------------------- #
class TestWebCompatibility:
    def test_vision_event_is_exposed_by_the_manager_snapshot(self):
        manager = HazardManager(_config())
        manager.add_source(_source("fire"))
        manager.evaluate()
        snapshot = manager.snapshot()
        assert snapshot["state"] == "EMERGENCY"
        assert snapshot["active_events"][0]["kind"] == "FIRE"
        assert snapshot["active_events"][0]["confidence"] == 0.93

    def test_snapshot_is_json_serialisable(self):
        manager = HazardManager(_config())
        manager.add_source(_source("with_location"))
        manager.evaluate()
        assert json.dumps(manager.snapshot())


# --------------------------------------------------------------------------- #
# Simulated detector surface
# --------------------------------------------------------------------------- #
class TestSimulatedDetector:
    #: The C5 baseline scenario set. C13 added image-space (bbox) scenarios
    #: on top; this list is what the original `== 12` assertion was really
    #: asserting, and it is now stated explicitly so adding a scenario later
    #: cannot silently drop one of these.
    C5_SCENARIOS = (
        "normal", "person", "fire", "smoke", "obstacle", "low_confidence",
        "multiple_objects", "with_location", "without_location", "malformed",
        "unknown_class", "multiple_cameras",
    )
    #: Added in C13 for camera overlays. All carry pixel bboxes in a 640x480
    #: frame and are simulation input only.
    C13_SCENARIOS = (
        "person_bbox", "bbox_multiple", "bbox_partially_outside",
        "bbox_world_and_image",
    )

    def test_all_baseline_scenarios_are_available(self):
        """The original C5 contract: all twelve documented scenarios exist."""
        for name in self.C5_SCENARIOS:
            assert name in SIMULATED_SCENARIOS, name

    def test_c13_bbox_scenarios_are_available(self):
        for name in self.C13_SCENARIOS:
            assert name in SIMULATED_SCENARIOS, name

    def test_scenario_set_is_exactly_the_documented_one(self):
        """Still an exact set — C13 added four, and no scenario was removed."""
        assert set(SIMULATED_SCENARIOS) == set(self.C5_SCENARIOS) | \
            set(self.C13_SCENARIOS)
        assert len(SIMULATED_SCENARIOS) == 16

    def test_normal_scenario_is_empty(self):
        assert SimulatedVisionDetector("normal").detect(None) == ()

    @pytest.mark.parametrize("scenario", sorted(SIMULATED_SCENARIOS))
    def test_every_scenario_is_deterministic(self, scenario):
        first = SimulatedVisionDetector(scenario).detect(None)
        second = SimulatedVisionDetector(scenario).detect(None)
        assert [d.to_dict() for d in first] == [d.to_dict() for d in second]

    def test_unknown_scenario_raises(self):
        with pytest.raises(ValueError, match="unknown scenario"):
            SimulatedVisionDetector("does-not-exist")

    def test_simulate_helper_returns_readings(self):
        assert simulate("person")[0].kind is HazardKind.HUMAN

    def test_custom_camera_source_is_stamped(self):
        detector = SimulatedVisionDetector(
            [{"class": "PERSON", "confidence": 0.9}], source="camera_top")
        assert detector.detect(None)[0].source == "camera_top"

    def test_timestamps_are_fixed_by_default(self):
        det = SimulatedVisionDetector("person").detect(None)[0]
        assert det.timestamp == 1_700_000_000.0

    def test_explicit_detection_source_wins(self):
        detector = SimulatedVisionDetector("multiple_cameras",
                                           source="simulated_camera")
        assert {d.source for d in detector.detect(None)} == {
            "camera_front", "camera_rear"}

    def test_multiple_cameras_keep_separate_event_identities(self):
        manager = HazardManager(_config())
        manager.add_source(_source("multiple_cameras"))
        manager.evaluate()
        assert {e.source for e in manager.events.history()} == {
            "camera_front", "camera_rear"}

    def test_malformed_scenario_yields_no_detections(self):
        assert SimulatedVisionDetector("malformed").detect(None) == ()

    def test_unknown_class_scenario_yields_no_detections(self):
        assert SimulatedVisionDetector("unknown_class").detect(None) == ()

    def test_low_confidence_scenario_produces_no_reading(self):
        assert simulate("low_confidence") == ()

    def test_detector_is_documented_as_simulation_only(self):
        assert "SIMULATION" in (
            SimulatedVisionDetector.__doc__ or "").upper()

    def test_manager_survives_a_broken_source_alongside_vision(self):
        def boom():
            raise RuntimeError("camera disconnected")

        manager = HazardManager(_config())
        manager.add_source(VisionHazardSource(boom, name="camera_front"))
        manager.add_source(_source("person"))
        status = manager.evaluate()
        assert status.state is HazardState.STOP
        assert any(r.kind is HazardKind.HUMAN for r in status.readings)

    def test_none_detections_are_ignored(self):
        assert make_vision_readings(None) == ()

    def test_empty_frame_keeps_state_normal(self):
        status = _evaluate("normal")
        assert status.state is HazardState.NORMAL
        assert status.readings == ()
        assert not status.blocks_motion
