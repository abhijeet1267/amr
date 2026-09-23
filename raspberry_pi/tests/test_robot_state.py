"""Tests for the robot logical state model (mode + snapshot)."""

from __future__ import annotations

from amr.robot import RobotMode, RobotState


def test_default_state_is_idle_not_moving_disconnected():
    s = RobotState()
    assert s.mode is RobotMode.IDLE
    assert s.is_moving is False
    assert s.connected is False
    assert s.last_error is None


def test_is_moving_reflects_wheel_speeds():
    s = RobotState()
    s.left_speed = 50
    assert s.is_moving is True
    s.left_speed = 0
    s.right_speed = -30
    assert s.is_moving is True
    s.right_speed = 0
    assert s.is_moving is False


def test_is_safe_to_move_only_in_operating_modes():
    assert RobotMode.MANUAL.is_safe_to_move
    assert RobotMode.AUTONOMOUS.is_safe_to_move
    assert not RobotMode.IDLE.is_safe_to_move
    assert not RobotMode.SAFETY_STOP.is_safe_to_move
    assert not RobotMode.ERROR.is_safe_to_move


def test_sensor_fields_default_to_none():
    s = RobotState()
    assert s.front_cm is None
    assert s.left_cm is None
    assert s.right_cm is None
    assert s.rear_cm is None


def test_to_dict_is_json_friendly():
    s = RobotState()
    s.mode = RobotMode.MANUAL
    s.connected = True
    s.left_speed = 40
    s.front_cm = 25
    d = s.to_dict()
    assert d["mode"] == "MANUAL"
    assert d["connected"] is True
    assert d["left_speed"] == 40
    assert d["front_cm"] == 25
    assert d["is_moving"] is True
    assert d["last_error"] is None
    # All values must be JSON-serialisable primitives.
    import json

    json.dumps(d)
