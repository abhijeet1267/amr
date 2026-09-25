"""Tests for the warehouse layer (Phase 16) — the top of the AMR stack.

Covers, with no ROS and no hardware:

* :mod:`amr.warehouse.map` — ``WarehouseMap`` construction (dict / sequence
  forms), unknown-location errors, the default map, and the
  :func:`map_from_config` fallback.
* :mod:`amr.warehouse.tasks` — ``Task`` / ``TaskResult`` models, and the
  manipulator seam (``MockManipulator`` carry-at-most-one rules,
  ``NullManipulator``, factory, protocol conformance).
* :class:`~amr.warehouse.task_manager.WarehouseTaskManager` — submission
  validation and queue limits; the happy path (move, and a full
  pick -> place -> return-to-dock pipeline) driven through a real
  ``RobotManager.create_mock`` stack so every motion still passes the
  Layer-3 safety gate; and the safety interactions: e-stop / close-sensor
  pause + operator resume, link-loss blocking, and navigator failure
  marking a task FAILED while the rest of the queue keeps going.
"""

from __future__ import annotations

import dataclasses

import pytest

from amr.navigation import LocalNavigator, NavStatus, Pose
from amr.robot import RobotCommandError, RobotManager, RobotMode
from amr.utils.config import WarehouseConfig, load_config
from amr.warehouse import (
    Manipulator,
    MapError,
    ManagerStatus,
    MockManipulator,
    NullManipulator,
    QueueFullError,
    Task,
    TaskResult,
    TaskStatus,
    TaskType,
    WarehouseMap,
    WarehouseTaskManager,
    default_map,
    make_manipulator,
    map_from_config,
)

DT = 0.05


# =========================================================================== #
# Fixtures / helpers
# =========================================================================== #
@pytest.fixture
def app_config(config_dir):
    return load_config(config_dir)


@pytest.fixture
def stack(app_config):
    """Full offline stack: mock robot + gated navigator + warehouse manager.

    The navigator's ``command`` is :meth:`RobotManager.move`, i.e. the exact
    wiring used in the real stack — every wheel command passes the Layer-3
    safety gate, and a veto surfaces as a navigator failure.
    """
    mgr, transport = RobotManager.create_mock(app_config)
    mgr.start()
    nav = LocalNavigator(
        command=mgr.move,
        start_pose=Pose(0.0, 0.0, 0.0),
        wheel_base_m=app_config.warehouse.wheel_base_m,
        max_linear_speed=app_config.warehouse.task_speed,
        max_angular_speed=app_config.warehouse.turn_speed,
        max_pwm=app_config.robot.motors.max_speed,
    )
    wh = WarehouseTaskManager.create(app_config, mgr, nav)
    return mgr, transport, nav, wh


def run_to_empty(wh: WarehouseTaskManager, dt: float = DT, max_ticks: int = 3000):
    """Drive ``process`` until the queue drains; fail loudly if it never does."""
    st = None
    for _ in range(max_ticks):
        st = wh.process(dt)
        if wh.queue_empty():
            return st
    raise AssertionError(f"manager did not drain in {max_ticks} ticks: {st.to_dict()}")


