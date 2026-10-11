"""C19 — spatial heat map (hazard density + traffic density).

Three properties matter and are pinned here: the two grids share one stable
extent so they can be compared, nothing is silently dropped (an unplaceable or
out-of-extent sample is *counted*, never discarded), and the module is strictly
read-only.

Orientation gets its own tests. The payload publishes ``cell_m``, the extent and
``row_order`` precisely so a client can map a world point to a cell without
guessing, and the orientation is the part that is easy to get wrong: a
vertically mirrored heat map looks entirely plausible and would never fail a
"does it render" test. ``cell_of`` below is that published contract written out,
so these tests check the module honours what it publishes.
"""

from __future__ import annotations

import inspect
import json
from typing import Optional, Tuple

import pytest
from conftest import NoActuation

from amr.hazard.types import (
    HazardEvent,
    HazardKind,
    HazardLocation,
    HazardSeverity,
    HazardState,
)
from amr.map import (
    DEFAULT_CELL_M,
    HEATMAP_SCHEMA_VERSION,
    SEVERITY_WEIGHTS,
    MapPoint,
    MapRobot,
    MapSnapshot,
    MapStatic,
    MapWaypoint,
    build_heatmap_state,
    severity_weight,
)
from amr.map.heatmap import grid_geometry
from amr.map.snapshot import SIMULATION, UNAVAILABLE

#: The configured warehouse: two waypoints spanning 4 x 3 m, so the derived
#: extent (with the default 0.5 m margin) is exactly -0.5..4.5 x -0.5..3.5.
_DOCK = (0.0, 0.0)
_FAR = (4.0, 3.0)


def _snap(**kw) -> MapSnapshot:
    """A populated snapshot; override any field per test."""
    base = {
        "robot": MapRobot(0.0, 0.0, 0.0, SIMULATION),
        "path": (),
        "zones": (),
        "static": MapStatic(
            waypoints=(
                MapWaypoint("dock", _DOCK[0], _DOCK[1], SIMULATION),
                MapWaypoint("station", _FAR[0], _FAR[1], SIMULATION),
            ),
            source=SIMULATION,
        ),
        "source": SIMULATION,
    }
    base.update(kw)
    return MapSnapshot(**base)


def _empty_grid(snapshot: Optional[MapSnapshot] = None):
    """The traffic grid of a snapshot with no path, for its geometry."""
    return build_heatmap_state(snapshot or _snap(), ()).traffic


