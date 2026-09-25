"""C13 — camera hazard overlays (display-only).

The single most important thing tested here is a *negative*: that an image-space
bounding box never becomes a world coordinate. The C5 pipeline already forbids
it, and C13 must not quietly undo that by drawing on top of a camera frame.
"""

from __future__ import annotations

import pytest

from amr.camera import CameraOverlay, build_camera_overlay
from amr.camera.frame import CameraFrame, CameraStatus, SimulatedCameraSource
from amr.hazard.vision import (
    SIMULATED_SCENARIOS,
    SimulatedVisionDetector,
    VisionBoundingBox,
)


def _frame(width=640, height=480, source="SimulatedCamera", frame_id=7):
    return CameraFrame(timestamp=1_700_000_000.0, source=source,
                       width=width, height=height, format="png",
                       frame_id=frame_id, data=b"\x89PNG",
                       status=CameraStatus.SIMULATION)


def _event(kind="PERSON", bbox=(10, 20, 60, 120), source="simulated_camera",
           **over):
    meta = {}
    if bbox is not None:
        meta["bbox"] = list(bbox)
    meta.update(over.pop("metadata", {}))
    event = {"kind": kind, "severity": "WARNING", "source": source,
             "metadata": meta, "confidence": 0.91}
    event.update(over)
    return event


# --------------------------------------------------------------------------- #
# Frame contract
# --------------------------------------------------------------------------- #
class TestOverlayFrame:
    def test_valid_frame_reports_image_geometry(self):
        o = build_camera_overlay(_frame(), []).to_dict()
        assert o["image"]["width"] == 640
        assert o["image"]["height"] == 480
        assert o["image"]["backend"] == "SimulatedCamera"
        assert o["image"]["frame_id"] == 7
        assert o["image"]["status"] == "SIMULATION"

    def test_missing_frame_yields_empty_but_valid_overlay(self):
        o = build_camera_overlay(None, [_event()]).to_dict()
        assert o["box_count"] == 0
        assert o["image"]["width"] is None
        # Still drawable=False rather than an error or a fabricated size.
        assert o["drawable"] is False

    def test_deterministic_mock_frame(self):
        """The C8 simulated source is deterministic given a fixed clock."""
        clock = iter([1_700_000_000.0, 1_700_000_000.0, 1_700_000_000.0,
                      1_700_000_000.0, 1_700_000_000.0, 1_700_000_000.0])
        a = SimulatedCameraSource(clock=lambda: next(clock))
        b = SimulatedCameraSource(clock=lambda: 1_700_000_000.0)
        a.start()
        b.start()
        fa, fb = a.read(), b.read()
        assert (fa.width, fa.height) == (fb.width, fb.height) == (640, 480)
        assert fa.status is fb.status is CameraStatus.SIMULATION
        assert fa.source == fb.source
        # Identical frames => an identical overlay, so tests and the dashboard
        # see byte-stable output for the same simulated input.
        assert build_camera_overlay(fa, []).to_dict() == \
            build_camera_overlay(fb, []).to_dict()

    def test_simulated_frame_pixels_are_deterministic(self):
        a, b = SimulatedCameraSource(), SimulatedCameraSource()
        a.start()
        b.start()
        assert a.read().data == b.read().data

    def test_unknown_resolution_is_not_invented(self):
        o = build_camera_overlay(_frame(width=None, height=None), []).to_dict()
        assert o["image"]["width"] is None
        assert o["drawable"] is False


