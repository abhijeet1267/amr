"""Optional ROS 2 bridge (C18) — dependency-free message translation.

This package is the seam where the dependency-free AMR stack meets ROS 2.
It translates *outbound* (this stack -> ROS topics) and *inbound* (ROS
topics -> this stack):

* outbound: :class:`RobotState` -> a ``geometry_msgs/PoseStamped``-shaped
  dict, :class:`HazardStatus` -> a ``diagnostic_msgs``-shaped dict;
* inbound: a ``geometry_msgs/PoseStamped``-shaped dict -> a navigation
  :class:`~amr.navigation.Goal`.

Deliberately dependency-free: no ``rclpy`` import anywhere in this package,
so the core stack keeps importing with no ROS installed. The translation
functions speak plain dicts shaped like the ROS messages; the thin
``rclpy`` node that will own publishers/subscribers lives in
``ros2/amr_bringup`` (not built yet) and stays outside the tested core.

The bridge must never become a control path of its own: goals produced
here are handed to the existing warehouse task queue
(:meth:`WarehouseTaskManager.submit_move`), so Layer-3 safety still gates
every motion command.
"""

from .bridge import (
    BRIDGE_SCHEMA_VERSION,
    goal_from_pose_stamped,
    hazard_to_diagnostic,
    pose_stamped_from_snapshot,
    pose_stamped_to_goal,
)

__all__ = [
    "BRIDGE_SCHEMA_VERSION",
    "goal_from_pose_stamped",
    "hazard_to_diagnostic",
    "pose_stamped_from_snapshot",
    "pose_stamped_to_goal",
]
