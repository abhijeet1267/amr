"""C10 — 3D digital twin.

The twin is a *view* over the C9 MapSnapshot. These tests pin the three things
that matter most: the world -> 3D conversion is centralised and correct, the
twin is honest (schematic, never fabricated), and it is strictly read-only.
"""

from __future__ import annotations

import json
import math

import pytest

from amr.map import (
    GEOMETRY_DISCLAIMER,
    MapGoal,
    MapHazard,
    MapPoint,
    MapRobot,
    MapSafety,
    MapSnapshot,
    MapStatic,
    MapWaypoint,
    MapZone,
    TWIN_COORDINATE_SYSTEM,
    TWIN_SCHEMA_VERSION,
    build_twin_state,
    robot_model,
    world_to_three,
    yaw_to_rotation_z,
)
from amr.map.snapshot import LIVE, SIMULATION, UNAVAILABLE


def _snap(**kw) -> MapSnapshot:
    """A populated snapshot; override any field per test."""
    base = dict(
        robot=MapRobot(2.0, 3.0, math.pi / 2, SIMULATION),
        goal=MapGoal("shelf_c", 4.0, 1.5, 0.0, SIMULATION),
        route=(MapPoint(2.0, 3.0), MapPoint(3.0, 2.0), MapPoint(4.0, 1.5)),
        path=(MapPoint(0.0, 0.0), MapPoint(1.0, 1.0)),
        static=MapStatic(waypoints=(
            MapWaypoint("dock", 0.0, 0.0, SIMULATION),
            MapWaypoint("shelf_c", 4.0, 1.5, SIMULATION),
        ), bounds={"x_min": 0.0, "x_max": 4.0, "y_min": 0.0, "y_max": 3.0},
            source=SIMULATION),
        zones=(MapZone("charging_bay", 3.5, 1.0, 4.5, 2.0, "CRITICAL"),),
        safety=MapSafety("NORMAL", "PROCEED", False, None, False, SIMULATION),
        source=SIMULATION,
    )
    base.update(kw)
    return MapSnapshot(**base)


class TestCoordinateConversion:
    """The single world -> 3D conversion, pinned at the required angles."""

    def test_origin_maps_to_origin(self):
        assert world_to_three(0.0, 0.0) == [0.0, 0.0, 0.0]

    def test_world_y_is_negated_for_the_z_up_renderer(self):
        # y-up -> z-up: the same single negation the 2D SVG view applies.
        assert world_to_three(1.0, 2.0) == [1.0, -2.0, 0.0]
        assert world_to_three(1.0, -2.0) == [1.0, 2.0, 0.0]

    def test_height_becomes_renderer_z(self):
        assert world_to_three(0.0, 0.0, 0.45) == [0.0, 0.0, 0.45]

    def test_positive_and_negative_coordinates_round_trip(self):
        for x, y in ((3.5, 2.25), (-3.5, -2.25), (0.0, -7.0)):
            got = world_to_three(x, y)
            assert got[0] == pytest.approx(x)
            assert -got[1] == pytest.approx(y)

    @pytest.mark.parametrize("yaw,expected", [
        (0.0, 0.0),
        (math.pi / 2, -90.0),
        (math.pi, -180.0),
        (-math.pi / 2, 90.0),
    ])
    def test_required_yaw_angles(self, yaw, expected):
        assert yaw_to_rotation_z(yaw) == pytest.approx(expected)

    def test_conversion_is_deterministic(self):
        first = [world_to_three(i * 0.37, i * -0.11) for i in range(20)]
        second = [world_to_three(i * 0.37, i * -0.11) for i in range(20)]
        assert first == second

    def test_non_numeric_input_is_refused_not_nan(self):
        # A bad pose must not silently become a robot at the origin.
        assert world_to_three(float("nan"), 1.0) is None
        assert world_to_three(None, 1.0) is None
        assert yaw_to_rotation_z(float("nan")) == 0.0

    def test_coordinate_system_is_published(self):
        cs = TWIN_COORDINATE_SYSTEM
        assert cs["units"] == "metres"
        assert cs["up_axis"] == "z"
        assert cs["source_yaw_units"] == "radians"
        assert "three.y=-world.y" in cs["axis_map"]
        assert "rotation_z_deg" in cs["yaw_rule"]


