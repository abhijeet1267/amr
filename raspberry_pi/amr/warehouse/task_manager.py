"""Warehouse task manager (Phase 16) — the top of the AMR stack.

Orchestrates a queue of :class:`~amr.warehouse.tasks.Task` against a
:class:`~amr.robot.robot_manager.RobotManager` and a
:class:`~amr.navigation.navigator.Navigator`, with a
:class:`~amr.warehouse.map.WarehouseMap` providing named goals.

Safety is never bypassed: every cycle the underlying control tick runs first
(sensors, watchdog, enforcement), and the manager only commands autonomous
motion while the robot is in ``AUTONOMOUS`` mode. A ``SAFETY_STOP``/``ERROR``
(or a lost link) pauses the running task and re-arms it once the operator
acknowledges the stop and the robot can re-enter autonomous motion.

Drive one control iteration per tick::

    mgr, _ = RobotManager.create_mock(config); mgr.start()
    wh = WarehouseTaskManager.create(config, mgr, navigator)
    wh.submit_move("shelf_a")
    while not wh.queue_empty():
        wh.process(dt=0.05)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional

from ..logging import get_logger
from ..navigation import Goal, NavStatus, Navigator
from ..robot import RobotCommandError, RobotManager, RobotMode
from .map import WarehouseMap, map_from_config
from .tasks import (
    Manipulator,
    QueueFullError,
    Task,
    TaskStatus,
    TaskType,
    make_manipulator,
)


@dataclass
class ManagerStatus:
    """A point-in-time snapshot of the warehouse manager (for UIs/tests)."""

    mode: str
    connected: bool
    current: Optional[str]        # active task_id
    current_type: Optional[str]
    current_status: Optional[str]
    queued: int
    completed: int
    failed: int
    pose: dict

    @property
    def idle(self) -> bool:
        return self.queued == 0 and self.current is None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "connected": self.connected,
            "current": self.current,
            "current_type": self.current_type,
            "current_status": self.current_status,
            "queued": self.queued,
            "completed": self.completed,
            "failed": self.failed,
            "pose": self.pose,
        }


class WarehouseTaskManager:
    """Task queue + orchestration over the robot and navigator."""

    def __init__(
        self,
        robot: RobotManager,
        navigator: Navigator,
        manipulator: Manipulator,
        warehouse_map: WarehouseMap,
        dock: str = "dock",
        queue_max: int = 16,
    ):
        self._robot = robot
        self._nav = navigator
        self._manip = manipulator
        self._map = warehouse_map
        self._dock = dock
        self._queue_max = int(queue_max)

        self._queue: Deque[Task] = deque()
        self._current: Optional[Task] = None
        self._pending_action: Optional[TaskType] = None
        self._completed: List[Task] = []
        self._failed: List[Task] = []
        self.log = get_logger("warehouse")

    # -- construction ------------------------------------------------------ #
    @classmethod
    def create(
        cls,
        config,
        robot: RobotManager,
        navigator: Navigator,
        manipulator: Optional[Manipulator] = None,
        warehouse_map: Optional[WarehouseMap] = None,
    ) -> "WarehouseTaskManager":
        """Build from an :class:`AppConfig` (reads ``config.warehouse``)."""
        whcfg = config.warehouse
        mapping = warehouse_map or map_from_config(whcfg)
        manip = manipulator or make_manipulator(whcfg.manipulator)
        return cls(
            robot=robot,
            navigator=navigator,
            manipulator=manip,
            warehouse_map=mapping,
            dock=whcfg.dock,
            queue_max=whcfg.queue_max,
        )

    # -- submission -------------------------------------------------------- #
    def submit(self, task: Task) -> Task:
        """Enqueue a task. Validates the location exists in the map."""
        if len(self._queue) >= self._queue_max:
            raise QueueFullError(
                f"task queue is full ({self._queue_max}); wait for a task to finish"
            )
        self._map.pose(task.location)  # raises MapError if unknown
        task.status = TaskStatus.PENDING
        self._queue.append(task)
        self.log.info(
            "queued %s %s -> %s (queue=%d)",
            task.task_id, task.task_type.value, task.location, len(self._queue),
        )
        return task

    def submit_move(self, location: str, payload_id: Optional[str] = None) -> Task:
        return self.submit(Task(TaskType.MOVE, location, payload_id))

    def submit_pick(self, location: str, payload_id: str) -> Task:
        return self.submit(Task(TaskType.PICK, location, payload_id))

    def submit_place(self, location: str, payload_id: str) -> Task:
        return self.submit(Task(TaskType.PLACE, location, payload_id))

    def submit_return_to_dock(self) -> Task:
        return self.submit(Task(TaskType.RETURN_TO_DOCK, self._dock))

    # -- queries ----------------------------------------------------------- #
    def current_task(self) -> Optional[Task]:
        return self._current

    def queue_size(self) -> int:
        return len(self._queue)

    def queue_empty(self) -> bool:
        return not self._queue and self._current is None

    def pending(self) -> List[Task]:
        return list(self._queue)

    def completed(self) -> List[Task]:
        return list(self._completed)

    def failed(self) -> List[Task]:
        return list(self._failed)

    @property
    def dock(self) -> str:
        return self._dock

    # -- main loop --------------------------------------------------------- #
    def process(self, dt: float) -> ManagerStatus:
        """Advance the manager by one control iteration (``dt`` seconds)."""
        # 1) One control tick: poll sensors, watchdog, safety enforcement.
        self._robot.tick()

        # 2) Link lost -> pause everything.
        if not self._robot.state.connected:
            self._pause_current("disconnected")
            return self.status()

        mode = self._robot.state.mode

        # 3) A safety stop or fault: pause the running task and halt.
        if mode in (RobotMode.SAFETY_STOP, RobotMode.ERROR):
            self._pause_current("safety stop")
            self._nav.cancel()
            self._robot.stop()
            return self.status()

        # 4) Warehouse work requires AUTONOMOUS.
        self._ensure_autonomous()
        if self._robot.state.mode is not RobotMode.AUTONOMOUS:
            return self.status()

        # 5) Start (or resume) a task.
        if self._current is not None and self._current.status is TaskStatus.PAUSED:
            self._current.status = TaskStatus.RUNNING
            self._start(self._current)  # re-arm the navigator toward the goal
        elif self._current is None and self._queue:
            self._current = self._queue.popleft()
            self._current.status = TaskStatus.RUNNING
            self._current.attempts += 1
            self._start(self._current)

        # 6) Drive the active task one step.
        if self._current is not None:
            self._nav.step(dt)
            nav_status = self._nav.status
            if nav_status is NavStatus.DONE:
                self._finish_current()
            elif nav_status is NavStatus.FAILED:
                self._current.status = TaskStatus.FAILED
                self._current.last_error = self._nav.error
                self._failed.append(self._current)
                self._current = None
                self._robot.stop()
        return self.status()

    # -- orchestration internals ------------------------------------------- #
    def _start(self, task: Task) -> None:
        pose = self._map.pose(task.location)
        self._pending_action = task.task_type
        self._nav.go_to(Goal(pose=pose, name=task.location))
        self.log.info("started %s %s -> %s", task.task_id, task.task_type.value, task.location)

    def _finish_current(self) -> None:
        task = self._current
        action = self._pending_action
        ok, error = self._perform(action, task)
        if ok:
            task.status = TaskStatus.DONE
            self._completed.append(task)
        else:
            task.status = TaskStatus.FAILED
            task.last_error = error
            self._failed.append(task)
        self._robot.stop()
        self._current = None
        self.log.info("finished %s (%s)", task.task_id, task.status.value)

    def _perform(self, action: Optional[TaskType], task: Task):
        """Run the (optional) end-effector action for a completed drive."""
        if action is TaskType.PICK:
            return self._manip.pick(task.payload_id or task.location), None
        if action is TaskType.PLACE:
            return self._manip.place(task.payload_id or task.location), None
        return True, None  # MOVE / RETURN_TO_DOCK: nothing to manipulate

    def _pause_current(self, reason: str) -> None:
        if self._current is not None and self._current.status is TaskStatus.RUNNING:
            self._current.status = TaskStatus.PAUSED
            self._current.last_error = reason
            self.log.warning("paused %s: %s", self._current.task_id, reason)

    def _ensure_autonomous(self) -> None:
        """Best-effort transition to AUTONOMOUS (IDLE -> MANUAL -> AUTONOMOUS)."""
        mode = self._robot.state.mode
        if mode is RobotMode.AUTONOMOUS:
            return
        try:
            if mode is RobotMode.IDLE:
                self._robot.request_mode(RobotMode.MANUAL)
            if self._robot.state.mode is not RobotMode.AUTONOMOUS:
                self._robot.request_mode(RobotMode.AUTONOMOUS)
        except RobotCommandError as exc:
            self.log.debug("cannot enter AUTONOMOUS yet: %s", exc)

    # -- status ------------------------------------------------------------ #
    def status(self) -> ManagerStatus:
        cur = self._current
        pose = self._nav.current_pose()
        return ManagerStatus(
            mode=self._robot.state.mode.value,
            connected=self._robot.state.connected,
            current=cur.task_id if cur else None,
            current_type=cur.task_type.value if cur else None,
            current_status=cur.status.value if cur else None,
            queued=len(self._queue),
            completed=len(self._completed),
            failed=len(self._failed),
            pose=pose.to_dict(),
        )
