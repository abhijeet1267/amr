"""Dependency-free ROS 2 translation (C18).

Outbound (this stack -> ROS topics) and inbound (ROS topics -> this stack)
speak plain dicts shaped like the ROS messages, so no ``rclpy`` import is
needed anywhere here and the core stack keeps importing with no ROS
installed. The thin ``rclpy`` node that will own publishers/subscribers
lives in ``ros2/amr_bringup`` (not built yet) and stays outside the core.

The bridge must never become a control path of its own: goals produced here
are handed to the existing warehouse task queue (``submit_move``), so
Layer-3 safety still gates every motion command.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Tuple

#: Bridge schema version. Bump when a translated field is removed or changes
#: meaning. Additive fields do not require a bump.
BRIDGE_SCHEMA_VERSION = "1.0"

#: Frames stamped onto outbound pose messages. ``map`` is the fixed world
#: frame the warehouse locations live in; ``base_link`` is the robot body
#: frame reporters of ``/tf`` expect.
MAP_FRAME = "map"
BASE_FRAME = "base_link"

#: Diagnostic level vocabulary mirrored from ``diagnostic_msgs`` so a ROS
#: operator reads the mapping without a translation table. Only ever emitted
#: as integers inside plain dicts; the ROS package itself is never imported.
DIAGNOSTIC_OK = 0
DIAGNOSTIC_WARN = 1
DIAGNOSTIC_ERROR = 2
DIAGNOSTIC_STALE = 3

#: Hazard states where motion must be vetoed. Plain strings (not the
#: ``HazardState`` enum) so this module imports nothing from the stack — the
#: mapping is asserted against the real enum by the test-suite.
_BLOCKING_STATES = frozenset({"STOP", "EMERGENCY"})


def _finite(value: Any) -> Optional[float]:
    """Coerce to a finite float, or ``None`` (never NaN/inf on the wire)."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _yaw_to_quaternion(yaw: Any) -> Dict[str, float]:
    """Planar yaw (radians) -> a unit quaternion dict (x/y/z/w)."""
    try:
        angle = float(yaw)
    except (TypeError, ValueError):
        angle = 0.0
    if angle != angle:  # NaN headings face forward, never poison the pose
        angle = 0.0
    half = angle / 2.0
    return {"x": 0.0, "y": 0.0, "z": math.sin(half), "w": math.cos(half)}


def _quaternion_to_yaw(q: Any) -> Optional[float]:
    """Planar yaw from a quaternion mapping; ``None`` when unreadable."""
    if not isinstance(q, Mapping):
        return None
    try:
        x = float(q.get("x", 0.0))
        y = float(q.get("y", 0.0))
        z = float(q.get("z", 0.0))
        w = float(q.get("w", 1.0))
    except (TypeError, ValueError):
        return None
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm <= 0.0 or norm != norm:
        return None
    siny = 2.0 * (w * z + x * y)
    cosy = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny, cosy)
    return None if yaw != yaw else yaw


def pose_stamped_from_snapshot(snapshot: Any) -> Dict[str, Any]:
    """Snapshot -> a PoseStamped-shaped dict (missing coords stay ``None``).

    Reads ``position`` / ``orientation`` / ``timestamp`` through a duck-typed
    ``to_dict()`` call, so both the real ``TelemetrySnapshot`` and lightweight
    test doubles are accepted. Absent coordinates serialise as ``None`` —
    never a fabricated zero (the C7 telemetry honesty rule at the boundary).
    """
    position: Dict[str, Any] = {}
    orientation: Dict[str, Any] = {}
    timestamp: Any = 0.0
    try:
        to_dict = getattr(snapshot, "to_dict", None)
        payload = to_dict() if callable(to_dict) else snapshot
        if isinstance(payload, Mapping):
            position = dict(payload.get("position") or {})
            orientation = dict(payload.get("orientation") or {})
            timestamp = payload.get("timestamp", 0.0)
    except Exception:  # noqa: BLE001 - a bad snapshot degrades, never raises
        position, orientation, timestamp = {}, {}, 0.0
    x = _finite(position.get("x"))
    y = _finite(position.get("y"))
    yaw = _finite(orientation.get("yaw")) if orientation else 0.0
    stamp = _finite(timestamp)
    return {
        "header": {
            "frame_id": MAP_FRAME,
            "stamp": stamp if stamp is not None else 0.0,
        },
        "pose": {
            "position": {"x": x, "y": y, "z": None},
            "orientation": _yaw_to_quaternion(yaw if yaw is not None else 0.0),
        },
    }


