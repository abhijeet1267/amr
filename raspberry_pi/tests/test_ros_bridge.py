"""Tests for the optional ROS 2 bridge (C18).

Covers, with no ROS and no hardware:

* :mod:`ros2.bridge` — snapshot -> PoseStamped-shaped dict, HazardStatus ->
  diagnostic-shaped dict, PoseStamped-shaped dict -> navigation Goal.
* The optionality contract — no ``rclpy``/``ament``/``colcon`` import
  anywhere in the bridge or the core ``amr`` stack.
* The no-control-path rule — the bridge never imports motor drivers, the
  serial transport, or the command API; inbound goals only enter through
  the warehouse task queue, so Layer-3 safety still gates every motion.

**No ROS installation exists in this repository.** Every message here is a
plain dict shaped like its ROS counterpart; no real topic has ever been
published by this code.
"""

from __future__ import annotations

import math
import pathlib
import re
import sys

import pytest

# The bridge lives at the repo root (``ros2/``), one level above the
# ``raspberry_pi/`` pytest rootdir. Add it without touching ``sys.path`` for
# anyone else.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from amr.hazard.types import HazardState, HazardStatus
from amr.navigation import Goal
from amr.telemetry import TelemetrySnapshot
from ros2.bridge import (
    BASE_FRAME,
    BRIDGE_SCHEMA_VERSION,
    DIAGNOSTIC_ERROR,
    DIAGNOSTIC_OK,
    DIAGNOSTIC_STALE,
    DIAGNOSTIC_WARN,
    MAP_FRAME,
    goal_from_pose_stamped,
    hazard_to_diagnostic,
    pose_stamped_from_snapshot,
    pose_stamped_to_goal,
)


def _pose_msg(x=1.0, y=2.0, yaw=0.5, frame=MAP_FRAME):
    """A PoseStamped-shaped dict, built without any ROS dependency."""
    half = yaw / 2.0
    return {
        "header": {"frame_id": frame, "stamp": 123.0},
        "pose": {
            "position": {"x": x, "y": y, "z": 0.0},
            "orientation": {
                "x": 0.0,
                "y": 0.0,
                "z": math.sin(half),
                "w": math.cos(half),
            },
        },
    }


# =========================================================================== #
# Outbound: snapshot -> PoseStamped
# =========================================================================== #
class TestPoseStampedFromSnapshot:
    def test_schema_version_is_pinned(self):
        assert BRIDGE_SCHEMA_VERSION == "1.0"

    def test_empty_snapshot_never_fabricates_a_position(self):
        msg = pose_stamped_from_snapshot(TelemetrySnapshot())
        assert msg["header"]["frame_id"] == MAP_FRAME
        assert msg["pose"]["position"] == {"x": None, "y": None, "z": None}

    def test_pose_round_trips_through_quaternion(self):
        snap = TelemetrySnapshot()
        object.__setattr__(snap.position, "x", 1.5)
        object.__setattr__(snap.position, "y", -2.5)
        object.__setattr__(snap.orientation, "yaw", 1.0)
        msg = pose_stamped_from_snapshot(snap)
        assert msg["pose"]["position"]["x"] == 1.5
        assert msg["pose"]["position"]["y"] == -2.5
        back = goal_from_pose_stamped(msg)
        assert back.pose.x == pytest.approx(1.5)
        assert back.pose.y == pytest.approx(-2.5)
        assert back.pose.theta == pytest.approx(1.0)

    def test_nan_coordinates_degrade_to_none(self):
        snap = TelemetrySnapshot()
        object.__setattr__(snap.position, "x", float("nan"))
        object.__setattr__(snap.position, "y", float("inf"))
        msg = pose_stamped_from_snapshot(snap)
        assert msg["pose"]["position"]["x"] is None
        assert msg["pose"]["position"]["y"] is None

    def test_bad_snapshot_degrades_never_raises(self):
        assert pose_stamped_from_snapshot(object())["header"]["frame_id"] == MAP_FRAME


# =========================================================================== #
# Outbound: HazardStatus -> diagnostic
# =========================================================================== #
class TestHazardToDiagnostic:
    @pytest.mark.parametrize(
        ("state", "level"),
        [
            (HazardState.NORMAL, DIAGNOSTIC_OK),
            (HazardState.WARNING, DIAGNOSTIC_WARN),
            (HazardState.SLOW, DIAGNOSTIC_WARN),
            (HazardState.STOP, DIAGNOSTIC_ERROR),
            (HazardState.EMERGENCY, DIAGNOSTIC_ERROR),
        ],
    )
    def test_every_state_maps_to_its_level(self, state, level):
        diag = hazard_to_diagnostic(HazardStatus(state=state))
        assert diag["level"] == level
        assert diag["name"] == "amr_hazard"
        assert diag["hardware_id"] == BASE_FRAME
        by_key = {v["key"]: v["value"] for v in diag["values"]}
        assert by_key["state"] == state.value
        assert by_key["blocks_motion"] == str(state.blocks_motion)

    def test_reasons_reach_the_message(self):
        diag = hazard_to_diagnostic(
            HazardStatus(state=HazardState.WARNING, reasons=("gas ppm high",))
        )
        assert "gas ppm high" in diag["message"]

    def test_unknown_state_degrades_to_stale_never_ok(self):
        diag = hazard_to_diagnostic({"state": "SOMETHING_NEW", "reasons": []})
        assert diag["level"] == DIAGNOSTIC_STALE
        assert diag["message"] == "SOMETHING_NEW"


