"""C12 — mission monitoring tests.

The headline here is not new UI, it is that the **mission telemetry section had
never worked**. Three defects in ``TelemetryCollector._mission()`` meant it
always reported ``UNAVAILABLE``:

1. ``WarehouseTaskManager.status()`` returns a ``ManagerStatus`` object, but
   the reader tested ``isinstance(data, dict)`` and bailed out.
2. The real key is ``current``, not ``current_task``, so the active task would
   have been dropped even from a dict.
3. ``mission_id`` was read but no such key ever existed.

These tests drive the **real** ``WarehouseTaskManager`` through the real
warehouse scenario, so the fix is proven against the actual runtime rather than
a hand-written double that could encode the same wrong assumptions.
"""

from __future__ import annotations

import pytest

from amr.warehouse import WarehouseTaskManager
from amr.telemetry import build_console_state, mission_phase
from amr.telemetry.collector import TelemetryCollector
from amr.utils.config import load_config

PICK_PHASE = "NAVIGATE"


# --------------------------------------------------------------------------- #
# Fixtures — the real stack, not a double
# --------------------------------------------------------------------------- #
@pytest.fixture
def runtime(config_dir):
    """The real mock robot + navigator + task manager from the real config."""
    from amr.main import build_navigator, build_warehouse
    from amr.robot import RobotManager
    config = load_config(config_dir)
    mgr, transport = RobotManager.create_mock(config)
    # Expose the recording transport so read-only assertions can inspect it,
    # exactly as the web fixtures do.
    mgr.test_transport = transport
    mgr.start()
    nav = build_navigator(mgr, config)
    wh = build_warehouse(mgr, config, nav)
    assert wh is not None, "warehouse layer must be enabled in the test config"
    wh._mission_id = "test-mission"
    collector = TelemetryCollector(mgr, navigator=nav, warehouse=wh,
                                   simulated=True)
    try:
        yield mgr, nav, wh, collector
    finally:
        mgr.shutdown()


def _run_to_completion(mgr, wh, collector, limit=4000):
    """Drive the real scenario, recording every distinct mission phase seen."""
    seen = []
    for _ in range(limit):
        mgr.tick()
        wh.process(dt=0.05)
        mission = build_console_state(collector.snapshot())["mission"]
        key = (mission["phase"], mission["current_task_type"],
               mission["destination"])
        if not seen or seen[-1][0] != key:
            seen.append((key, mission))
        if wh.queue_empty() and mission["current_task"] is None:
            break
    return seen


# --------------------------------------------------------------------------- #
# The three defects this milestone fixed
# --------------------------------------------------------------------------- #
class TestMissionSectionWasBroken:
    def test_manager_status_object_is_accepted(self, runtime):
        """Defect 1: status() returns a ManagerStatus object, not a dict."""
        from amr.warehouse import ManagerStatus
        mgr, nav, wh, collector = runtime
        assert isinstance(wh.status(), ManagerStatus)
        assert not isinstance(wh.status(), dict)
        mission = collector._mission()
        # The whole point: it must NOT fall back to UNAVAILABLE.
        assert mission.source.value == "SIMULATION"

    def test_current_task_is_not_dropped(self, runtime):
        """Defect 2: the key is `current`, not `current_task`."""
        mgr, nav, wh, collector = runtime
        wh.submit_move("shelf_a")
        wh.process(dt=0.05)
        mission = collector._mission()
        assert mission.current_task is not None
        assert mission.current_task_type == "MOVE"
        assert mission.current_task_status

    def test_mission_id_is_reported(self, runtime):
        """Defect 3: mission_id was read but never produced."""
        mgr, nav, wh, collector = runtime
        assert collector._mission().mission_id == "test-mission"

    def test_idle_manager_is_available_not_unavailable(self, runtime):
        """An idle manager is real data, so it must not read as unavailable."""
        mgr, nav, wh, collector = runtime
        mission = collector._mission()
        assert mission.source.value == "SIMULATION"
        assert mission.current_task is None
        assert mission.total_tasks == 0
        assert mission.mission_progress is None   # no work yet -> unknown, not 0