def hazard_to_diagnostic(status: Any) -> Dict[str, Any]:
    """HazardStatus -> a diagnostic dict (unknown states degrade to STALE).

    ``message`` carries the human-readable reasons so a ROS operator sees
    *why*; ``values`` keeps the machine-readable verdict (state, motion
    gate, latch, speed scale) for dashboards.
    """
    to_dict = getattr(status, "to_dict", None)
    try:
        payload = to_dict() if callable(to_dict) else status
        data = dict(payload) if isinstance(payload, Mapping) else {}
    except Exception:  # noqa: BLE001 - degrade, never raise
        data = {}
    state = str(data.get("state", "") or "").upper()
    reasons = data.get("reasons") or []
    if state in _BLOCKING_STATES:
        level = DIAGNOSTIC_ERROR
    elif state in ("WARNING", "SLOW"):
        level = DIAGNOSTIC_WARN
    elif state == "NORMAL":
        level = DIAGNOSTIC_OK
    else:
        level = DIAGNOSTIC_STALE
    message = "; ".join(str(r) for r in reasons) if reasons else state or "UNKNOWN"
    values: List[Dict[str, str]] = [
        {"key": "state", "value": state or "UNKNOWN"},
        {"key": "blocks_motion",
         "value": str(bool(data.get("blocks_motion", level == DIAGNOSTIC_ERROR)))},
        {"key": "latched", "value": str(bool(data.get("latched", False)))},
        {"key": "speed_scale", "value": str(data.get("speed_scale", 1.0))},
    ]
    return {
        "name": "amr_hazard",
        "hardware_id": BASE_FRAME,
        "level": level,
        "message": message,
        "values": values,
    }


def _goal_pose_from_dict(payload: Mapping[str, Any]) -> Tuple[Any, Any, float, List[str]]:
    """Extract (x, y, yaw) from a PoseStamped-shaped dict plus error notes."""
    errors: List[str] = []
    pose = payload.get("pose")
    if not isinstance(pose, Mapping):
        return None, None, 0.0, ["msg.pose is missing"]
    position = pose.get("position")
    if not isinstance(position, Mapping):
        return None, None, 0.0, ["msg.pose.position is missing"]
    x = _finite(position.get("x"))
    y = _finite(position.get("y"))
    if x is None or y is None:
        errors.append("msg.pose.position.x/y must be finite numbers")
    yaw = _quaternion_to_yaw(pose.get("orientation"))
    if yaw is None:
        errors.append("msg.pose.orientation is not a readable quaternion; yaw defaults to 0")
        yaw = 0.0
    return x, y, yaw, errors


def goal_from_pose_stamped(msg: Any, name: str = "ros_goal") -> Any:
    """PoseStamped-shaped dict -> a navigation ``Goal`` (or ``ValueError``).

    A missing/unreadable orientation degrades to yaw ``0.0`` with a note in
    The import is lazy so this module stays dependency-free at import time.
    It tries the ``amr`` package first (normal runtime layout) and falls back
    to the ``raspberry_pi.amr`` path (repo-root imports).
    """
    try:
        from amr.navigation import Goal, Pose  # noqa: PLC0415 - lazy on purpose
    except ImportError:
        from raspberry_pi.amr.navigation import (  # noqa: PLC0415 - alternate layout
            Goal,
            Pose,
        )

    if not isinstance(msg, Mapping):
        raise ValueError("goal message must be a mapping shaped like geometry_msgs/PoseStamped")
    label = str(name or "ros_goal").strip() or "ros_goal"
    x, y, yaw, errors = _goal_pose_from_dict(msg)
    if x is None or y is None:
        raise ValueError("; ".join(errors) or "goal message carries no usable position")
    if errors:
        label = f"{label} (yaw defaulted: orientation unreadable)"
    return Goal(pose=Pose(x, y, yaw), name=label)


def pose_stamped_to_goal(msg: Any, name: str = "ros_goal") -> Any:
    """Backwards-compatible alias for :func:`goal_from_pose_stamped`."""
    return goal_from_pose_stamped(msg, name=name)


__all__ = [
    "BASE_FRAME",
    "BRIDGE_SCHEMA_VERSION",
    "DIAGNOSTIC_ERROR",
    "DIAGNOSTIC_OK",
    "DIAGNOSTIC_STALE",
    "DIAGNOSTIC_WARN",
    "MAP_FRAME",
    "goal_from_pose_stamped",
    "hazard_to_diagnostic",
    "pose_stamped_from_snapshot",
    "pose_stamped_to_goal",
]