class TestTwinState:
    """Scene assembly from a real MapSnapshot."""

    def test_full_snapshot_converts(self):
        d = build_twin_state(_snap()).to_dict()
        assert d["schema_version"] == TWIN_SCHEMA_VERSION
        assert d["source"] == SIMULATION
        assert d["robot"]["position"] == [2.0, -3.0, 0.0]
        assert d["robot"]["rotation_z_deg"] == pytest.approx(-90.0)
        assert d["goal"]["position"] == [4.0, -1.5, 0.0]
        assert len(d["route"]) == 3
        assert len(d["waypoints"]) == 2
        assert len(d["zones"]) == 1
        assert d["floor"]["available"] is True

    def test_empty_snapshot_is_valid(self):
        d = build_twin_state(MapSnapshot()).to_dict()
        assert d["robot"] is None and d["goal"] is None
        assert d["route"] == [] and d["path"] == [] and d["hazards"] == []
        assert d["floor"]["available"] is False
        assert d["source"] == UNAVAILABLE

    def test_missing_robot_does_not_invent_one(self):
        # The origin is the dock — a real place. Never park a robot there.
        d = build_twin_state(_snap(robot=None)).to_dict()
        assert d["robot"] is None

    def test_missing_goal_is_none(self):
        assert build_twin_state(_snap(goal=None)).to_dict()["goal"] is None

    def test_empty_route_and_path(self):
        d = build_twin_state(_snap(route=(), path=())).to_dict()
        assert d["route"] == [] and d["path"] == []

    def test_path_is_the_bounded_server_trail_not_browser_history(self):
        d = build_twin_state(_snap(path=(MapPoint(i, i) for i in range(5)))).to_dict()
        assert len(d["path"]) == 5
        assert d["path"][0] == [0.0, 0.0, 0.0]

    def test_unavailable_source_is_reported_as_unavailable(self):
        d = build_twin_state(MapSnapshot(source=UNAVAILABLE)).to_dict()
        assert d["source"] == UNAVAILABLE

    def test_live_source_is_preserved(self):
        d = build_twin_state(_snap(source=LIVE)).to_dict()
        assert d["source"] == LIVE

    def test_payload_is_json_serialisable(self):
        json.dumps(build_twin_state(_snap()).to_dict())

    def test_conversion_is_deterministic(self):
        a = build_twin_state(_snap()).to_dict()
        b = build_twin_state(_snap()).to_dict()
        assert a == b


class TestRobotModel:
    def test_model_has_chassis_four_wheels_camera_and_mount(self):
        m = robot_model()
        assert m["forward_axis"] == "+x"
        assert len(m["wheels"]) == 4
        assert m["chassis"]["size"][0] > 0
        assert m["camera"]["position"][0] > 0  # front face
        # A mount is drawn, but no manipulator is claimed to exist.
        assert m["manipulator_mount"]["implemented"] is False

    def test_wheels_sit_at_the_chassis_corners(self):
        m = robot_model()
        xs = sorted({round(w["position"][0], 6) for w in m["wheels"]})
        ys = sorted({round(w["position"][1], 6) for w in m["wheels"]})
        assert len(xs) == 2 and len(ys) == 2
        assert m["forward_axis"] == "+x"

    def test_model_contains_no_wall_clock_values(self):
        # Determinism: the model must not embed a timestamp.
        assert "timestamp" not in robot_model()


