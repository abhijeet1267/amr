"""Navigation layer (Phase 12).

Defines the :class:`~amr.navigation.navigator.Navigator` contract that the
warehouse layer (Phase 16) drives, plus a deterministic, dependency-free
:class:`~amr.navigation.navigator.LocalNavigator` so the whole stack runs and
is tested with no ROS and no hardware. The ROS-side implementation of the same
contract (backed by Nav2) lives in ``ros2/amr_bringup`` / ``ros2/amr_navigation``.
"""

from .types import (
    Goal,
    NavResult,
    NavStatus,
    Pose,
    distance,
    wrap_angle,
)
from .navigator import Navigator, LocalNavigator

__all__ = [
    "Goal",
    "NavResult",
    "NavStatus",
    "Pose",
    "Navigator",
    "LocalNavigator",
    "distance",
    "wrap_angle",
]