# =========================================================================== #
# map.py
# =========================================================================== #
class TestWarehouseMap:
    def test_empty_map_raises(self):
        with pytest.raises(MapError):
            WarehouseMap({})

    def test_from_dict_mapping_form(self):
        m = WarehouseMap.from_dict({"a": {"x": 1.0, "y": 2.0, "theta": 0.5}})
        assert m.pose("a") == Pose(1.0, 2.0, 0.5)

    def test_from_dict_sequence_form_coerces_to_float(self):
        m = WarehouseMap.from_dict({"a": [1, 2, 0]})
        assert m.pose("a") == Pose(1.0, 2.0, 0.0)

    def test_from_dict_bad_sequence_length_raises(self):
        with pytest.raises(MapError):
            WarehouseMap.from_dict({"a": [1.0, 2.0]})

    def test_pose_unknown_raises_with_known_names(self):
        m = WarehouseMap.from_dict({"a": [0, 0, 0]})
        with pytest.raises(MapError, match="unknown location"):
            m.pose("b")

    def test_membership_len_and_iteration(self):
        m = WarehouseMap.from_dict({"a": [0, 0, 0], "b": [1, 1, 0]})
        assert m.has("a") and "b" in m and "c" not in m
        assert len(m) == 2
        assert sorted(m.names()) == ["a", "b"]
        assert sorted(m) == ["a", "b"]

    def test_default_map_layout(self):
        m = default_map()
        assert {"dock", "shelf_a", "shelf_b", "shelf_c", "station"} <= set(m)
        assert m.pose("dock") == Pose(0.0, 0.0, 0.0)

    def test_map_from_config_uses_config_locations(self):
        cfg = WarehouseConfig(dock="dock", locations={"x": (1.0, 2.0, 0.0)})
        m = map_from_config(cfg)
        assert len(m) == 1
        assert m.pose("x") == Pose(1.0, 2.0, 0.0)

    def test_map_from_config_falls_back_to_default(self):
        m = map_from_config(WarehouseConfig())
        ref = default_map()
        assert m.names() == ref.names()
        assert all(m.pose(n) == ref.pose(n) for n in m)


# =========================================================================== #
# tasks.py
# =========================================================================== #
class TestTaskModel:
    def test_defaults(self):
        t = Task(TaskType.MOVE, "shelf_a")
        assert t.status is TaskStatus.PENDING
        assert t.payload_id is None
        assert t.attempts == 0
        assert t.last_error is None
        assert t.task_id.startswith("task-")
        assert t.created_at > 0

    def test_ids_are_unique_and_sequential(self):
        a = Task(TaskType.MOVE, "a")
        b = Task(TaskType.MOVE, "b")
        assert a.task_id != b.task_id
        assert int(a.task_id.split("-")[1]) + 1 == int(b.task_id.split("-")[1])

    def test_to_dict(self):
        t = Task(TaskType.PICK, "shelf_a", "p1")
        d = t.to_dict()
        assert d["type"] == "pick"
        assert d["location"] == "shelf_a"
        assert d["payload_id"] == "p1"
        assert d["status"] == "pending"
        assert d["task_id"] == t.task_id

    def test_task_result_to_dict(self):
        r = TaskResult(task_id="task-0001", status=TaskStatus.DONE, error=None)
        assert r.to_dict() == {"task_id": "task-0001", "status": "done", "error": None}


class TestManipulators:
    def test_mock_pick_then_place_cycle(self):
        m = MockManipulator()
        assert m.pick("p1") is True
        assert m.has_payload() and m.payload == "p1"
        assert m.places == 0
        assert m.place("p1") is True
        assert m.places == 1
        assert not m.has_payload() and m.payload is None

    def test_mock_rejects_second_pick_while_carrying(self):
        m = MockManipulator()
        assert m.pick("p1") is True
        assert m.pick("p2") is False  # already carrying
        assert m.payload == "p1"
        assert m.picks == 1

    def test_mock_rejects_place_when_empty(self):
        m = MockManipulator()
        assert m.place("p1") is False
        assert m.places == 0

    def test_mock_reset_clears_payload_but_keeps_counters(self):
        m = MockManipulator()
        m.pick("p1")
        m.reset()
        assert m.payload is None
        assert (m.picks, m.places) == (1, 0)

    def test_null_manipulator_is_always_success_and_never_carries(self):
        m = NullManipulator()
        assert m.pick("p1") is True and m.place("p1") is True
        assert m.has_payload() is False
        m.reset()  # must not raise

    def test_make_manipulator_factory(self):
        assert isinstance(make_manipulator("null"), NullManipulator)
        assert isinstance(make_manipulator("mock"), MockManipulator)
        assert isinstance(make_manipulator(None), MockManipulator)
        assert isinstance(make_manipulator("gripper"), MockManipulator)

    def test_implementations_satisfy_protocol(self):
        assert isinstance(MockManipulator(), Manipulator)
        assert isinstance(NullManipulator(), Manipulator)