class TestHazardPlacement:
    """The C5/C9 rule, enforced again at the 3D boundary."""

    def test_world_location_hazard_is_placed(self):
        hz = MapHazard("FIRE", "CRITICAL", 0.88, "camera_front",
                       5.0, -2.0, 123.0, "evt-1")
        d = build_twin_state(_snap(hazards=(hz,))).to_dict()
        assert len(d["hazards"]) == 1
        placed = d["hazards"][0]
        assert placed["position"] == [5.0, 2.0, 0.0]  # world y negated
        assert placed["kind"] == "FIRE"
        assert placed["confidence"] == 0.88
        assert placed["source"] == "camera_front"
        assert placed["critical"] is True

    def test_confidence_is_preserved_not_rescaled(self):
        hz = MapHazard("SMOKE", "WARNING", 0.84, "camera_rear", 1.0, 1.0)
        d = build_twin_state(_snap(hazards=(hz,))).to_dict()
        assert d["hazards"][0]["confidence"] == 0.84

    def test_image_space_only_hazard_is_never_placed(self):
        """A bbox is image space. It must reach the 3D view only as unplaced."""
        unlocated = ({"kind": "PERSON", "severity": "WARNING",
                      "confidence": 0.91, "source": "camera_front",
                      "reason": "image-space evidence: no world location",
                      "metadata": {"bbox": [10, 20, 50, 90]}},)
        d = build_twin_state(_snap(hazards=(), unlocated=unlocated)).to_dict()
        assert d["hazards"] == []
        assert len(d["unlocated"]) == 1
        rec = d["unlocated"][0]
        assert "x" not in rec and "y" not in rec
        assert "image-space" in rec["reason"]

    def test_hazard_with_missing_confidence_is_allowed(self):
        hz = MapHazard("OBSTACLE", "WARNING", None, "zones", 1.0, 1.0)
        d = build_twin_state(_snap(hazards=(hz,))).to_dict()
        assert d["hazards"][0]["confidence"] is None

    def test_unknown_hazard_kind_is_still_placed_verbatim(self):
        hz = MapHazard("SOMETHING_NEW", "WARNING", 0.5, "ext", 1.0, 1.0)
        d = build_twin_state(_snap(hazards=(hz,))).to_dict()
        assert d["hazards"][0]["kind"] == "SOMETHING_NEW"

    def test_non_emergency_severity_is_not_marked_critical(self):
        hz = MapHazard("OBSTACLE", "WARNING", 0.6, "ext", 1.0, 1.0)
        d = build_twin_state(_snap(hazards=(hz,))).to_dict()
        assert d["hazards"][0]["critical"] is False


class TestSafetyIsDisplayOnly:
    """Safety state may change presentation. It must never act."""

    @pytest.mark.parametrize("action,estop", [
        ("PROCEED", False), ("STOP", False), ("WAIT", False), (None, True),
    ])
    def test_safety_state_is_carried_through(self, action, estop):
        snap = _snap(safety=MapSafety("NORMAL", action, estop, None, False,
                                     SIMULATION))
        sf = build_twin_state(snap).to_dict()["safety"]
        assert sf["action"] == action
        assert sf["emergency_stop"] is estop

    def test_twin_builds_no_robot_manager_and_no_commands(self):
        """Static guarantee: the twin module cannot reach an actuator.

        If this module ever imported RobotManager, Navigation, a motor driver,
        the serial transport or GPIO, the twin would have a control path.
        """
        import inspect
        from amr.map import twin
        source = inspect.getsource(twin)
        for banned in ("robot_manager", "RobotManager", "serial", "gpio",
                       "pwm", "dispatch(", "MotorDriver", "ArduinoSerial",
                       "set_speed", "Navigator", "SafetyManager"):
            assert banned not in source, f"twin must not reference {banned}"


class TestRendererDeclaration:
    def test_renderer_is_dependency_free(self):
        r = build_twin_state(_snap()).to_dict()["renderer"]
        assert r["backend"] == "webgl"
        assert r["library"] is None

    def test_geometry_is_labelled_schematic(self):
        d = build_twin_state(_snap()).to_dict()
        assert d["geometry_disclaimer"] == GEOMETRY_DISCLAIMER
        assert "no surveyed" in d["geometry_disclaimer"]
        # The floor reports its provenance: data extent, not a building survey.
        assert d["floor"]["source"] == "data-extent"
        assert "not a surveyed" in d["floor"]["note"]