class TestMissionFields:
    def test_destination_comes_from_the_task(self, runtime):
        mgr, nav, wh, collector = runtime
        wh.submit_pick("shelf_a", payload_id="SKU-1")
        wh.process(dt=0.05)
        assert collector._mission().destination == "shelf_a"

    def test_destination_is_none_when_idle(self, runtime):
        mgr, nav, wh, collector = runtime
        assert collector._mission().destination is None

    def test_total_tasks_counts_real_work(self, runtime):
        mgr, nav, wh, collector = runtime
        wh.submit_pick("shelf_a", payload_id="SKU-1")
        wh.submit_place("station", payload_id="SKU-1")
        wh.submit_return_to_dock()
        assert collector._mission().total_tasks == 3

    def test_mission_progress_tracks_completion(self, runtime):
        mgr, nav, wh, collector = runtime
        wh.submit_pick("shelf_a", payload_id="SKU-1")
        wh.submit_place("station", payload_id="SKU-1")
        wh.submit_return_to_dock()
        _run_to_completion(mgr, wh, collector)
        final = collector._mission()
        assert final.completed_tasks == 3
        assert final.mission_progress == pytest.approx(1.0)

    def test_progress_is_none_before_any_work_is_queued(self, runtime):
        mgr, nav, wh, collector = runtime
        assert collector._mission().mission_progress is None

    def test_new_fields_are_optional_and_default_safe(self):
        """A C12-unaware reader must still work: the new fields default."""
        from amr.telemetry import MissionTelemetry
        m = MissionTelemetry()
        d = m.to_dict()
        for key in ("destination", "total_tasks", "mission_progress",
                    "task_progress"):
            assert key in d
        assert d["destination"] is None and d["mission_progress"] is None


# --------------------------------------------------------------------------- #
# Phase derivation — from real state, never invented
# --------------------------------------------------------------------------- #
def _mission(**over):
    base = {"source": "SIMULATION", "current_task": "t1",
            "current_task_type": "PICK", "current_task_status": "RUNNING",
            "destination": "shelf_a", "task_progress": 0.2,
            "completed_tasks": 0, "mission_progress": 0.0, "total_tasks": 3}
    base.update(over)
    return base


class TestMissionPhase:
    @pytest.mark.parametrize("task_type,progress,expected", [
        ("PICK", 0.2, "NAVIGATE"),
        ("PICK", 0.95, "PICKUP"),
        ("PLACE", 0.2, "NAVIGATE"),
        ("PLACE", 0.95, "DROP"),
        ("MOVE", 0.2, "NAVIGATE"),
        ("MOVE", 0.95, "ARRIVE"),
        ("RETURN_TO_DOCK", 0.0, "RETURN"),
        ("RETURN_TO_DOCK", 0.99, "RETURN"),
    ])
    def test_phase_follows_task_and_progress(self, task_type, progress, expected):
        assert mission_phase(_mission(current_task_type=task_type,
                                      task_progress=progress)) == expected

    def test_unknown_progress_is_never_treated_as_arrival(self):
        """A missing measurement must not be read as success."""
        assert mission_phase(_mission(task_progress=None)) == PICK_PHASE

    def test_nan_progress_is_not_arrival(self):
        assert mission_phase(_mission(task_progress=float("nan"))) == PICK_PHASE

    def test_no_task_and_no_work_is_idle(self):
        assert mission_phase(_mission(current_task=None,
                                      current_task_type=None,
                                      completed_tasks=0)) == "IDLE"

    def test_finished_run_is_completed(self):
        assert mission_phase(_mission(current_task=None,
                                      current_task_type=None,
                                      completed_tasks=3)) == "COMPLETED"

    @pytest.mark.parametrize("action,estop,expected", [
        ("PROCEED", False, PICK_PHASE),
        ("TURN", False, "AVOID"),
        ("REPLAN", False, "AVOID"),
        ("STOP", False, "HELD"),
        ("WAIT", False, "HELD"),
        (None, True, "EMERGENCY"),
    ])
    def test_safety_overrides_the_narrative(self, action, estop, expected):
        """C6 avoidance and E-stop outrank the mission story."""
        safety = {"action": action, "emergency_stop": estop}
        assert mission_phase(_mission(), safety=safety) == expected

    def test_safety_beats_completion(self):
        safety = {"action": "STOP", "emergency_stop": False}
        assert mission_phase(_mission(current_task=None,
                                      current_task_type=None,
                                      completed_tasks=3),
                             safety=safety) == "HELD"

    def test_unavailable_mission_has_no_phase(self):
        assert mission_phase({"source": "UNAVAILABLE"}) == "UNAVAILABLE"

    def test_unavailable_source_wins_over_task_fields(self):
        assert mission_phase(_mission(source="UNAVAILABLE")) == "UNAVAILABLE"

    def test_console_exposes_phase_next_to_raw_task_fields(self):
        """The derived phase must never hide the runtime's own words."""
        console = build_console_state({"mission": _mission()})
        m = console["mission"]
        assert m["phase"] == PICK_PHASE
        assert m["current_task_type"] == "PICK"
        assert m["current_task_status"] == "RUNNING"


