"""Warehouse layer (Phase 16) — the top of the AMR stack.

A :class:`~amr.warehouse.task_manager.WarehouseTaskManager` turns a queue of
tasks (move / pick / place / return-to-dock) into safe, gated robot motion by
orchestrating a :class:`~amr.navigation.navigator.Navigator` against the
:class:`~amr.robot.robot_manager.RobotManager` and a
:class:`~amr.warehouse.map.WarehouseMap`. It runs and is unit-tested with no
ROS and no hardware.
"""

from .map import MapError, WarehouseMap, default_map, map_from_config
from .tasks import (
    Manipulator,
    MockManipulator,
    NullManipulator,
    QueueFullError,
    Task,
    TaskResult,
    TaskStatus,
    TaskType,
    make_manipulator,
)
from .task_manager import ManagerStatus, WarehouseTaskManager

__all__ = [
    "WarehouseMap",
    "MapError",
    "default_map",
    "map_from_config",
    "Task",
    "TaskType",
    "TaskStatus",
    "TaskResult",
    "QueueFullError",
    "Manipulator",
    "MockManipulator",
    "NullManipulator",
    "make_manipulator",
    "WarehouseTaskManager",
    "ManagerStatus",
]