# --------------------------------------------------------------------------- #
# BBox handling
# --------------------------------------------------------------------------- #
class TestOverlayBBox:
    def test_valid_bbox_is_carried_in_image_space(self):
        o = build_camera_overlay(_frame(), [_event()],
                                 camera_id="simulated_camera").to_dict()
        assert o["box_count"] == 1
        box = o["boxes"][0]
        assert box["image_bbox"] == {"x": 10.0, "y": 20.0,
                                     "width": 60.0, "height": 120.0}
        assert box["space"] == "image"

    def test_malformed_bbox_is_not_drawn(self):
        for bad in ([1, 2, 3], "nope", {"x": 1}, [1, 2, 3, 4, 5],
                    [float("nan"), 1, 2, 3], [0, 0, 0, 10], [0, 0, 10, -5]):
            o = build_camera_overlay(_frame(), [_event(bbox=bad)],
                                     camera_id="simulated_camera").to_dict()
            assert o["box_count"] == 0, bad
            assert o["without_bbox"], bad

    def test_bbox_entirely_inside_frame_is_fully_visible(self):
        o = build_camera_overlay(_frame(), [_event(bbox=(1, 1, 10, 10))],
                                 camera_id="simulated_camera").to_dict()
        assert o["boxes"][0]["fully_visible"] is True

    def test_bbox_on_the_boundary_is_fully_visible(self):
        """A box touching the last pixel is inside, not outside."""
        o = build_camera_overlay(_frame(), [_event(bbox=(600, 440, 40, 40))],
                                 camera_id="simulated_camera").to_dict()
        assert o["boxes"][0]["fully_visible"] is True

    def test_bbox_overhanging_the_frame_is_flagged_not_dropped(self):
        o = build_camera_overlay(_frame(), [_event(bbox=(600, 440, 100, 100))],
                                 camera_id="simulated_camera").to_dict()
        # Still drawn, but marked: the operator can see it is partial.
        assert o["box_count"] == 1
        assert o["boxes"][0]["fully_visible"] is False

    def test_bbox_accepted_at_origin(self):
        o = build_camera_overlay(_frame(), [_event(bbox=(0, 0, 5, 5))],
                                 camera_id="simulated_camera").to_dict()
        assert o["box_count"] == 1

    def test_optional_metadata_absent_is_fine(self):
        o = build_camera_overlay(_frame(), [{"kind": "FIRE",
                                              "source": "simulated_camera",
                                              "metadata": {}}],
                                 camera_id="simulated_camera").to_dict()
        assert o["box_count"] == 0
        assert o["without_bbox"][0]["kind"] == "FIRE"

    def test_missing_metadata_key_is_fine(self):
        o = build_camera_overlay(_frame(), [{"kind": "FIRE",
                                              "source": "simulated_camera"}],
                                 camera_id="simulated_camera").to_dict()
        assert o["box_count"] == 0


# --------------------------------------------------------------------------- #
# Coordinate safety — the guarantee this milestone exists to protect
# --------------------------------------------------------------------------- #
class TestCoordinateSpaceIsNeverMixed:
    def test_overlay_declares_image_space_and_no_world_transform(self):
        o = build_camera_overlay(_frame(), [_event()],
                                 camera_id="simulated_camera").to_dict()
        assert o["space"] == "image"
        assert o["units"] == "pixels"
        # Explicitly null: there is no calibration in this project, and saying
        # so is better than leaving a client to assume one exists.
        assert o["world_transform"] is None

    def test_no_box_ever_carries_a_world_position(self):
        o = build_camera_overlay(_frame(), [_event()],
                                 camera_id="simulated_camera").to_dict()
        for box in o["boxes"]:
            for forbidden in ("x_m", "y_m", "world", "location", "pose",
                              "world_x", "world_y"):
                assert forbidden not in box, forbidden

    def test_bbox_values_are_never_rescaled_into_metres(self):
        """A 640-px box must stay 640-px, not become 0.64 m or similar."""
        o = build_camera_overlay(_frame(), [_event(bbox=(0, 0, 640, 480))],
                                 camera_id="simulated_camera").to_dict()
        b = o["boxes"][0]["image_bbox"]
        assert b["width"] == 640.0 and b["height"] == 480.0

    def test_world_located_event_is_not_drawn_on_the_image(self):
        """The C5 rule, re-asserted at the overlay boundary."""
        ev = _event(location={"x": 12.3, "y": 4.7, "frame": "world"})
        o = build_camera_overlay(_frame(), [ev],
                                 camera_id="simulated_camera").to_dict()
        assert o["box_count"] == 0          # not drawn here
        assert len(o["world_located"]) == 1  # reported for the map instead
        assert o["world_located"][0]["location"]["x"] == 12.3

    def test_both_spaces_at_once_are_separated(self):
        """A detection may have both; each must land in its own bucket."""
        ev = _event(bbox=(300, 100, 100, 120),
                    location={"x": 12.3, "y": 4.7, "frame": "world"})
        o = build_camera_overlay(_frame(), [ev],
                                 camera_id="simulated_camera").to_dict()
        # World location wins for map purposes; the image box is not smuggled in.
        assert o["box_count"] == 0
        assert len(o["world_located"]) == 1

    def test_overlay_module_never_references_a_map_transform(self):
        """Source-level guard against a future image->world helper creeping in."""
        import inspect
        import amr.camera.overlay as mod
        src = inspect.getsource(mod)
        for forbidden in ("depth_scale", "metres_per_pixel", "pixels_per_metre",
                          "image_to_world", "project_point", "ray_cast"):
            assert forbidden not in src, forbidden

    def test_reuses_the_existing_validated_bbox_type(self):
        """No second, incompatible box representation."""
        import amr.camera.overlay as mod
        assert mod.VisionBoundingBox is VisionBoundingBox