# =========================================================================== #
# TaskManager — submission & queries
# =========================================================================== #
class TestSubmission:
    def test_submit_move_returns_pending_task(self, stack):
        mgr, transport, nav, wh = stack
        t = wh.submit_move("shelf_a")
        assert isinstance(t, Task)
        assert t.task_type is TaskType.MOVE
        assert t.status is TaskStatus.PENDING
        assert wh.queue_size() == 1
        assert wh.pending() == [t]
        assert wh.queue_empty() is False

    def test_submit_pick_place_and_return(self, stack):
        mgr, transport, nav, wh = stack
        pick = wh.submit_pick("shelf_a", "p1")
        place = wh.submit_place("station", "p1")
        ret = wh.submit_return_to_dock()
        assert (pick.task_type, pick.location, pick.payload_id) == (TaskType.PICK, "shelf_a", "p1")
        assert (place.task_type, place.location, place.payload_id) == (TaskType.PLACE, "station", "p1")
        assert ret.task_type is TaskType.RETURN_TO_DOCK
        assert ret.location == wh.dock == "dock"

    def test_submit_unknown_location_raises_and_keeps_queue_empty(self, stack):
        mgr, transport, nav, wh = stack
        with pytest.raises(MapError):
            wh.submit_move("nowhere")
        assert wh.queue_size() == 0

    def test_queue_max_enforced(self, app_config):
        mgr, transport = RobotManager.create_mock(app_config)
        mgr.start()
        nav = LocalNavigator(command=mgr.move, start_pose=Pose(0, 0, 0))
        wh = WarehouseTaskManager(
            robot=mgr, navigator=nav, manipulator=NullManipulator(),
            warehouse_map=default_map(), queue_max=2,
        )
        wh.submit_move("shelf_a")
        wh.submit_move("shelf_b")
        with pytest.raises(QueueFullError, match="full"):
            wh.submit_move("shelf_c")
        assert wh.queue_size() == 2

    def test_status_reflects_queue(self, stack):
        mgr, transport, nav, wh = stack
        wh.submit_move("shelf_a")
        wh.submit_move("shelf_b")
        st = wh.status()
        assert st.queued == 2
        assert st.current is None
        assert st.completed == 0 and st.failed == 0
        assert st.idle is False


# =========================================================================== #
# TaskManager — happy path (over the real gated stack)
# =========================================================================== #
class TestHappyPath:
    def test_move_task_completes(self, stack):
        mgr, transport, nav, wh = stack
        t = wh.submit_move("shelf_a")
        st = run_to_empty(wh)
        assert t.status is TaskStatus.DONE
        assert wh.completed() == [t] and wh.failed() == []
        assert st.idle is True
        assert st.completed == 1 and st.failed == 0
        # Arrived at the map pose (within the navigator's arrival tolerance).
        p = nav.current_pose()
        assert (abs(p.x - 2.0), abs(p.y - 0.0)) < (0.06, 0.06)
        # Robot was stopped at the end and entered autonomous motion.
        assert transport.motor_state == (0, 0)
        assert mgr.state.mode is RobotMode.AUTONOMOUS

    def test_pick_place_return_pipeline(self, app_config):
        mgr, transport = RobotManager.create_mock(app_config)
        mgr.start()
        nav = LocalNavigator(command=mgr.move, start_pose=Pose(0, 0, 0))
        manip = MockManipulator()
        wh = WarehouseTaskManager.create(app_config, mgr, nav, manipulator=manip)

        pick = wh.submit_pick("shelf_a", "p1")
        place = wh.submit_place("station", "p1")
        ret = wh.submit_return_to_dock()
        run_to_empty(wh)

        assert [t.status for t in (pick, place, ret)] == [
            TaskStatus.DONE, TaskStatus.DONE, TaskStatus.DONE,
        ]
        assert (manip.picks, manip.places) == (1, 1)
        assert manip.payload is None
        # Back at the dock.
        p = nav.current_pose()
        assert (abs(p.x), abs(p.y)) < (0.06, 0.06)

    def test_fifo_ordering(self, stack):
        mgr, transport, nav, wh = stack
        t1 = wh.submit_move("shelf_c")
        t2 = wh.submit_move("shelf_a")
        t3 = wh.submit_move("station")
        assert [t.task_id for t in wh.pending()] == [t1.task_id, t2.task_id, t3.task_id]
        run_to_empty(wh)
        assert wh.completed() == [t1, t2, t3]