# --------------------------------------------------------------------------- #
# End-to-end: the real warehouse scenario, observed through the console
# --------------------------------------------------------------------------- #
class TestMissionEndToEnd:
    def test_full_mission_reports_every_stage(self, runtime):
        mgr, nav, wh, collector = runtime
        wh.submit_pick("shelf_a", payload_id="SKU-1")
        wh.submit_place("station", payload_id="SKU-1")
        wh.submit_return_to_dock()
        seen = _run_to_completion(mgr, wh, collector)
        types = [k[1] for k, _ in seen]
        assert "PICK" in types and "PLACE" in types
        assert "RETURN_TO_DOCK" in types
        # It really finished, and the console agrees with the manager.
        assert wh.queue_empty()
        final = build_console_state(collector.snapshot())["mission"]
        assert final["phase"] == "COMPLETED"
        assert final["completed_tasks"] == 3
        assert final["mission_progress"] == pytest.approx(1.0)

    def test_destinations_follow_the_scenario(self, runtime):
        mgr, nav, wh, collector = runtime
        wh.submit_pick("shelf_a", payload_id="SKU-1")
        wh.submit_place("station", payload_id="SKU-1")
        wh.submit_return_to_dock()
        seen = _run_to_completion(mgr, wh, collector)
        dests = {k[1]: k[2] for k, _ in seen if k[1]}
        assert dests["PICK"] == "shelf_a"
        assert dests["PLACE"] == "station"
        assert dests["RETURN_TO_DOCK"] == "dock"

    def test_progress_advances_monotonically(self, runtime):
        mgr, nav, wh, collector = runtime
        wh.submit_pick("shelf_a", payload_id="SKU-1")
        wh.submit_place("station", payload_id="SKU-1")
        wh.submit_return_to_dock()
        values = []
        for _ in range(4000):
            mgr.tick()
            wh.process(dt=0.05)
            m = collector._mission().mission_progress
            if m is not None and (not values or values[-1] != m):
                values.append(m)
            if wh.queue_empty() and collector._mission().current_task is None:
                break
        assert values == sorted(values), "mission progress must not go backwards"
        assert values[-1] == pytest.approx(1.0)

    def test_task_progress_tracks_travel(self, runtime):
        mgr, nav, wh, collector = runtime
        wh.submit_move("shelf_a")
        seen_progress = []
        for _ in range(2000):
            mgr.tick()
            wh.process(dt=0.05)
            p = collector._mission().task_progress
            if p is not None and (not seen_progress or seen_progress[-1] != p):
                seen_progress.append(p)
            if wh.queue_empty() and collector._mission().current_task is None:
                break
        # Real travel means the number actually moved.
        assert len(seen_progress) > 1
        assert seen_progress == sorted(seen_progress)


