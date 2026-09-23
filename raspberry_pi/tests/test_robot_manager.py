"""Tests for the RobotManager (Phase 8) — full offline stack.

Everything runs against :class:`MockSerialTransport`; the same code paths
execute in hardware mode (only the transport differs).
"""

from __future__ import annotations

import json

import pytest

from amr.main import run_demo
from amr.robot import (
    RobotCommandError,
    RobotManager,
    RobotMode,
)
from amr.safety import SafetyAction
from amr.sensors import UltrasonicReading
from amr.utils.config import load_config


@pytest.fixture
def app_config(config_dir):
    return load_config(config_dir)


@pytest.fixture
def robot(app_config):
    mgr, transport = RobotManager.create_mock(app_config)
    mgr.start()
    return mgr, transport


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
def test_start_connects_and_reports_version(robot):
    mgr, _ = robot
    assert mgr.state.connected is True
    assert mgr.version == "1.0"
    assert mgr.state.mode is RobotMode.IDLE


def test_start_fails_when_controller_silent(app_config):
    mgr, _ = RobotManager.create_mock(app_config, drop_after=0)
    with pytest.raises(ConnectionError):
        mgr.start()
    assert mgr.state.connected is False


def test_tick_refreshes_sensor_state(robot):
    mgr, transport = robot
    transport.set_distances(100, 80, 90, 120)
    d = mgr.tick()
    assert d.action is SafetyAction.PROCEED
    s = mgr.state
    assert (s.front_cm, s.left_cm, s.right_cm, s.rear_cm) == (100, 80, 90, 120)


def test_snapshot_contains_core_fields(robot):
    mgr, _ = robot
    d = mgr.snapshot()
    for key in (
        "mode", "connected", "left_speed", "right_speed",
        "front_cm", "rear_cm", "safety", "version", "is_moving",
    ):
        assert key in d
    assert d["version"] == "1.0"


# --------------------------------------------------------------------------- #
# Motion gating (Layer 3)
# --------------------------------------------------------------------------- #
def test_motion_blocked_in_idle(robot):
    mgr, _ = robot
    with pytest.raises(RobotCommandError, match="not allowed in mode"):
        mgr.forward(100)


def test_manual_forward_works(robot):
    mgr, transport = robot
    mgr.request_mode(RobotMode.MANUAL)
    mgr.forward(100)
    assert transport.motor_state == (100, 100)
    assert mgr.state.is_moving is True
    assert (mgr.state.left_speed, mgr.state.right_speed) == (100, 100)


def test_backward_and_rotate(robot):
    mgr, transport = robot
    mgr.request_mode(RobotMode.MANUAL)
    mgr.backward(60)
    assert transport.motor_state == (-60, -60)
    mgr.rotate_left(80)
    assert transport.motor_state == (-80, 80)
    mgr.rotate_right(80)
    assert transport.motor_state == (80, -80)


def test_stop_command_always_allowed(robot):
    mgr, transport = robot
    # Not even in MANUAL — stop must still work.
    mgr.stop()
    assert transport.motor_state == (0, 0)


def test_safety_veto_blocks_motion(robot):
    mgr, _ = robot
    mgr.request_mode(RobotMode.MANUAL)
    # Simulate a fresh close reading arriving (as tick would publish it).
    mgr._last_reading = UltrasonicReading(front=5, left=100, right=100, rear=100)
    with pytest.raises(RobotCommandError, match="safety veto"):
        mgr.forward(100)
    # Mode is still MANUAL — the veto is a refusal, not a state change.
    assert mgr.state.mode is RobotMode.MANUAL


def test_motion_blocked_when_disconnected(robot):
    mgr, _ = robot
    mgr.request_mode(RobotMode.MANUAL)
    # Simulate the link having been declared lost.
    mgr.state.connected = False
    with pytest.raises(RobotCommandError, match="not connected"):
        mgr.forward(100)


# --------------------------------------------------------------------------- #
# Safety enforcement via tick()
# --------------------------------------------------------------------------- #
def test_close_sensor_forces_safety_stop(robot):
    mgr, transport = robot
    mgr.request_mode(RobotMode.MANUAL)
    mgr.forward(100)

    transport.set_distances(10, 100, 100, 100)
    d = mgr.tick()

    assert d.action is SafetyAction.STOP
    assert mgr.state.mode is RobotMode.SAFETY_STOP
    assert transport.motor_state == (0, 0)
    assert mgr.state.is_moving is False
    assert mgr.state.last_error is not None

    with pytest.raises(RobotCommandError, match="not allowed in mode"):
        mgr.forward(100)


def test_link_loss_forces_safety_stop(app_config):
    # First two commands (PING, VERSION) answer; then the link dies.
    mgr, _ = RobotManager.create_mock(app_config, drop_after=2)
    mgr.start()
    assert mgr.state.connected is True

    d = mgr.tick()  # SENSOR poll times out -> link loss

    assert d.action is SafetyAction.STOP
    assert mgr.state.connected is False
    assert mgr.state.mode is RobotMode.SAFETY_STOP
    assert "LINK" in (mgr.state.last_error or "").upper() or mgr.state.last_error


def test_estop_from_manual(robot):
    mgr, transport = robot
    mgr.request_mode(RobotMode.MANUAL)
    mgr.forward(100)
    mgr.estop()
    assert transport.motor_state == (0, 0)
    assert mgr.state.mode is RobotMode.SAFETY_STOP
    assert mgr.state.last_error == "E-STOP (operator)"


def test_estop_from_idle(robot):
    mgr, _ = robot
    mgr.estop()
    assert mgr.state.mode is RobotMode.SAFETY_STOP


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #
def test_reset_after_estop_allows_motion_again(robot):
    mgr, transport = robot
    mgr.estop()
    assert mgr.request_mode(RobotMode.IDLE) is RobotMode.IDLE
    assert mgr.request_mode(RobotMode.MANUAL) is RobotMode.MANUAL
    mgr.forward(50)
    assert transport.motor_state == (50, 50)


def test_autonomous_requires_manual_first(robot):
    mgr, _ = robot
    with pytest.raises(RobotCommandError):
        mgr.request_mode(RobotMode.AUTONOMOUS)


def test_autonomous_allowed_when_sensors_clear(robot):
    mgr, _ = robot
    mgr.request_mode(RobotMode.MANUAL)
    assert mgr.request_mode(RobotMode.AUTONOMOUS) is RobotMode.AUTONOMOUS
    mgr.forward(40)  # autonomous motion is permitted while clear


def test_autonomous_blocked_when_sensors_close(robot):
    mgr, _ = robot
    mgr.request_mode(RobotMode.MANUAL)
    mgr._last_reading = UltrasonicReading(front=100, left=100, right=100, rear=10)
    with pytest.raises(RobotCommandError, match="AUTONOMOUS"):
        mgr.request_mode(RobotMode.AUTONOMOUS)
    assert mgr.state.mode is RobotMode.MANUAL


# --------------------------------------------------------------------------- #
# Demo mode
# --------------------------------------------------------------------------- #
def test_demo_runs_cleanly(app_config, capsys):
    mgr, _ = RobotManager.create_mock(app_config)
    rc = run_demo(mgr, out=lambda _line: None)
    assert rc == 0


def test_demo_reports_step_results(app_config):
    lines = []
    mgr, _ = RobotManager.create_mock(app_config)
    rc = run_demo(mgr, out=lines.append)
    assert rc == 0
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["step"] == "start"
    assert parsed[-1]["step"] == "snapshot"
    assert all(p["ok"] for p in parsed)