# =========================================================================== #
# TaskManager — safety interactions
# =========================================================================== #
class TestSafety:
    def test_estop_mid_task_pauses_then_resumes(self, stack):
        mgr, transport, nav, wh = stack
        t = wh.submit_move("shelf_b")
        st = wh.process(DT)
        assert st.current is t.task_id
        assert t.status is TaskStatus.RUNNING
        assert mgr.state.mode is RobotMode.AUTONOMOUS

        mgr.estop()  # operator e-stop
        wh.process(DT)
        assert t.status is TaskStatus.PAUSED
        assert mgr.state.mode is RobotMode.SAFETY_STOP
        assert nav.status is NavStatus.CANCELLED

        mgr.request_mode(RobotMode.IDLE)  # operator acknowledgement
        run_to_empty(wh)
        assert t.status is TaskStatus.DONE
        assert t.attempts == 1  # resume does not count as a new attempt
        assert wh.status().completed == 1 and wh.status().failed == 0
        p = nav.current_pose()
        assert (abs(p.x - 2.0), abs(p.y - 1.5)) < (0.06, 0.06)

    def test_close_sensor_forces_pause(self, stack):
        mgr, transport, nav, wh = stack
        t = wh.submit_move("shelf_a")
        wh.process(DT)  # task starts moving
        assert t.status is TaskStatus.RUNNING

        transport.set_distances(5, 100, 100, 100)  # obstacle in front
        wh.process(DT)
        assert t.status is TaskStatus.PAUSED
        assert mgr.state.mode is RobotMode.SAFETY_STOP
        assert transport.motor_state == (0, 0)
        assert nav.status is NavStatus.CANCELLED

    def test_link_loss_blocks_all_work(self, app_config):
        # PING + VERSION answer during start(); the first sensor poll dies.
        mgr, transport = RobotManager.create_mock(app_config, drop_after=2)
        mgr.start()
        nav = LocalNavigator(command=mgr.move, start_pose=Pose(0, 0, 0))
        wh = WarehouseTaskManager.create(app_config, mgr, nav)

        t = wh.submit_move("shelf_a")
        st = wh.process(DT)  # tick detects the dead link
        assert st.connected is False
        assert mgr.state.mode is RobotMode.SAFETY_STOP

        wh.process(DT)  # still down -> nothing may run
        assert t.status is TaskStatus.PENDING
        assert wh.current_task() is None
        assert wh.queue_size() == 1
        assert wh.status().completed == 0

    def test_nav_failure_fails_task_and_next_proceeds(self, app_config):
        class VetoOnce:
            """Pass-through that rejects exactly one motion burst."""

            def __init__(self, real, after: int = 3):
                self.real = real
                self.after = after
                self.n = 0
                self.tripped = False

            def __call__(self, left: int, right: int) -> None:
                if self.tripped:
                    self.real(left, right)
                    return
                if left or right:
                    self.n += 1
                    if self.n > self.after:
                        self.tripped = True
                        raise RobotCommandError("safety veto (simulated)")
                self.real(left, right)

        mgr, transport = RobotManager.create_mock(app_config)
        mgr.start()
        nav = LocalNavigator(command=VetoOnce(mgr.move), start_pose=Pose(0, 0, 0))
        wh = WarehouseTaskManager.create(app_config, mgr, nav)

        t1 = wh.submit_move("shelf_a")
        t2 = wh.submit_move("shelf_b")
        run_to_empty(wh)

        assert t1.status is TaskStatus.FAILED
        assert "safety veto" in (t1.last_error or "")
        assert wh.failed() == [t1]
        assert t2.status is TaskStatus.DONE
        assert wh.completed() == [t2]
        assert transport.motor_state == (0, 0)

    def test_place_with_no_payload_fails(self, stack):
        mgr, transport, nav, wh = stack
        t = wh.submit_place("station", "p1")  # nothing was picked
        run_to_empty(wh)
        assert t.status is TaskStatus.FAILED
        assert wh.failed() == [t] and wh.completed() == []

    def test_pick_while_carrying_fails(self, stack):
        mgr, transport, nav, wh = stack
        t1 = wh.submit_pick("shelf_a", "p1")
        t2 = wh.submit_pick("shelf_b", "p2")
        run_to_empty(wh)
        assert t1.status is TaskStatus.DONE  # now carrying p1
        assert t2.status is TaskStatus.FAILED  # cannot pick a second payload