def cell_of(grid, x: float, y: float) -> Tuple[int, int]:
    """The published contract: ``col`` from x, ``row`` from y, row 0 = y_min."""
    col = int((x - grid.x_min) // grid.cell_m)
    row = int((y - grid.y_min) // grid.cell_m)
    return col, row


def _event(x, y, severity=HazardSeverity.WARNING, kind=HazardKind.GAS) -> HazardEvent:
    return HazardEvent(
        event_id=f"ev-{x}-{y}",
        kind=kind,
        severity=severity,
        state=HazardState.WARNING,
        location=HazardLocation(x=x, y=y),
    )


# --------------------------------------------------------------------------- #
# Extent / geometry
# --------------------------------------------------------------------------- #
class TestGridGeometry:
    def test_no_bounds_means_no_grid(self):
        assert grid_geometry(None) is None
        assert grid_geometry({}) is None

    def test_degenerate_bounds_are_refused(self):
        assert grid_geometry({"x_min": 1.0, "x_max": 1.0,
                              "y_min": 0.0, "y_max": 2.0}) is None

    def test_malformed_bounds_are_refused(self):
        assert grid_geometry({"x_min": "a", "x_max": 1.0,
                              "y_min": 0.0, "y_max": 2.0}) is None
        assert grid_geometry({"x_min": 0.0, "y_min": 0.0}) is None

    def test_the_extent_is_the_config_geometry_plus_the_margin(self):
        """Pinned, because every other test's indices derive from it."""
        grid = _empty_grid()
        assert grid.cell_m == DEFAULT_CELL_M
        assert (grid.x_min, grid.y_min) == (-0.5, -0.5)
        assert (grid.x_max, grid.y_max) == (4.5, 3.5)
        assert (grid.cols, grid.rows) == (20, 16)

    def test_grid_is_snapped_outwards_to_whole_cells(self):
        """The published extent must fully contain the geometry it covers."""
        grid = _empty_grid()
        assert grid.x_max - grid.x_min == pytest.approx(grid.cols * grid.cell_m)
        assert grid.y_max - grid.y_min == pytest.approx(grid.rows * grid.cell_m)

    def test_both_grids_share_one_geometry(self):
        """They are compared side by side, so they must be directly comparable."""
        state = build_heatmap_state(_snap(path=(MapPoint(1.0, 1.0),)), ())
        assert state.hazard.cell_m == state.traffic.cell_m
        assert state.hazard.cols == state.traffic.cols
        assert state.hazard.rows == state.traffic.rows
        assert state.hazard.to_dict()["extent"] == state.traffic.to_dict()["extent"]

    def test_invalid_cell_size_falls_back_to_the_default(self):
        cols, _, cell, _, _ = grid_geometry(
            {"x_min": 0.0, "x_max": 4.0, "y_min": 0.0, "y_max": 3.0}, 0)
        assert cell == DEFAULT_CELL_M
        assert cols >= 1


# --------------------------------------------------------------------------- #
# Traffic grid
# --------------------------------------------------------------------------- #
class TestTrafficGrid:
    def test_every_path_point_is_one_sample(self):
        path = tuple(MapPoint(0.5 + i * 0.15, 0.5) for i in range(20))
        state = build_heatmap_state(_snap(path=path), ())
        assert state.traffic.samples == 20
        assert state.traffic.total == pytest.approx(20.0)

    def test_repeated_points_accumulate_in_one_cell(self):
        """A cell's value is time spent there, so repeats must add up."""
        path = tuple(MapPoint(0.05, 0.05) for _ in range(7))
        state = build_heatmap_state(_snap(path=path), ())
        assert state.traffic.max_value == pytest.approx(7.0)
        assert state.traffic.samples == 7

    def test_empty_path_yields_a_zero_grid_and_says_so(self):
        state = build_heatmap_state(_snap(path=()), ())
        assert state.traffic.samples == 0
        assert state.traffic.total == 0.0
        assert all(v == 0.0 for v in state.traffic.cells)
        assert any("no travelled path" in n for n in state.notes)

    def test_row_zero_is_the_lowest_y(self):
        """y-up: row 0 is the BOTTOM row, and the payload says so."""
        grid = _empty_grid()
        bottom = grid.y_min + 0.05
        state = build_heatmap_state(_snap(path=(MapPoint(0.05, bottom),)), ())
        col, row = cell_of(grid, 0.05, bottom)
        assert row == 0
        assert state.traffic.at(col, 0) == pytest.approx(1.0)
        assert state.traffic.at(col, grid.rows - 1) == 0.0
        assert "y_min" in state.traffic.to_dict()["row_order"]

    def test_the_highest_y_lands_in_the_last_row(self):
        grid = _empty_grid()
        top = grid.y_max - 0.05
        state = build_heatmap_state(_snap(path=(MapPoint(0.05, top),)), ())
        col, row = cell_of(grid, 0.05, top)
        assert row == grid.rows - 1
        assert state.traffic.at(col, grid.rows - 1) == pytest.approx(1.0)
        assert state.traffic.at(col, 0) == 0.0

    def test_a_point_maps_to_the_cell_the_contract_predicts(self):
        grid = _empty_grid()
        x, y = 2.3, 1.7
        state = build_heatmap_state(_snap(path=(MapPoint(x, y),)), ())
        col, row = cell_of(grid, x, y)
        assert state.traffic.at(col, row) == pytest.approx(1.0)
        assert state.traffic.samples == 1


# --------------------------------------------------------------------------- #
# Hazard grid
# --------------------------------------------------------------------------- #
class TestHazardGrid:
    def test_located_events_are_placed(self):
        grid = _empty_grid()
        x, y = 0.05, 0.05
        state = build_heatmap_state(_snap(), (_event(x, y),))
        col, row = cell_of(grid, x, y)
        assert state.hazard.samples == 1
        assert state.hazard.at(col, row) == pytest.approx(
            SEVERITY_WEIGHTS["WARNING"])

    def test_severity_weighting_is_applied(self):
        assert severity_weight(HazardSeverity.INFO) == 1.0
        assert severity_weight(HazardSeverity.WARNING) == 2.0
        assert severity_weight(HazardSeverity.CRITICAL) == 4.0

    def test_critical_dominates_a_warning(self):
        """The point of the weighting: a critical cell must not read as mild."""
        mild = build_heatmap_state(_snap(), (_event(1.0, 1.0,
                                                    HazardSeverity.WARNING),))
        severe = build_heatmap_state(_snap(), (_event(1.0, 1.0,
                                                      HazardSeverity.CRITICAL),))
        assert severe.hazard.total > mild.hazard.total
        assert severe.hazard.total == pytest.approx(2 * mild.hazard.total)

    def test_unknown_severity_does_not_vanish(self):
        """An unrecognised severity must still show up on the picture."""
        assert severity_weight("SOMETHING_NEW") == 2.0
        assert severity_weight(None) == 2.0

    def test_events_without_a_location_are_never_placed(self):
        """The C5 rule: no world location means no warehouse coordinate."""
        blind = HazardEvent(event_id="ev-blind", kind=HazardKind.VISION,
                            severity=HazardSeverity.CRITICAL,
                            state=HazardState.STOP, location=None)
        state = build_heatmap_state(_snap(), (blind,))
        assert state.hazard.samples == 0
        assert state.hazard.unlocated == 1
        assert state.hazard.total == 0.0
        assert any("no world location" in n for n in state.notes)

    def test_dict_events_are_accepted_too(self):
        """``HazardEventLog.read_events`` returns dicts, not objects."""
        as_dict = _event(1.0, 1.0, HazardSeverity.CRITICAL).to_dict()
        state = build_heatmap_state(_snap(), (as_dict,))
        assert state.hazard.samples == 1
        assert state.hazard.total == pytest.approx(4.0)

    def test_an_event_whose_location_lacks_coordinates_is_unlocated(self):
        broken = {"event_id": "x", "kind": "GAS", "severity": "WARNING",
                  "location": {"theta": 1.0}}
        state = build_heatmap_state(_snap(), (broken,))
        assert state.hazard.samples == 0
        assert state.hazard.unlocated == 1

    def test_no_events_yields_a_zero_grid(self):
        state = build_heatmap_state(_snap(), ())
        assert state.hazard.samples == 0
        assert all(v == 0.0 for v in state.hazard.cells)


# --------------------------------------------------------------------------- #
# Honesty
# --------------------------------------------------------------------------- #
class TestHonesty:
    def test_no_configured_geometry_means_no_grid_at_all(self):
        """Better to draw nothing than to invent a floor plan."""
        bare = MapSnapshot(static=MapStatic(), source=UNAVAILABLE)
        state = build_heatmap_state(bare, (_event(0.0, 0.0),))
        assert state.hazard is None and state.traffic is None
        assert state.source == UNAVAILABLE
        assert any("no configured warehouse geometry" in n for n in state.notes)

    def test_out_of_extent_samples_are_counted_not_dropped(self):
        far = (MapPoint(50.0, 50.0), MapPoint(1.0, 1.0))
        state = build_heatmap_state(_snap(path=far), ())
        assert state.traffic.clipped == 1
        assert state.traffic.samples == 1
        assert any("clipped" in n for n in state.notes)

    def test_out_of_extent_hazards_are_counted_too(self):
        state = build_heatmap_state(_snap(), (_event(50.0, 50.0),))
        assert state.hazard.clipped == 1
        assert state.hazard.samples == 0

    def test_source_is_inherited_from_the_snapshot(self):
        assert build_heatmap_state(_snap(), ()).source == SIMULATION

    def test_the_extent_does_not_move_with_the_robot(self):
        """A frame that rescales every poll cannot be compared with itself.

        The robot's pose is deliberately excluded from the extent: it changes
        every tick, so including it would slide the grid under the data.
        """
        at_origin = _snap(robot=MapRobot(0.0, 0.0, 0.0, SIMULATION))
        far_away = _snap(robot=MapRobot(3.9, 2.9, 1.0, SIMULATION))
        a = build_heatmap_state(at_origin, ()).hazard.to_dict()
        b = build_heatmap_state(far_away, ()).hazard.to_dict()
        assert a["extent"] == b["extent"]
        assert a["cols"] == b["cols"] and a["rows"] == b["rows"]

    def test_the_data_does_not_rescale_the_extent_either(self):
        near = build_heatmap_state(_snap(path=(MapPoint(1.0, 1.0),)), ())
        far = build_heatmap_state(_snap(path=(MapPoint(2.5, 2.5),)), ())
        assert near.hazard.to_dict()["extent"] == far.hazard.to_dict()["extent"]

    def test_note_explains_a_wholly_unlocated_hazard_picture(self):
        blind = HazardEvent(event_id="b", kind=HazardKind.FIRE,
                            severity=HazardSeverity.CRITICAL,
                            state=HazardState.EMERGENCY, location=None)
        state = build_heatmap_state(_snap(), (blind,))
        assert state.hazard.samples == 0
        assert state.notes, "an empty hazard picture must be explained"


# --------------------------------------------------------------------------- #
# Payload shape
# --------------------------------------------------------------------------- #
class TestPayload:
    def test_payload_is_json_serialisable(self):
        payload = build_heatmap_state(_snap(path=(MapPoint(1.0, 1.0),)),
                                      (_event(0.5, 0.5),)).to_dict()
        assert json.loads(json.dumps(payload)) == payload

    def test_payload_publishes_the_contract_a_client_needs(self):
        payload = build_heatmap_state(_snap(), ()).to_dict()
        assert payload["schema_version"] == HEATMAP_SCHEMA_VERSION
        assert payload["units"] == "metres"
        assert payload["y_axis"] == "up"
        # Weights are published so a client never has to guess the convention.
        assert payload["severity_weights"] == SEVERITY_WEIGHTS
        for key in ("cols", "rows", "cell_m", "extent", "cells", "row_order",
                    "max_value", "total", "samples", "clipped", "source", "note"):
            assert key in payload["hazard"], f"hazard grid is missing {key}"

    def test_cells_length_matches_the_grid(self):
        payload = build_heatmap_state(_snap(), ()).to_dict()
        for name in ("hazard", "traffic"):
            grid = payload[name]
            assert len(grid["cells"]) == grid["cols"] * grid["rows"]

    def test_max_value_is_the_largest_cell(self):
        path = tuple(MapPoint(0.05, 0.05) for _ in range(5))
        grid = build_heatmap_state(_snap(path=path), ()).traffic
        assert grid.max_value == max(grid.cells)

    def test_at_is_safe_out_of_range(self):
        grid = build_heatmap_state(_snap(), ()).traffic
        assert grid.at(-1, 0) == 0.0
        assert grid.at(0, 10_000) == 0.0


# --------------------------------------------------------------------------- #
# Read-only guarantee
# --------------------------------------------------------------------------- #
class TestReadOnly:
    def test_the_module_cannot_reach_an_actuator(self):
        """Static guarantee, in the same spirit as the twin's."""
        from amr.map import heatmap
        source = inspect.getsource(heatmap)
        for banned in ("robot_manager", "RobotManager", "serial", "gpio",
                       "pwm", "dispatch(", "MotorDriver", "ArduinoSerial",
                       "set_speed", "Navigator", "SafetyManager"):
            assert banned not in source, f"heatmap must not reference {banned}"

    def test_building_a_heat_map_writes_nothing_to_the_transport(self, config_dir):
        """A view must not command the robot, proven against a real transport."""
        from amr.main import build_navigator
        from amr.robot import RobotManager
        from amr.utils.config import load_config

        config = load_config(config_dir)
        mgr, transport = RobotManager.create_mock(config)
        mgr.test_transport = transport
        try:
            mgr.start()
            nav = build_navigator(mgr, config)
            assert nav is not None
            with NoActuation(transport):
                state = build_heatmap_state(
                    _snap(path=(MapPoint(1.0, 1.0),)), (_event(0.5, 0.5),))
                assert state.traffic.samples == 1
                assert state.hazard.samples == 1
        finally:
            mgr.shutdown()
