"""C9 — 2D warehouse map: model, coordinate transform, rendering, HTTP.

No test here requires a robot, a Raspberry Pi, a camera or a network. The
navigator and hazard layer are test doubles, so the whole file runs in CI.

The properties under test are the ones that keep the map *honest* and
*consistent*:

* the warehouse frame (metres, y-up, radians) is preserved end to end;
* the world->screen transform is deterministic, aspect-preserving and y-flipped;
* a hazard is placed **only** with a real world location (the C5 rule), and an
  image-space detection is listed but never given coordinates;
* static geometry the project does not model is reported UNAVAILABLE rather
  than invented;
* the map is strictly read-only and can never move the robot.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import pytest

from amr.map import (
    MAP_SCHEMA_VERSION,
    MapPoint,
    MapService,
    MapTransform,
    PathHistory,
    bounds_for,
    build_map_snapshot,
    goal_from,
    hazards_from,
    robot_from,
    route_from,
    waypoints_from,
    zones_from,
)
from amr.navigation import LocalNavigator
from amr.navigation.types import Goal, Pose
from amr.robot import RobotManager
from amr.utils.config import load_config
from amr.warehouse import WarehouseTaskManager
from amr.web import AMRWebApp

# The real warehouse layout from config/warehouse.yaml — the map must consume
# this shape, not invent a richer one.
REAL_LOCATIONS = {
    "dock": {"x": 0.0, "y": 0.0, "theta": 0.0},
    "shelf_a": {"x": 2.0, "y": 0.0, "theta": 0.0},
    "shelf_b": {"x": 2.0, "y": 1.5, "theta": 0.0},
    "shelf_c": {"x": 4.0, "y": 1.5, "theta": 0.0},
    "station": {"x": 0.0, "y": 3.0, "theta": 0.0},
}

REAL_ZONE = {
    "name": "charging_bay",
    "x_min": 3.5, "x_max": 4.5, "y_min": 1.0, "y_max": 2.0,
    "severity": "CRITICAL", "kind": "ZONE_BREACH",
}


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeNavigator:
    """Stands in for ``LocalNavigator``: real Pose/Goal, no motion side effects."""

    def __init__(self, pose=None, goal=None, status="IDLE", route=()):
        self._pose = pose if pose is not None else Pose(0.0, 0.0, 0.0)
        self._goal = goal
        self._status = status
        self._route = tuple(route)
        # Any call to a movement API from the map would be a bug; record it.
        self.movement_calls = []

    def current_pose(self):
        return self._pose

    def goal(self):
        return self._goal

    def status(self):
        return self._status

    def plan(self, goal):
        return list(self._route) or ([self._pose, goal.pose] if goal else [])

    def step(self, dt):  # pragma: no cover - must never be called by the map
        self.movement_calls.append(dt)
        return self._status

    def go_to(self, goal):  # pragma: no cover - must never be called
        self.movement_calls.append(goal)
        return self._status


class Exploding:
    """A collaborator whose every attribute access raises."""

    def __getattr__(self, name):
        def _boom(*_a, **_kw):
            raise RuntimeError("subsystem is on fire")

        return _boom


def _hazard_event(**kw):
    base = {
        "event_id": "e1", "kind": "PERSON", "severity": "WARNING",
        "confidence": 0.91, "source": "camera_front",
        "location": {"x": 1.0, "y": 2.0, "theta": 0.0, "zone": None},
        "metadata": {},
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
# 1. Map model — waypoints, zones, static geometry, source metadata
# --------------------------------------------------------------------------- #
class TestMapModel:
    def test_waypoints_from_the_real_config_shape(self):
        wps = waypoints_from(REAL_LOCATIONS)
        assert [w.name for w in wps] == list(REAL_LOCATIONS)
        assert wps[2].x == 2.0 and wps[2].y == 1.5
        assert wps[0].source == "SIMULATION"

    def test_waypoints_accept_the_sequence_form(self):
        wps = waypoints_from({"a": (1.0, 2.0, 0.5)})
        assert (wps[0].x, wps[0].y, wps[0].theta) == (1.0, 2.0, 0.5)

    def test_waypoints_accept_a_warehouse_map_instance(self):
        from amr.warehouse.map import map_from_config
        from amr.utils.config import WarehouseConfig
        wps = waypoints_from(map_from_config(WarehouseConfig(
            locations=REAL_LOCATIONS)))
        assert {w.name for w in wps} == set(REAL_LOCATIONS)

    def test_empty_warehouse_is_empty_not_fabricated(self):
        assert waypoints_from(None) == ()
        assert waypoints_from({}) == ()
        assert waypoints_from("not a map") == ()

    @pytest.mark.parametrize("bad", [
        {"x": None, "y": 1.0}, {"x": 1.0, "y": "nope"},
        {"x": float("nan"), "y": 1.0}, {"y": 1.0},
    ])
    def test_malformed_waypoint_is_skipped(self, bad):
        # One broken entry must not take the whole map down, and must never
        # become a (0, 0) point.
        wps = waypoints_from({"good": {"x": 1.0, "y": 1.0}, "bad": bad})
        assert [w.name for w in wps] == ["good"]

    def test_zones_from_the_real_config_shape(self):
        zones = zones_from([REAL_ZONE])
        assert len(zones) == 1
        assert zones[0].name == "charging_bay"
        assert (zones[0].x_min, zones[0].x_max) == (3.5, 4.5)
        assert zones[0].severity == "CRITICAL"

    def test_zone_with_swapped_bounds_is_normalised(self):
        # C5's HazardZone tolerates swapped config bounds; the map must not
        # draw an inverted rectangle.
        out = zones_from([{"name": "z", "x_min": 4.5, "x_max": 3.5,
                           "y_min": 1.0, "y_max": 2.0}])
        assert out[0].x_min == 3.5 and out[0].x_max == 4.5

    def test_static_geometry_the_project_does_not_model_is_reported(self):
        snap = build_map_snapshot(locations=REAL_LOCATIONS, simulated=True)
        d = snap.static.to_dict()
        # The project models waypoints, not shelves/racks/obstacles/walls.
        assert d["shelves"] == [] and d["racks"] == [] and d["obstacles"] == []
        assert d["boundary"] is None
        assert "not modelled" in d["note"]
        # ...and says so, rather than drawing an invented floor plan.
        assert len(d["waypoints"]) == 5
        assert d["bounds"] is not None

    def test_bounds_are_none_when_nothing_is_placed(self):
        assert bounds_for() is None
        assert build_map_snapshot().static.bounds is None

    def test_source_is_unavailable_when_there_is_nothing(self):
        snap = build_map_snapshot()
        assert snap.source == "UNAVAILABLE"
        assert snap.static.source == "UNAVAILABLE"
        assert snap.robot is None

    def test_source_is_simulation_for_mock_geometry(self):
        assert build_map_snapshot(
            locations=REAL_LOCATIONS, simulated=True).source == "SIMULATION"
        assert build_map_snapshot(
            locations=REAL_LOCATIONS, simulated=False).source == "LIVE"

    def test_snapshot_declares_its_coordinate_convention(self):
        d = build_map_snapshot(locations=REAL_LOCATIONS, simulated=True).to_dict()
        assert d["units"] == "metres"
        assert d["y_axis"] == "up"
        assert d["yaw_units"] == "radians"
        assert d["frame"] == "warehouse"
        assert d["schema_version"] == MAP_SCHEMA_VERSION

    def test_snapshot_is_json_serialisable(self):
        json.dumps(build_map_snapshot(
            locations=REAL_LOCATIONS, zones=[REAL_ZONE], simulated=True).to_dict())


# --------------------------------------------------------------------------- #
# 2. Coordinate transform — origin, corners, y-flip, determinism
# --------------------------------------------------------------------------- #
class TestMapTransform:
    @pytest.fixture
    def t(self):
        return MapTransform({"x_min": 0.0, "x_max": 4.0,
                             "y_min": 0.0, "y_max": 4.0},
                            width=400, height=400, padding=0.0)

    def test_origin_is_bottom_left(self, t):
        x, y = t.to_screen(0.0, 0.0)
        assert (x, y) == (0.0, 400.0)

    def test_far_corner_is_top_right(self, t):
        x, y = t.to_screen(4.0, 4.0)
        assert (x, y) == (400.0, 0.0)

    def test_centre_is_the_centre(self, t):
        x, y = t.to_screen(2.0, 2.0)
        assert abs(x - 200.0) < 1e-9 and abs(y - 200.0) < 1e-9

    def test_y_is_flipped_because_the_world_is_y_up(self, t):
        # The defining property: world +y must render UPWARD on screen.
        assert t.to_screen(0.0, 3.0)[1] < t.to_screen(0.0, 1.0)[1]
        assert t.to_screen(0.0, 4.0)[1] < t.to_screen(0.0, 0.0)[1]

    def test_aspect_ratio_is_preserved(self):
        # A non-square viewport must not stretch a square metre.
        t = MapTransform({"x_min": 0.0, "x_max": 10.0,
                          "y_min": 0.0, "y_max": 10.0},
                         width=400, height=200, padding=0.0)
        (x0, y0), (x1, y1) = t.to_screen(0, 0), t.to_screen(1, 1)
        assert abs((x1 - x0) - (y0 - y1)) < 1e-9

    def test_negative_coordinates_are_supported(self):
        t = MapTransform({"x_min": -5.0, "x_max": 5.0,
                          "y_min": -5.0, "y_max": 5.0},
                         width=200, height=200, padding=0.0)
        assert t.to_screen(-5.0, -5.0) == (0.0, 200.0)
        assert t.to_screen(5.0, 5.0) == (200.0, 0.0)

    @pytest.mark.parametrize("bad", [
        (float("nan"), 1.0), (1.0, float("inf")), (None, 1.0), ("a", "b"),
    ])
    def test_invalid_input_never_raises(self, t, bad):
        px, py = t.to_screen(*bad)
        assert not (math.isfinite(px) and math.isfinite(py))

    def test_round_trip_is_exact(self, t):
        for wx, wy in ((0.0, 0.0), (1.25, 3.5), (-2.0, 0.5)):
            bx, by = t.to_world(*t.to_screen(wx, wy))
            assert abs(bx - wx) < 1e-9 and abs(by - wy) < 1e-9

    def test_yaw_is_independent_of_position(self, t):
        # Rotating must not move the point, and vice versa.
        before = t.to_screen(2.0, 2.0)
        assert t.yaw_to_degrees(1.0) == t.yaw_to_degrees(1.0)
        assert before == t.to_screen(2.0, 2.0)

    def test_yaw_conversion_is_negated_for_the_flip(self, t):
        # +pi/2 in a y-up world is 90 deg CCW; SVG must be told -90 deg.
        assert abs(t.yaw_to_degrees(math.pi / 2) + 90.0) < 1e-6
        assert t.yaw_to_degrees(0.0) == 0.0
        assert t.yaw_to_degrees("nope") == 0.0

    def test_degenerate_bounds_do_not_divide_by_zero(self):
        t = MapTransform({"x_min": 1.0, "x_max": 1.0,
                          "y_min": 1.0, "y_max": 1.0},
                         width=0, height=0, padding=0.0)
        assert math.isfinite(t.scale)
        px, py = t.to_screen(1.0, 1.0)
        assert math.isfinite(px) and math.isfinite(py)

    def test_partial_bounds_are_normalised(self):
        t = MapTransform({}, width=200, height=200, padding=10.0)
        assert t.bounds["x_min"] < t.bounds["x_max"]
        assert t.bounds["y_min"] < t.bounds["y_max"]

    def test_zoom_is_clamped_to_something_usable(self):
        b = {"x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0}
        assert MapTransform(b, 200, 200, zoom=0.0).zoom >= 0.05
        assert MapTransform(b, 200, 200, zoom=1e9).zoom <= 20.0

    def test_zoom_scales_and_pan_shifts(self, t):
        # Zoom multiplies the scale; the transform is anchored at the world
        # origin, so a zoomed point moves further from it (the UI re-centres
        # interactively rather than baking that in here).
        base = MapTransform(t.bounds, 400, 400, padding=0.0)
        zoomed = MapTransform(t.bounds, 400, 400, padding=0.0, zoom=2.0)
        assert abs(zoomed.scale - 2.0 * base.scale) < 1e-9
        assert zoomed.to_screen(2.0, 2.0)[0] > base.to_screen(2.0, 2.0)[0]
        panned = MapTransform(t.bounds, 400, 400, padding=0.0,
                              pan_x=1.0).to_screen(0.0, 0.0)
        assert panned[0] > t.to_screen(0.0, 0.0)[0]

    def test_transform_is_deterministic(self, t):
        assert t.to_screen(1.234, 5.678) == t.to_screen(1.234, 5.678)
        assert t.to_dict() == t.to_dict()

    def test_rect_maps_a_world_rectangle(self, t):
        r = t.rect(1.0, 1.0, 3.0, 3.0)
        assert r is not None
        assert abs(r["x"] - 100.0) < 1e-6 and abs(r["y"] - 100.0) < 1e-6
        assert abs(r["width"] - 200.0) < 1e-6

    def test_polyline_drops_non_finite_points(self, t):
        pts = t.polyline([MapPoint(0, 0), MapPoint(1, 1),
                          MapPoint(float("nan"), 2), MapPoint(2, 2)])
        assert "nan" not in pts.lower()
        assert len(pts.split()) == 3  # three "x,y" pairs survive


# --------------------------------------------------------------------------- #
# 3. Robot, goal and route
# --------------------------------------------------------------------------- #
class TestRobotAndRoute:
    def test_robot_pose_comes_from_the_navigator(self):
        nav = FakeNavigator(pose=Pose(1.5, 2.5, 1.5708))
        snap = build_map_snapshot(navigator=nav, locations=REAL_LOCATIONS,
                                  simulated=True)
        assert (snap.robot.x, snap.robot.y) == (1.5, 2.5)
        assert abs(snap.robot.yaw - 1.5708) < 1e-9

    def test_robot_is_absent_without_a_navigator(self):
        assert build_map_snapshot().robot is None

    def test_robot_pose_dict_is_accepted(self):
        r = robot_from({"x": 1.0, "y": 2.0, "theta": 0.5})
        assert (r.x, r.y, r.yaw) == (1.0, 2.0, 0.5)

    @pytest.mark.parametrize("bad", [None, {}, {"x": None, "y": 1.0},
                                     "nope", object()])
    def test_malformed_pose_is_not_invented(self, bad):
        # Critically: never falls back to (0, 0), which is a real place.
        assert robot_from(bad) is None

    def test_goal_is_read_from_the_navigator(self):
        goal = Goal(Pose(4.0, 1.5, 0.0), "shelf_c")
        nav = FakeNavigator(goal=goal, status="MOVING")
        snap = build_map_snapshot(navigator=nav, simulated=True)
        assert snap.goal.name == "shelf_c"
        assert (snap.goal.x, snap.goal.y) == (4.0, 1.5)
        assert snap.navigation_state == "MOVING"

    def test_no_goal_means_no_goal(self):
        assert build_map_snapshot(navigator=FakeNavigator()).goal is None

    def test_route_comes_from_the_planner(self):
        nav = FakeNavigator(
            goal=Goal(Pose(4.0, 1.5, 0.0), "shelf_c"),
            route=[Pose(0, 0), Pose(2.0, 0.0), Pose(4.0, 1.5)])
        snap = build_map_snapshot(navigator=nav, simulated=True)
        assert [(p.x, p.y) for p in snap.route] == [(0.0, 0.0), (2.0, 0.0),
                                                    (4.0, 1.5)]

    def test_no_route_is_reported_as_empty_not_faked(self):
        snap = build_map_snapshot(navigator=FakeNavigator(), simulated=True)
        assert snap.route == ()

    def test_route_points_skip_unusable_entries(self):
        pts = route_from([{"x": 1, "y": 2}, {"x": None, "y": 2},
                          Pose(3.0, 4.0), "junk"])
        assert [(p.x, p.y) for p in pts] == [(1.0, 2.0), (3.0, 4.0)]

    def test_status_may_be_a_property_or_a_method(self):
        class PropNav:
            @property
            def status(self):
                return "IDLE"

            def current_pose(self):
                return Pose(0.0, 0.0, 0.0)

        assert build_map_snapshot(navigator=PropNav()).navigation_state == "IDLE"

    def test_breaking_navigator_degrades_to_unavailable(self):
        snap = build_map_snapshot(navigator=Exploding(), simulated=True)
        assert snap.robot is None
        assert snap.navigation_state is None

    def test_planner_failure_does_not_break_the_map(self):
        class BadPlan:
            def current_pose(self):
                return Pose(0.0, 0.0, 0.0)

            def goal(self):
                return Goal(Pose(1.0, 1.0, 0.0), "g")

            def status(self):
                return "MOVING"

            def plan(self, goal):
                raise RuntimeError("planner exploded")

        snap = build_map_snapshot(navigator=BadPlan(), simulated=True)
        assert snap.route == ()
        assert snap.robot is not None


# --------------------------------------------------------------------------- #
# 4. Hazards — the C5 placement rule
# --------------------------------------------------------------------------- #
class TestMapHazards:
    def test_located_hazard_is_placed(self):
        placed, unplaced = hazards_from([_hazard_event()])
        assert len(placed) == 1 and unplaced == ()
        h = placed[0]
        assert (h.x, h.y) == (1.0, 2.0)
        assert h.kind == "PERSON"

    def test_confidence_is_preserved_exactly(self):
        # Not rounded to 1.0 and not dropped.
        placed, _ = hazards_from([_hazard_event(confidence=0.84)])
        assert placed[0].confidence == 0.84

    def test_source_and_severity_are_preserved(self):
        placed, _ = hazards_from([_hazard_event(source="camera_rear",
                                                 severity="CRITICAL")])
        assert placed[0].source == "camera_rear"
        assert placed[0].severity == "CRITICAL"

    def test_missing_location_is_listed_not_placed(self):
        placed, unlocated = hazards_from([_hazard_event(location=None)])
        assert placed == ()
        assert unlocated[0]["kind"] == "PERSON"
        assert "no world location" in unlocated[0]["reason"]

    def test_image_space_detection_is_never_given_coordinates(self):
        # The C5 rule: a vision bbox is image space, not a warehouse position.
        event = _hazard_event(location=None,
                              metadata={"bbox": [10, 20, 50, 90]})
        placed, unlocated = hazards_from([event])
        assert placed == ()
        assert "image-space" in unlocated[0]["reason"]
        # No x/y may leak into the unplaced record.
        assert "x" not in unlocated[0] and "y" not in unlocated[0]

    def test_partial_location_is_not_treated_as_the_origin(self):
        placed, unplaced = hazards_from([_hazard_event(location={"x": 1.0})])
        assert placed == ()
        assert unplaced[0]["kind"] == "PERSON"

    def test_non_numeric_location_is_rejected(self):
        placed, _ = hazards_from([_hazard_event(location={"x": "a", "y": "b"})])
        assert placed == ()

    def test_zero_zero_location_is_kept_because_it_is_real(self):
        placed, _ = hazards_from([_hazard_event(
            location={"x": 0.0, "y": 0.0})])
        assert (placed[0].x, placed[0].y) == (0.0, 0.0)

    def test_unknown_hazard_kind_is_still_shown(self):
        placed, _ = hazards_from([_hazard_event(kind="MYSTERY")])
        assert placed[0].kind == "MYSTERY"

    def test_missing_kind_degrades_to_unknown_never_omitted(self):
        event = _hazard_event()
        del event["kind"]
        placed, _ = hazards_from([event])
        assert placed[0].kind == "UNKNOWN"

    def test_non_dict_events_are_ignored(self):
        placed, unlocated = hazards_from(["junk", None, 42])
        assert placed == () and unlocated == ()

    def test_no_events_means_no_hazards(self):
        assert hazards_from(None) == ((), ())
        assert hazards_from([]) == ((), ())

    def test_snapshot_splits_located_and_unlocated(self):
        snap = build_map_snapshot(
            hazard_snapshot={"active_events": [
                _hazard_event(),
                _hazard_event(event_id="e2", location=None),
            ]}, simulated=True)
        assert len(snap.hazards) == 1
        assert len(snap.unlocated) == 1
        # The unplaced entry must not have coordinates in its serialised form.
        assert "x" not in snap.unlocated[0]

    def test_the_c2_attached_shape_is_also_accepted(self):
        # GET /hazard adds an `attached` key the manager does not emit; both
        # shapes must work so /map and /hazard never disagree.
        snap = build_map_snapshot(
            hazard_snapshot={"attached": True, "active_events": [
                _hazard_event()]}, simulated=True)
        assert len(snap.hazards) == 1

    def test_a_snapshot_with_no_events_yields_nothing(self):
        assert build_map_snapshot(hazard_snapshot={}).hazards == ()
        # An explicitly unattached layer (the C2 payload shape) has no data.
        assert build_map_snapshot(
            hazard_snapshot={"attached": False,
                             "active_events": None}).hazards == ()


# --------------------------------------------------------------------------- #
# 5. Path history — bounded and de-duplicated
# --------------------------------------------------------------------------- #
class TestPathHistory:
    def test_first_point_is_stored(self):
        h = PathHistory()
        assert h.add(0.0, 0.0) is True
        assert len(h) == 1

    def test_stationary_robot_does_not_grow_the_buffer(self):
        h = PathHistory()
        for _ in range(100):
            h.add(1.0, 1.0)
        assert len(h) == 1

    def test_movement_is_recorded(self):
        h = PathHistory()
        for i in range(5):
            h.add(float(i), 0.0)
        assert len(h) == 5

    def test_buffer_is_bounded_and_drops_the_oldest(self):
        h = PathHistory(limit=10)
        for i in range(100):
            h.add(float(i), 0.0)
        assert len(h) == 10
        # The most recent pose is retained; the oldest is gone.
        assert h.points()[-1].x == 99.0

    def test_limit_is_always_at_least_two(self):
        assert PathHistory(limit=0).limit >= 2
        assert PathHistory(limit=-5).limit >= 2

    def test_invalid_point_is_rejected(self):
        h = PathHistory()
        assert h.add(float("nan"), 0.0) is False
        assert h.add(None, 1.0) is False
        assert len(h) == 0

    def test_rotation_alone_is_recorded(self):
        h = PathHistory()
        h.add(0.0, 0.0, 0.0)
        # A turn in place is real motion and must appear in the trail.
        assert h.add(0.0, 0.0, math.pi / 2) is True

    def test_clear_resets(self):
        h = PathHistory()
        h.add(1.0, 1.0)
        h.clear()
        assert len(h) == 0

    def test_service_records_the_travelled_path(self):
        nav = FakeNavigator(pose=Pose(0.0, 0.0, 0.0))
        svc = MapService(locations=REAL_LOCATIONS, navigator=nav,
                         simulated=True)
        svc.snapshot()
        for x in (1.0, 2.0, 3.0):
            nav._pose = Pose(x, 0.0, 0.0)
            svc.snapshot()
        assert [p.x for p in svc.snapshot().path] == [0.0, 1.0, 2.0, 3.0]

    def test_service_path_is_bounded(self):
        nav = FakeNavigator(pose=Pose(0.0, 0.0, 0.0))
        svc = MapService(locations=REAL_LOCATIONS, navigator=nav,
                         simulated=True, path_limit=5)
        for i in range(50):
            nav._pose = Pose(float(i), 0.0, 0.0)
            svc.snapshot()
        assert len(svc.snapshot().path) <= 5


# --------------------------------------------------------------------------- #
# 6. SVG rendering
# --------------------------------------------------------------------------- #
def _service(**kw):
    kw.setdefault("locations", REAL_LOCATIONS)
    kw.setdefault("simulated", True)
    return MapService(**kw)


class TestMapRendering:
    def test_svg_is_valid_xml(self):
        ET.fromstring(_service().svg(600, 400))

    def test_svg_contains_every_layer(self):
        svg = _service(
            zones=[REAL_ZONE],
            navigator=FakeNavigator(pose=Pose(0.5, 0.5, 0.3),
                                   goal=Goal(Pose(4.0, 1.5, 0.0), "shelf_c"),
                                   status="MOVING"),
            hazard_layer=_HazardStub([_hazard_event()]),
        ).svg(600, 400)
        assert "layer-grid" in svg
        assert "layer-zones" in svg
        assert "layer-waypoints" in svg
        assert "layer-goal" in svg
        assert "layer-hazards" in svg
        assert 'data-layer="robot"' in svg

    def test_robot_marker_rotates_by_the_real_yaw(self):
        svg = _service(navigator=FakeNavigator(
            pose=Pose(0.0, 0.0, math.pi / 2))).svg(600, 400)
        # +pi/2 in a y-up world -> -90 deg in SVG.
        assert "rotate(-90.00)" in svg

    def test_waypoint_names_are_escaped(self):
        # Names come from config; they must not be able to break the document.
        svg = _service(locations={"<script>x</script>": {"x": 0.0, "y": 0.0}}
                       ).svg(400, 300)
        ET.fromstring(svg)
        assert "<script>" not in svg

    def test_no_data_renders_an_explicit_empty_state(self):
        svg = MapService().svg(400, 300)
        ET.fromstring(svg)
        assert "no map data available" in svg

    def test_rendering_is_deterministic(self):
        svc = _service(navigator=FakeNavigator(pose=Pose(1.0, 1.0, 0.2)))
        assert svc.svg(600, 400) == svc.svg(600, 400)

    def test_render_is_deterministic_across_instances(self):
        nav = FakeNavigator(pose=Pose(1.0, 1.0, 0.2))
        a = _service(navigator=nav).svg(600, 400)
        b = _service(navigator=FakeNavigator(pose=Pose(1.0, 1.0, 0.2))).svg(600, 400)
        assert a == b

    def test_zoom_changes_the_scale_not_the_data(self):
        svc = _service()
        zoomed = svc.svg(600, 400, zoom=2.0)
        assert "charging_bay" not in zoomed  # no zones configured here
        assert "shelf_a" in zoomed

    def test_breaking_hazard_layer_does_not_break_rendering(self):
        svg = _service(hazard_layer=Exploding()).svg(400, 300)
        ET.fromstring(svg)

    def test_route_polyline_is_emitted_when_there_is_a_route(self):
        svg = _service(navigator=FakeNavigator(
            goal=Goal(Pose(4.0, 1.5, 0.0), "shelf_c"),
            route=[Pose(0, 0), Pose(2.0, 0.0), Pose(4.0, 1.5)])).svg(600, 400)
        assert "layer-route" in svg


class _HazardStub:
    """Minimal hazard-layer double exposing only ``snapshot()``."""

    def __init__(self, events):
        self._events = events

    def snapshot(self):
        return {"attached": True, "state": "WARNING", "latched": False,
                "active_events": self._events, "recent_events": [],
                "events_recorded": len(self._events)}


# --------------------------------------------------------------------------- #
# 7. Safety — the map is read-only and displays, never acts
# --------------------------------------------------------------------------- #
class TestMapIsReadOnly:
    def test_sampling_never_steps_the_navigator(self):
        nav = FakeNavigator(pose=Pose(0.0, 0.0, 0.0))
        svc = MapService(locations=REAL_LOCATIONS, navigator=nav,
                         simulated=True)
        for _ in range(20):
            svc.snapshot()
            svc.svg(400, 300)
        assert nav.movement_calls == []

    def test_map_imports_no_control_or_communication_code(self):
        # The map must not be able to reach an actuator even indirectly.
        import pathlib
        import amr.map
        root = pathlib.Path(amr.map.__file__).parent
        forbidden = ("motor", "pwm", "arduino", "serial", "gpio",
                     "robot_manager", "DifferentialDrive")
        for path in root.glob("*.py"):
            for line in path.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")):
                    for word in forbidden:
                        assert word not in stripped, f"{path.name}: {stripped}"

    def test_emergency_stop_is_surfaced_not_acted_on(self):
        class TelemetryStub:
            def snapshot(self):
                return {
                    "safety": {"state": "SAFETY_STOP", "action": "STOP",
                               "emergency_stop": True},
                    "hazards": {"state": "EMERGENCY", "latched": True},
                }

        snap = build_map_snapshot(locations=REAL_LOCATIONS,
                                  telemetry=TelemetryStub(), simulated=True)
        assert snap.safety.emergency_stop is True
        assert snap.safety.action == "STOP"
        assert snap.safety.latched is True
        # Displaying an E-STOP must not, by itself, change any map geometry.
        assert snap.robot is None

    def test_safety_is_unavailable_without_telemetry(self):
        assert build_map_snapshot().safety.source == "UNAVAILABLE"

    def test_breaking_telemetry_degrades_gracefully(self):
        snap = build_map_snapshot(telemetry=Exploding(), locations=REAL_LOCATIONS)
        assert snap.safety.state is None
        assert len(snap.static.waypoints) == 5

    def test_all_safety_actions_are_passed_through_verbatim(self):
        for action in ("PROCEED", "WAIT", "STOP", "TURN", "REPLAN"):
            class T:
                def snapshot(self):
                    return ({"safety": {"state": "OK", "action": action,
                                         "emergency_stop": False},
                             "hazards": {"state": "NORMAL", "latched": False}})

            assert build_map_snapshot(telemetry=T()).safety.action == action


# --------------------------------------------------------------------------- #
# 8. HTTP surface
# --------------------------------------------------------------------------- #
def _get(port: int, path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}",
                                timeout=5) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


def _post(port: int, path: str, body: str):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def port_of(fixture):
    return fixture[1]


@pytest.fixture
def web_map(config_dir):
    """A running dashboard with the REAL warehouse config and navigator.

    This mirrors ``python -m amr.main --mock --web``, so the HTTP tests exercise
    the same wiring an operator gets rather than a synthetic stand-in.
    """
    config = load_config(config_dir)
    mgr, transport = RobotManager.create_mock(config)
    mgr.test_transport = transport
    wheel_base = config.robot.wheel_track_m or config.warehouse.wheel_base_m
    nav = LocalNavigator(
        command=mgr.move, start_pose=None, wheel_base_m=wheel_base,
        max_linear_speed=config.warehouse.task_speed,
        max_angular_speed=config.warehouse.turn_speed,
        max_pwm=mgr.drive.max_speed)
    wh = WarehouseTaskManager.create(config, mgr, nav)
    app = AMRWebApp(mgr, tick_hz=10.0, navigator=nav, warehouse=wh,
                    simulated=True)
    port = app.start(host="127.0.0.1", port=0)
    mgr.start()
    try:
        yield app, port, mgr
    finally:
        app.stop()
        mgr.shutdown()


class TestMapHTTP:
    def test_get_map_returns_the_snapshot(self, web_map):
        _app, port, _mgr = web_map
        status, ctype, body = _get(port, "/map")
        assert status == 200 and "json" in ctype
        data = json.loads(body)
        assert data["units"] == "metres"
        assert data["y_axis"] == "up"
        assert len(data["warehouse"]["waypoints"]) == 5
        assert data["robot"] is not None
        assert data["source"] == "SIMULATION"

    def test_map_agrees_with_telemetry(self, web_map):
        # The same robot state must appear in both read-only views.
        _app, port, _mgr = web_map
        robot = json.loads(_get(port, "/map")[2])["robot"]
        tele = json.loads(_get(port, "/telemetry")[2])
        assert tele["position"]["x"] == pytest.approx(robot["x"])
        assert tele["position"]["y"] == pytest.approx(robot["y"])

    def test_map_never_contradicts_the_warehouse_config(self, web_map):
        _app, port, _mgr = web_map
        wps = {w["name"]: (w["x"], w["y"]) for w in
               json.loads(_get(port, "/map")[2])["warehouse"]["waypoints"]}
        assert wps["dock"] == (0.0, 0.0)
        assert wps["shelf_c"] == (4.0, 1.5)

    def test_map_svg_is_served(self, web_map):
        _app, port, _mgr = web_map
        status, ctype, body = _get(port, "/map.svg")
        assert status == 200
        assert "svg" in ctype
        ET.fromstring(body.decode("utf-8"))

    def test_map_svg_honours_size_parameters(self, web_map):
        _app, port, _mgr = web_map
        body = _get(port, "/map.svg?width=400&height=300")[2].decode("utf-8")
        assert 'viewBox="0 0 400 300"' in body

    @pytest.mark.parametrize("query", [
        "width=abc", "zoom=xyz", "width=-5", "zoom=1e99", "width=&height=",
    ])
    def test_malformed_parameters_do_not_break_the_map(self, web_map, query):
        _app, port, _mgr = web_map
        status, _ctype, body = _get(port, f"/map.svg?{query}")
        assert status == 200
        ET.fromstring(body.decode("utf-8"))

    def test_map_routes_are_get_only(self, web_map):
        # No POST surface may reach navigation or the map.
        for path in ("/map", "/map.svg"):
            status, _body = _post(port_of(web_map), path, "{}")
            assert status in (404, 405)

    def test_reading_the_map_never_writes_to_the_controller(self, web_map):
        _app, port, mgr = web_map
        before = len(mgr.test_transport.written)
        for _ in range(10):
            _get(port, "/map")
            _get(port, "/map.svg")
        assert len(mgr.test_transport.written) == before

    def test_map_is_unavailable_but_serving_without_a_warehouse(self, config_dir):
        mgr, _t = RobotManager.create_mock(load_config(config_dir))
        app = AMRWebApp(mgr, tick_hz=10.0, simulated=True)
        port = app.start(host="127.0.0.1", port=0)
        mgr.start()
        try:
            data = json.loads(_get(port, "/map")[2])
            assert data["source"] == "UNAVAILABLE"
            assert data["warehouse"]["bounds"] is None
            assert data["warehouse"]["waypoints"] == []
            # The rest of the panel is unaffected.
            for path in ("/dashboard", "/telemetry", "/health"):
                assert _get(port, path)[0] == 200
        finally:
            app.stop()
            mgr.shutdown()

    def test_broken_warehouse_geometry_does_not_break_the_map(self, config_dir):
        mgr, _t = RobotManager.create_mock(load_config(config_dir))
        app = AMRWebApp(mgr, tick_hz=10.0,
                         warehouse={"map": "not a map"}, simulated=True)
        port = app.start(host="127.0.0.1", port=0)
        mgr.start()
        try:
            assert _get(port, "/map")[0] == 200
            ET.fromstring(_get(port, "/map.svg")[2].decode("utf-8"))
        finally:
            app.stop()
            mgr.shutdown()

    def test_dashboard_contains_the_map_panel_and_its_layers(self, web_map):
        _app, port, _mgr = web_map
        body = _get(port, "/dashboard")[2].decode("utf-8")
        assert 'id="m-svg"' in body
        assert 'id="m-safety"' in body
        assert 'id="m-hazards"' in body
        assert 'data-layer="robot"' in body                 # robot layer
        assert "layer-route" in body or "m.route" in body    # route layer
        assert "layer-hazards" in body or "m.hazards" in body  # hazard layer
        assert 'id="m-src"' in body   # simulation/live status is visible
        assert '"/map"' in body

    def test_dashboard_ships_no_command_endpoint(self, web_map):
        _app, port, _mgr = web_map
        assert "/command" not in _get(port, "/dashboard")[2].decode("utf-8")


# --------------------------------------------------------------------------- #
# 9. End-to-end: warehouse -> navigation -> pose -> hazard -> map
# --------------------------------------------------------------------------- #
class _LocatedSource:
    """Hazard source yielding one reading with a real world location."""

    name = "camera"

    def __init__(self, reading):
        self._reading = reading

    def read(self):
        return [self._reading]


class TestMapEndToEnd:
    def test_full_pipeline_is_consistent(self, config_dir):
        """One runtime state must read identically through every view."""
        from amr.hazard import HazardKind, HazardManager, HazardReading

        config = load_config(config_dir)
        mgr, _t = RobotManager.create_mock(config)
        mgr.start()
        try:
            # Warehouse + navigation, exactly as run_web wires them.
            nav = LocalNavigator(
                command=mgr.move, start_pose=None, wheel_base_m=0.30,
                max_linear_speed=0.5, max_angular_speed=1.0,
                max_pwm=mgr.drive.max_speed)
            wh = WarehouseTaskManager.create(config, mgr, nav)
            app = AMRWebApp(mgr, tick_hz=10.0, navigator=nav, warehouse=wh,
                            simulated=True)

            # A hazard event carrying a real world location, produced the way C5
            # produces it: confidence travels in `metadata`, which is where
            # HazardEvent.confidence reads it from.
            hazard = HazardManager.from_config(config.hazard)
            hazard.add_source(_LocatedSource(
                HazardReading(kind=HazardKind.HUMAN, source="camera_front",
                              value=0.9, unit="confidence",
                              location={"x": 2.0, "y": 1.5},
                              metadata={"confidence": 0.9})))
            mgr.attach_hazard(hazard)
            hazard.evaluate()
            app.map._hazard_layer = hazard

            data = app.map_snapshot()

            # 1. The warehouse came from the real config.
            assert {w["name"] for w in data["warehouse"]["waypoints"]} == {
                "dock", "shelf_a", "shelf_b", "shelf_c", "station"}
            # 2. The robot came from the navigator's own odometry.
            assert data["robot"] is not None
            assert data["robot"]["source"] == "SIMULATION"
            # 3. The hazard was placed using its real world location only.
            assert len(data["hazards"]) == 1
            placed = data["hazards"][0]
            assert (placed["x"], placed["y"]) == (2.0, 1.5)
            assert placed["kind"] == "HUMAN"
            assert placed["confidence"] == pytest.approx(0.9)
            # 4. The same state is renderable as valid SVG.
            svg, code = app.map_svg(600, 400)
            assert code == 200
            ET.fromstring(svg)
            assert "HUMAN" in svg
            # 5. Everything is tagged SIMULATION, never LIVE.
            assert data["source"] == "SIMULATION"
        finally:
            mgr.shutdown()

    def test_pipeline_preserves_fire_confidence(self, config_dir):
        from amr.hazard import HazardKind, HazardManager, HazardReading
        config = load_config(config_dir)
        mgr, _t = RobotManager.create_mock(config)
        mgr.start()
        try:
            hazard = HazardManager.from_config(config.hazard)
            hazard.add_source(_LocatedSource(
                HazardReading(kind=HazardKind.FIRE, source="camera_top",
                              value=0.88, unit="confidence",
                              location={"x": 1.0, "y": 2.0},
                              metadata={"confidence": 0.88})))
            mgr.attach_hazard(hazard)
            hazard.evaluate()
            app = AMRWebApp(mgr, tick_hz=10.0, simulated=True)
            app.map._hazard_layer = hazard
            data = app.map_snapshot()
            assert data["hazards"][0]["kind"] == "FIRE"
            assert data["hazards"][0]["confidence"] == pytest.approx(0.88)
        finally:
            mgr.shutdown()