# =========================================================================== #
# TaskManager — status snapshot & factory
# =========================================================================== #
class TestStatusAndFactory:
    def test_status_to_dict_fields(self, stack):
        mgr, transport, nav, wh = stack
        st = wh.status()
        d = st.to_dict()
        # C12: this was an exact `==` on the whole key set, which forbids any
        # future extension. The original contract is unchanged — every key below
        # is still present with the same meaning — so the assertion is now a
        # subset check, and the three additive C12 keys are asserted separately.
        # Net coverage is higher, not lower.
        assert {
            "mode", "connected", "current", "current_type", "current_status",
            "queued", "completed", "failed", "pose",
        }.issubset(set(d))
        # C12 additive, display-only fields.
        assert {"mission_id", "destination", "total_tasks"}.issubset(set(d))
        assert d["mode"] == "IDLE"
        assert d["connected"] is True
        assert d["pose"] == Pose(0.0, 0.0, 0.0).to_dict()
        assert isinstance(st, ManagerStatus)
        assert st.idle is True
        # Idle means no destination and no work counted yet.
        assert d["current"] is None and d["destination"] is None
        assert d["total_tasks"] == 0

    def test_status_pose_tracks_navigator(self, stack):
        mgr, transport, nav, wh = stack
        wh.submit_move("shelf_a")
        wh.process(DT)
        assert wh.status().pose == nav.current_pose().to_dict()

    def test_create_reads_warehouse_config(self, stack):
        mgr, transport, nav, wh = stack
        assert wh.dock == "dock"
        assert isinstance(wh._manip, MockManipulator)  # config says "mock"
        wh.submit_move("shelf_c")  # location comes from config/warehouse.yaml
        assert wh.queue_size() == 1

    def test_create_queue_max_from_config(self, app_config):
        cfg = dataclasses.replace(
            app_config, warehouse=dataclasses.replace(app_config.warehouse, queue_max=2)
        )
        mgr, transport = RobotManager.create_mock(cfg)
        mgr.start()
        nav = LocalNavigator(command=mgr.move, start_pose=Pose(0, 0, 0))
        wh = WarehouseTaskManager.create(cfg, mgr, nav)
        wh.submit_move("shelf_a")
        wh.submit_move("shelf_b")
        with pytest.raises(QueueFullError):
            wh.submit_move("shelf_c")

    def test_create_custom_map_override(self, app_config):
        mgr, transport = RobotManager.create_mock(app_config)
        mgr.start()
        nav = LocalNavigator(command=mgr.move, start_pose=Pose(0, 0, 0))
        custom = WarehouseMap.from_dict({"a": (0.0, 0.0, 0.0), "b": (1.0, 0.0, 0.0)})
        wh = WarehouseTaskManager.create(app_config, mgr, nav, warehouse_map=custom)
        wh.submit_move("a")
        assert wh.queue_size() == 1
        with pytest.raises(MapError):
            wh.submit_move("dock")  # not in the custom map
