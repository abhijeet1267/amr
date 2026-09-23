"""Tests for the robot mode state machine."""

from __future__ import annotations

import pytest

from amr.robot import ModeController, ModeTransitionError, RobotMode


def test_initial_mode_is_idle():
    assert ModeController().mode is RobotMode.IDLE


def test_idle_to_manual_allowed():
    mc = ModeController()
    assert mc.request(RobotMode.MANUAL) is RobotMode.MANUAL


def test_idle_to_autonomous_blocked_must_go_through_manual():
    mc = ModeController()
    with pytest.raises(ModeTransitionError):
        mc.request(RobotMode.AUTONOMOUS)
    assert mc.mode is RobotMode.IDLE


def test_manual_to_autonomous_allowed():
    mc = ModeController()
    mc.request(RobotMode.MANUAL)
    assert mc.request(RobotMode.AUTONOMOUS) is RobotMode.AUTONOMOUS


def test_autonomous_back_to_manual_or_idle():
    mc = ModeController()
    mc.request(RobotMode.MANUAL)
    mc.request(RobotMode.AUTONOMOUS)
    assert mc.request(RobotMode.MANUAL) is RobotMode.MANUAL
    assert mc.request(RobotMode.IDLE) is RobotMode.IDLE


def test_safety_stop_forced_from_any_mode():
    for start in (
        RobotMode.IDLE,
        RobotMode.MANUAL,
        RobotMode.AUTONOMOUS,
    ):
        mc = ModeController(initial=start)
        assert mc.safety_stop() is RobotMode.SAFETY_STOP


def test_safety_stop_is_idempotent():
    mc = ModeController()
    mc.safety_stop()
    assert mc.safety_stop() is RobotMode.SAFETY_STOP


def test_safety_stop_blocks_direct_return_to_motion():
    mc = ModeController()
    mc.safety_stop()
    with pytest.raises(ModeTransitionError):
        mc.request(RobotMode.MANUAL)
    with pytest.raises(ModeTransitionError):
        mc.request(RobotMode.AUTONOMOUS)


def test_reset_returns_to_idle_only():
    mc = ModeController()
    mc.safety_stop()
    assert mc.reset() is RobotMode.IDLE

    mc.request(RobotMode.MANUAL)
    mc.safety_stop()
    assert mc.reset() is RobotMode.IDLE
    # ...and now manual control is possible again
    assert mc.request(RobotMode.MANUAL) is RobotMode.MANUAL


def test_reset_requires_safety_stop_or_error():
    mc = ModeController()
    with pytest.raises(ModeTransitionError):
        mc.reset()


def test_error_mode_also_requires_reset():
    mc = ModeController()
    mc.request(RobotMode.ERROR)
    with pytest.raises(ModeTransitionError):
        mc.request(RobotMode.MANUAL)
    assert mc.reset() is RobotMode.IDLE


def test_request_same_mode_is_noop():
    mc = ModeController()
    assert mc.request(RobotMode.IDLE) is RobotMode.IDLE
    assert mc.can_transition(RobotMode.IDLE) is True


def test_can_transition_reflects_table():
    mc = ModeController()
    assert mc.can_transition(RobotMode.MANUAL) is True
    assert mc.can_transition(RobotMode.AUTONOMOUS) is False
    mc.request(RobotMode.MANUAL)
    assert mc.can_transition(RobotMode.AUTONOMOUS) is True