# --------------------------------------------------------------------------- #
# Frame / camera association
# --------------------------------------------------------------------------- #
class TestFrameAssociation:
    def test_detection_from_another_camera_is_not_drawn(self):
        o = build_camera_overlay(_frame(), [_event(source="camera_rear")],
                                 camera_id="camera_front").to_dict()
        assert o["box_count"] == 0
        assert o["other_source"][0]["source"] == "camera_rear"
        assert "different camera" in o["other_source"][0]["reason"]

    def test_matching_camera_is_drawn(self):
        o = build_camera_overlay(_frame(), [_event(source="camera_front")],
                                 camera_id="camera_front").to_dict()
        assert o["box_count"] == 1

    def test_unknown_frame_source_does_not_assume_a_match(self):
        o = build_camera_overlay(_frame(source="unknown"),
                                 [_event(source="camera_front")]).to_dict()
        assert o["box_count"] == 0
        assert o["other_source"]

    def test_frame_source_fallback_for_single_camera(self):
        """With no explicit camera_id, the frame's own source is the identity."""
        o = build_camera_overlay(_frame(source="simulated_camera"),
                                 [_event(source="simulated_camera")]).to_dict()
        assert o["box_count"] == 1

    def test_backend_name_and_camera_id_are_published_separately(self):
        o = build_camera_overlay(_frame(source="SimulatedCamera"), [],
                                 camera_id="camera_front").to_dict()
        assert o["image"]["backend"] == "SimulatedCamera"
        assert o["image"]["camera_id"] == "camera_front"


# --------------------------------------------------------------------------- #
# Hazard content and robustness
# --------------------------------------------------------------------------- #
class TestOverlayContent:
    def test_multiple_hazards_each_get_a_box(self):
        evs = [_event("PERSON", (10, 10, 50, 50)),
               _event("FIRE", (200, 100, 80, 80)),
               _event("OBSTACLE", (300, 300, 120, 60))]
        o = build_camera_overlay(_frame(), evs,
                                 camera_id="simulated_camera").to_dict()
        assert o["box_count"] == 3
        assert [b["kind"] for b in o["boxes"]] == ["PERSON", "FIRE", "OBSTACLE"]

    def test_confidence_is_preserved_not_rescaled(self):
        o = build_camera_overlay(_frame(), [_event(confidence=0.84)],
                                 camera_id="simulated_camera").to_dict()
        assert o["boxes"][0]["confidence"] == 0.84

    def test_confidence_read_from_metadata_when_event_lacks_it(self):
        ev = {"kind": "PERSON", "source": "simulated_camera",
              "metadata": {"bbox": [1, 2, 3, 4], "confidence": 0.55}}
        o = build_camera_overlay(_frame(), [ev],
                                 camera_id="simulated_camera").to_dict()
        assert o["boxes"][0]["confidence"] == 0.55

    def test_out_of_range_confidence_is_dropped_not_the_box(self):
        ev = {"kind": "PERSON", "source": "simulated_camera",
              "metadata": {"bbox": [1, 2, 3, 4], "confidence": 7.5}}
        o = build_camera_overlay(_frame(), [ev],
                                 camera_id="simulated_camera").to_dict()
        # The box is still valid evidence; only the bogus number is refused.
        assert o["box_count"] == 1
        assert o["boxes"][0]["confidence"] is None

    def test_severity_is_carried(self):
        o = build_camera_overlay(_frame(), [_event(severity="EMERGENCY")],
                                 camera_id="simulated_camera").to_dict()
        assert o["boxes"][0]["severity"] == "EMERGENCY"

    def test_label_defaults_to_kind_and_can_be_overridden(self):
        plain = build_camera_overlay(_frame(), [_event()],
                                     camera_id="simulated_camera").to_dict()
        assert plain["boxes"][0]["label"] == "PERSON"
        ev = _event(metadata={"label": "worker in aisle 3"})
        named = build_camera_overlay(_frame(), [ev],
                                     camera_id="simulated_camera").to_dict()
        assert named["boxes"][0]["label"] == "worker in aisle 3"

    def test_kind_colour_is_published(self):
        o = build_camera_overlay(_frame(), [_event("FIRE")],
                                 camera_id="simulated_camera").to_dict()
        assert o["boxes"][0]["color"].startswith("#")

    def test_non_dict_events_are_skipped(self):
        o = build_camera_overlay(_frame(), [None, 42, "x", _event()],
                                 camera_id="simulated_camera").to_dict()