# --------------------------------------------------------------------------- #
# Robustness + safety
# --------------------------------------------------------------------------- #
class TestMissionRobustness:
    def test_status_returning_plain_dict_still_works(self):
        """A hand-rolled warehouse double must keep working."""
        class Legacy:
            def status(self):
                return {"current_task": "t9", "current_task_type": "pick",
                        "current_task_status": "running", "queued": 0,
                        "completed": 1, "failed": 0}
        m = TelemetryCollector(warehouse=Legacy(), simulated=True)._mission()
        assert m.current_task == "t9"
        assert m.current_task_type == "PICK"
        assert m.mission_id is None

    def test_status_raising_is_contained(self):
        class Boom:
            def status(self):
                raise RuntimeError("boom")
        m = TelemetryCollector(warehouse=Boom(), simulated=True)._mission()
        assert m.source.value == "UNAVAILABLE"

    def test_non_numeric_counts_do_not_crash_the_snapshot(self):
        """A bad count must not take the whole telemetry snapshot down."""
        class Bad:
            def status(self):
                return {"mode": "IDLE", "queued": "not-a-number",
                        "completed": None, "failed": object(),
                        "current": None, "pose": {}}
        snap = TelemetryCollector(warehouse=Bad(), simulated=True).snapshot()
        assert snap["mission"]["queued"] == 0
        assert snap["mission"]["completed_tasks"] == 0

    def test_garbage_status_type_is_unavailable(self):
        class Weird:
            def status(self):
                return "not a mapping"
        m = TelemetryCollector(warehouse=Weird(), simulated=True)._mission()
        assert m.source.value == "UNAVAILABLE"

    def test_console_reports_mission_available_when_wired(self, runtime):
        mgr, nav, wh, collector = runtime
        console = build_console_state(collector.snapshot())
        assert console["mission"]["source"] == "SIMULATION"
        assert console["mission"]["availability"] == "AVAILABLE"
        assert console["mission"]["state"] == "IDLE"
        assert "mission" not in console["system"]["degraded"]

    def test_mission_reads_never_actuate(self, runtime):
        """Reading the mission section must not command the robot."""
        from conftest import NoActuation
        mgr, nav, wh, collector = runtime
        transport = mgr.test_transport
        with NoActuation(transport):
            for _ in range(5):
                collector._mission()
                build_console_state(collector.snapshot())


# --------------------------------------------------------------------------- #
# The opt-in mission demo is mock-only
# --------------------------------------------------------------------------- #
class TestMissionDemoSafetyGate:
    def test_refused_against_hardware(self, config_dir):
        """--mission-demo commands autonomous motion: never on real hardware."""
        import argparse
        from amr.main import run_web
        from amr.robot import RobotManager
        from amr.utils.config import load_config
        config = load_config(config_dir)
        mgr, _ = RobotManager.create_mock(config)
        args = argparse.Namespace(mock=False, mission_demo=True,
                                  host="127.0.0.1", port=0)
        with pytest.raises(SystemExit) as exc:
            run_web(mgr, config, args)
        assert "mock-only" in str(exc.value)

    def test_mission_id_travels_through_the_public_constructor(self, config_dir):
        """The label is supplied by the caller, never invented or poked in."""
        from amr.main import build_navigator, build_warehouse
        from amr.robot import RobotManager
        from amr.utils.config import load_config
        config = load_config(config_dir)
        mgr, _ = RobotManager.create_mock(config)
        nav = build_navigator(mgr, config)
        wh = build_warehouse(mgr, config, nav, mission_id="labelled")
        assert wh is not None
        assert wh.status().mission_id == "labelled"

    def test_mission_id_defaults_to_none_not_a_fake(self, config_dir):
        from amr.main import build_navigator, build_warehouse
        from amr.robot import RobotManager
        from amr.utils.config import load_config
        config = load_config(config_dir)
        mgr, _ = RobotManager.create_mock(config)
        nav = build_navigator(mgr, config)
        wh = build_warehouse(mgr, config, nav)
        # Honest absence: no label configured means no label shown.
        assert wh.status().mission_id is None




