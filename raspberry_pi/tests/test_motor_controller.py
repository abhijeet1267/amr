"""Tests for the Pi-side motor driver layer.

Covers :func:`amr.control.motor_controller.clamp_speed` (pure clamping), the
:class:`~amr.control.motor_controller.ArduinoMotorDriver` (speed clamping,
explicit-rejection handling, enable state, ``max_speed`` validation) and proves
it drives a real :class:`~amr.communication.arduino_serial.ArduinoSerial` over
the mock transport end-to-end.

No hardware: rejection paths are exercised with a tiny fake serial, and the
happy path uses :class:`amr.mocks.mock_serial.MockSerialTransport`.
"""

from __future__ import annotations

import types
from typing import List, Tuple

import pytest

from amr.communication import ArduinoSerial, MAX_SPEED, MIN_SPEED
from amr.control import ArduinoMotorDriver, MotorDriver, clamp_speed
from amr.control.motor_controller import MotorError
from amr.mocks.mock_serial import MockSerialTransport


# --------------------------------------------------------------------------- #
# clamp_speed (pure)
# --------------------------------------------------------------------------- #
def test_clamp_speed_within_range_unchanged():
    assert clamp_speed(120) == 120
    assert clamp_speed(-120) == -120
    assert clamp_speed(0) == 0


def test_clamp_speed_clamps_above_max():
    assert clamp_speed(1000) == MAX_SPEED
    assert clamp_speed(500, 0, 100) == 100


def test_clamp_speed_clamps_below_min():
    assert clamp_speed(-1000) == MIN_SPEED
    assert clamp_speed(-500, -100, 100) == -100


def test_clamp_speed_defaults_are_protocol_bounds():
    # Default min/max are the protocol-wide bounds, not the driver's max_speed.
    assert clamp_speed(10_000) == MAX_SPEED
    assert clamp_speed(-10_000) == MIN_SPEED


def test_clamp_speed_coerces_to_int():
    assert clamp_speed(120.7) == 120
    assert clamp_speed(120.9) == 120
    assert clamp_speed(-120.9) == -120


# --------------------------------------------------------------------------- #
# ArduinoMotorDriver: max_speed validation
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_serial() -> "_FakeSerial":
    return _FakeSerial()


@pytest.mark.parametrize("max_speed", [1, MAX_SPEED])
def test_init_max_speed_valid(fake_serial, max_speed):
    drv = ArduinoMotorDriver(fake_serial, max_speed=max_speed)
    assert drv.max_speed == max_speed
    assert drv.serial is fake_serial


@pytest.mark.parametrize("max_speed", [0, -1, MAX_SPEED + 1, 1000])
def test_init_max_speed_out_of_range_raises(fake_serial, max_speed):
    with pytest.raises(MotorError):
        ArduinoMotorDriver(fake_serial, max_speed=max_speed)


# --------------------------------------------------------------------------- #
# is_enabled
# --------------------------------------------------------------------------- #
def test_is_enabled_reflects_serial(fake_serial):
    drv = ArduinoMotorDriver(fake_serial)
    assert drv.is_enabled() is True
    fake_serial.set_connected(False)
    assert drv.is_enabled() is False


def test_arudino_driver_satisfies_motor_driver_protocol(fake_serial):
    assert isinstance(ArduinoMotorDriver(fake_serial), MotorDriver)


# --------------------------------------------------------------------------- #
# set_speed / stop: clamping + rejection (fake serial, isolated)
# --------------------------------------------------------------------------- #
def test_set_speed_clamps_to_driver_max(fake_serial):
    drv = ArduinoMotorDriver(fake_serial, max_speed=100)
    drv.set_speed(500, -500)
    assert fake_serial.mv == [(100, -100)]


def test_set_speed_passes_in_range_unchanged(fake_serial):
    drv = ArduinoMotorDriver(fake_serial, max_speed=255)
    drv.set_speed(80, -40)
    assert fake_serial.mv == [(80, -40)]


def test_set_speed_rejection_raises_motor_error(fake_serial):
    fake_serial.ok = False
    fake_serial.raw = "ERR RANGE out of range"
    drv = ArduinoMotorDriver(fake_serial)
    with pytest.raises(MotorError) as exc:
        drv.set_speed(10, 10)
    assert "ERR RANGE" in str(exc.value)


def test_stop_calls_serial_stop(fake_serial):
    drv = ArduinoMotorDriver(fake_serial)
    drv.stop()
    assert fake_serial.stops == 1


def test_stop_rejection_raises_motor_error(fake_serial):
    fake_serial.ok = False
    fake_serial.raw = "ERR LINK down"
    drv = ArduinoMotorDriver(fake_serial)
    with pytest.raises(MotorError) as exc:
        drv.stop()
    assert "ERR LINK" in str(exc.value)


# --------------------------------------------------------------------------- #
# End-to-end: real ArduinoSerial over the mock transport
# --------------------------------------------------------------------------- #
def _real_serial():
    t = MockSerialTransport()
    s = ArduinoSerial(t, timeout=0.5)
    s.connect()
    return s, t


def test_set_speed_end_to_end_updates_motors():
    s, t = _real_serial()
    drv = ArduinoMotorDriver(s)
    drv.set_speed(120, 120)
    assert t.motor_state == (120, 120)


def test_stop_end_to_end_zeroes_motors():
    s, t = _real_serial()
    drv = ArduinoMotorDriver(s)
    drv.set_speed(150, -30)
    assert t.motor_state == (150, -30)
    drv.stop()
    assert t.motor_state == (0, 0)


def test_is_enabled_end_to_end_tracks_connection():
    s, _ = _real_serial()
    drv = ArduinoMotorDriver(s)
    assert drv.is_enabled() is True
    s.disconnect()
    assert drv.is_enabled() is False


# --------------------------------------------------------------------------- #
# Fake serial — a minimal stand-in exposing only the ArduinoSerial surface the
# motor driver depends on (is_connected / move / stop).
# --------------------------------------------------------------------------- #
class _FakeSerial:
    def __init__(self, ok: bool = True, connected: bool = True):
        self.ok = ok
        self.raw = "ACK MOVE L=0 R=0"
        self._connected = connected
        self.mv: List[Tuple[int, int]] = []
        self.stops = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_connected(self, value: bool) -> None:
        self._connected = value

    def move(self, left: int, right: int) -> types.SimpleNamespace:
        self.mv.append((left, right))
        return types.SimpleNamespace(ok=self.ok, raw=self.raw)

    def stop(self) -> types.SimpleNamespace:
        self.stops += 1
        return types.SimpleNamespace(ok=self.ok, raw=self.raw)
