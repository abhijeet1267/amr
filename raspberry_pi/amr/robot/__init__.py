"""Robot logical state (mode, snapshot), mode state machine, robot manager.

The robot manager (Phase 8) owns :class:`RobotState` and
:class:`ModeController`; other layers read them and issue commands through
:meth:`RobotManager` only.
"""

from .mode_controller import ModeController, ModeTransitionError
from .robot_manager import RobotCommandError, RobotManager
from .robot_state import RobotMode, RobotState

__all__ = [
    "ModeController",
    "ModeTransitionError",
    "RobotCommandError",
    "RobotManager",
    "RobotMode",
    "RobotState",
]