# --------------------------------------------------------------------------- #
# End-to-end with the real C5 pipeline
# --------------------------------------------------------------------------- #
class TestEndToEndFromSimulatedDetector:
    def _events(self, scenario):
        # Mirrors HazardEvent.to_dict(): location is a TOP-LEVEL key, and bbox
        # lives in metadata. Copying the real shape here is deliberate — a
        # hand-rolled event that omits `location` would let a world-located
        # hazard be drawn on the image, hiding the very bug C13 guards against.
        dets = SimulatedVisionDetector(scenario).detect()
        return [{"kind": d.vision_class.value, "severity": "WARNING",
                 "source": d.source, "metadata": dict(d.metadata),
                 "confidence": d.confidence, "object_id": d.object_id,
                 "location": d.location.to_dict() if d.location else None}
                for d in dets]

    def test_bbox_scenarios_exist_and_carry_pixel_boxes(self):
        for name in ("person_bbox", "bbox_multiple", "bbox_partially_outside"):
            dets = SimulatedVisionDetector(name).detect()
            assert dets, name
            assert all(d.bbox is not None for d in dets), name
            assert all(d.location is None for d in dets), name

    def test_person_bbox_flows_through_to_an_overlay(self):
        o = build_camera_overlay(_frame(), self._events("person_bbox"),
                                 camera_id="simulated_camera").to_dict()
        assert o["box_count"] == 1
        assert o["boxes"][0]["kind"] == "PERSON"
        assert o["boxes"][0]["image_bbox"]["width"] == 90.0

    def test_multiple_bbox_scenario(self):
        o = build_camera_overlay(_frame(), self._events("bbox_multiple"),
                                 camera_id="simulated_camera").to_dict()
        assert o["box_count"] == 3
        assert o["drawable"] is True

    def test_partial_box_scenario_is_flagged(self):
        o = build_camera_overlay(
            _frame(), self._events("bbox_partially_outside"),
            camera_id="simulated_camera").to_dict()
        assert o["boxes"][0]["fully_visible"] is False

    def test_world_and_image_scenario_keeps_them_apart(self):
        o = build_camera_overlay(_frame(), self._events("bbox_world_and_image"),
                                 camera_id="simulated_camera").to_dict()
        assert o["box_count"] == 0
        assert len(o["world_located"]) == 1

    def test_c5_scenarios_without_bbox_still_work(self):
        """Adding C13 scenarios must not disturb the existing ones."""
        for name in ("person", "fire", "smoke", "obstacle", "multiple_objects",
                     "without_location", "with_location", "multiple_cameras"):
            assert SimulatedVisionDetector(name).detect(), name
        o = build_camera_overlay(_frame(), self._events("person"),
                                 camera_id="simulated_camera").to_dict()
        assert o["box_count"] == 0
        assert o["without_bbox"][0]["kind"] == "PERSON"

    def test_existing_scenario_keys_are_preserved(self):
        for name in ("normal", "person", "fire", "smoke", "obstacle",
                     "low_confidence", "multiple_objects", "with_location",
                     "without_location", "malformed", "unknown_class",
                     "multiple_cameras"):
            assert name in SIMULATED_SCENARIOS, name