# =========================================================================== #
# Inbound: PoseStamped -> navigation Goal
# =========================================================================== #
class TestGoalFromPoseStamped:
    def test_valid_message_becomes_a_goal(self):
        goal = goal_from_pose_stamped(_pose_msg(3.0, 4.0, math.pi / 2.0))
        assert isinstance(goal, Goal)
        assert goal.pose.x == pytest.approx(3.0)
        assert goal.pose.y == pytest.approx(4.0)
        assert goal.pose.theta == pytest.approx(math.pi / 2.0)
        assert goal.name == "ros_goal"

    def test_name_is_carried_through(self):
        goal = goal_from_pose_stamped(_pose_msg(), name="nav2_simple_goto")
        assert goal.name == "nav2_simple_goto"

    def test_alias_matches_the_canonical_function(self):
        msg = _pose_msg()
        assert pose_stamped_to_goal(msg) is not None
        assert pose_stamped_to_goal(msg).pose == goal_from_pose_stamped(msg).pose

    def test_non_mapping_message_is_rejected(self):
        with pytest.raises(ValueError, match="must be a mapping"):
            goal_from_pose_stamped("just a string")

    def test_missing_position_is_rejected(self):
        bad = {"pose": {"orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}
        with pytest.raises(ValueError, match="position"):
            goal_from_pose_stamped(bad)

    def test_non_finite_position_is_rejected(self):
        with pytest.raises(ValueError, match="finite"):
            goal_from_pose_stamped(_pose_msg(x=float("nan")))

    def test_unreadable_orientation_degrades_to_yaw_zero_with_a_note(self):
        msg = _pose_msg()
        msg["pose"]["orientation"] = {"x": "not", "y": "a", "z": "quaternion", "w": "!"}
        goal = goal_from_pose_stamped(msg)
        assert goal.pose.theta == 0.0
        assert "yaw defaulted" in goal.name

    def test_missing_orientation_entirely_degrades_to_yaw_zero(self):
        msg = _pose_msg()
        del msg["pose"]["orientation"]
        goal = goal_from_pose_stamped(msg)
        assert goal.pose.theta == 0.0
        assert "yaw defaulted" in goal.name

    def test_blank_name_falls_back_to_the_default_label(self):
        assert goal_from_pose_stamped(_pose_msg(), name="  ").name == "ros_goal"


# =========================================================================== #
# Optionality: no ROS anywhere in the core
# =========================================================================== #
def _py_files(*roots):
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


class TestOptionality:
    """The core stack must import with no ROS installed (C18's hard rule)."""

    def test_no_ros_import_in_bridge_or_core(self, repo_root):
        pattern = re.compile(
            r"^\s*(import\s+rclpy|from\s+rclpy|import\s+ament|from\s+ament)"
            r"|\bimport\s+roslib\b|\bcolcon\b.*import",
        )
        offenders = [
            f"{p.relative_to(repo_root)}:{i}: {line.strip()}"
            for p in _py_files(repo_root / "ros2", repo_root / "raspberry_pi" / "amr")
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if pattern.search(line)
        ]
        assert offenders == [], f"ROS import(s) leaked into the core: {offenders}"

    def test_bridge_importable_with_no_ros_installed(self):
        # This suite has no rclpy; if the import above worked, that is the proof.
        import ros2.bridge  # noqa: F401

        assert ros2.bridge.BRIDGE_SCHEMA_VERSION == "1.0"


# =========================================================================== #
# The bridge must never become a control path
# =========================================================================== #
class TestNoControlPath:
    def test_bridge_references_no_motor_serial_or_command_api(self, repo_root):
        """Outbound/inbound translation only — no way to reach the wheels."""
        banned = re.compile(
            r"\b(RobotManager|ArduinoSerial|ArduinoMotorDriver|MotorDriver|"
            r"DifferentialDrive|dispatch\s*\(|POST\s*/command)\b"
        )
        offenders = [
            f"{p.relative_to(repo_root)}:{i}: {line.strip()}"
            for p in _py_files(repo_root / "ros2")
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if banned.search(line) and not line.lstrip().startswith("#")
        ]
        assert offenders == [], f"bridge gained a control path: {offenders}"

    def test_bridge_target_inbound_flow_is_only_documented(self):
        """`ros2/__init__` names the task queue as the only motion entry point."""
        text = pathlib.Path(__file__).resolve().parents[2].joinpath(
            "ros2", "__init__.py").read_text(encoding="utf-8")
        assert "submit_move" in text
        assert "Layer-3 safety" in text

