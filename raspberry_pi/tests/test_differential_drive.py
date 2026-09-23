"""Tests for the control layer: differential drive + Arduino motor driver.

All tests run offline against :class:`MockMotorDriver` and
:class:`MockSerialTransport` — no hardware, no serial port.
"""

from __future__ import annotations

import pytest

from amr.control import (
    ArduinoMotorDriver,
    DifferentialDrive,
    MotorDriver,
    clamp_speed,
)
from amr.control.motor_controller import MotorError
from amr.communication.arduino_serial import ArduinoSerial, SerialTimeout
from amr.mocks import MockMotorDriver, MockSerialTransport


# --------------------------------------------------------------------------- #
# clamp_speed
# --------------------------------------------------------------------------- #
def test_clamp_speed_within_range_is_identity():
    assert clamp_speed(120) == 120
    assert clamp_speed(-120) == -120
    assert clamp_speed(0) == 0


def test_clamp_speed_hits_protocol_bounds():
    assert clamp_speed(300) == 255
    assert clamp_speed(-300) == -255


def test_clamp_speed_respects_custom_bounds():
    assert clamp_speed(200, min_speed=-100, max_speed=100) == 100
    assert clamp_speed(-200, min_speed=-100, max_speed=100) == -100


# --------------------------------------------------------------------------- #
# DifferentialDrive over MockMotorDriver
# --------------------------------------------------------------------------- #
def _make_drive(max_speed: int = 255):
    driver = MockMotorDriver()
    drive = DifferentialDrive(driver, max_speed=max_speed)
    return driver, drive


def test_forward_sets_equal_positive_speeds():
    driver, drive = _make_drive()
    drive.forward(120)
    assert (driver.left, driver.right) == (120, 120)


def test_backward_sets_equal_negative_speeds():
    driver, drive = _make_drive()
    drive.backward(120)
    assert (driver.left, driver.right) == (-120, -120)


def test_backward_treats_argument_as_magnitude():
    driver, drive = _make_drive()
    drive.backward(-120)
    assert (driver.left, driver.right) == (-120, -120)


def test_rotate_left_is_in_place():
    driver, drive = _make_drive()
    drive.rotate_left(100)
    assert (driver.left, driver.right) == (-100, 100)


def test_rotate_right_is_in_place():
    driver, drive = _make_drive()
    drive.rotate_right(100)
    assert (driver.left, driver.right) == (100, -100)


def test_turn_left_is_arc():
    driver, drive = _make_drive()
    drive.turn_left(90)
    assert (driver.left, driver.right) == (0, 90)


def test_turn_right_is_arc():
    driver, drive = _make_drive()
    drive.turn_right(90)
    assert (driver.left, driver.right) == (90, 0)


def test_move_clamps_raw_speeds_to_max_speed():
    driver, drive = _make_drive(max_speed=150)
    drive.move(300, -300)
    assert (driver.left, driver.right) == (150, -150)


def test_named_methods_clamp_to_max_speed():
    driver, drive = _make_drive(max_speed=100)
    drive.forward(255)
    assert (driver.left, driver.right) == (100, 100)
    drive.rotate_right(255)
    assert (driver.left, driver.right) == (100, -100)


def test_stop_zeros_speeds_and_records_it():
    driver, drive = _make_drive()
    drive.forward(100)
    drive.stop()
    assert (driver.left, driver.right) == (0, 0)
    assert driver.history[-1] == (0, 0)


def test_invalid_max_speed_is_rejected():
    with pytest.raises(ValueError):
        DifferentialDrive(MockMotorDriver(), max_speed=0)
    with pytest.raises(ValueError):
        DifferentialDrive(MockMotorDriver(), max_speed=300)


def test_mock_driver_satisfies_motor_driver_protocol():
    assert isinstance(MockMotorDriver(), MotorDriver)


# --------------------------------------------------------------------------- #
# ArduinoMotorDriver over MockSerialTransport
# --------------------------------------------------------------------------- #
def _make_serial_driver(**transport_kwargs):
    transport = MockSerialTransport(**transport_kwargs)
    serial = ArduinoSerial(transport, timeout=0.05)
    serial.connect()
    driver = ArduinoMotorDriver(serial, max_speed=255)
    return transport, serial, driver


def test_arduino_driver_move_sends_protocol_move():
    transport, _, driver = _make_serial_driver()
    driver.set_speed(120, -60)
    assert transport.written[-1] == "MOVE L=120 R=-60"
    assert transport.motor_state == (120, -60)


def test_arduino_driver_stop_sends_protocol_stop():
    transport, _, driver = _make_serial_driver()
    driver.set_speed(100, 100)
    driver.stop()
    assert transport.written[-1] == "STOP"
    assert transport.motor_state == (0, 0)


def test_arduino_driver_clamps_to_max_speed():
    transport, _, driver = _make_serial_driver()
    driver.set_speed(999, -999)
    assert transport.motor_state == (255, -255)


def test_arduino_driver_custom_max_speed():
    transport, serial, _ = _make_serial_driver()
    driver = ArduinoMotorDriver(serial, max_speed=150)
    driver.set_speed(200, -200)
    assert transport.motor_state == (150, -150)


def test_arduino_driver_is_enabled_tracks_connection():
    transport, serial, driver = _make_serial_driver()
    assert driver.is_enabled() is True
    serial.disconnect()
    assert driver.is_enabled() is False


def test_arduino_driver_set_speed_when_disconnected_raises():
    transport, serial, driver = _make_serial_driver()
    serial.disconnect()
    with pytest.raises(ConnectionError):
        driver.set_speed(10, 10)


def test_arduino_driver_timeout_propagates_serial_timeout():
    # First command is answered; the controller then goes silent (dead link).
    transport, serial, driver = _make_serial_driver(drop_after=1)
    driver.set_speed(10, 10)
    with pytest.raises(SerialTimeout):
        driver.set_speed(20, 20)


class _RejectingTransport:
    """Transport whose controller rejects every command with ERR (bad state)."""

    def __init__(self):
        self._open = False
        self._pending = None

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def write(self, line: str) -> None:
        if not self._open:
            raise ConnectionError("not open")
        self._pending = "ERR STATE safety active"

    def read_line(self, timeout: float):
        line, self._pending = self._pending, None
        return line


def test_arduino_driver_explicit_rejection_raises_motor_error():
    transport = _RejectingTransport()
    serial = ArduinoSerial(transport, timeout=0.05)
    serial.connect()
    driver = ArduinoMotorDriver(serial)

    with pytest.raises(MotorError):
        driver.set_speed(10, 10)
    with pytest.raises(MotorError):
        driver.stop()


def test_arduino_driver_invalid_max_speed_raises_motor_error():
    with pytest.raises(MotorError):
        ArduinoMotorDriver(ArduinoSerial(MockSerialTransport()), max_speed=0)
    with pytest.raises(MotorError):
        ArduinoMotorDriver(ArduinoSerial(MockSerialTransport()), max_speed=300)


# --------------------------------------------------------------------------- #
# Full offline stack: DifferentialDrive -> ArduinoMotorDriver -> MockSerial
# --------------------------------------------------------------------------- #
def test_differential_drive_over_arduino_driver():
    transport, serial, adriver = _make_serial_driver()
    drive = DifferentialDrive(adriver, max_speed=200)

    drive.rotate_left(300)
    assert transport.motor_state == (-200, 200)

    drive.forward(100)
    assert transport.motor_state == (100, 100)

    drive.backward(50)
    assert transport.motor_state == (-50, -50)

    drive.stop()
    assert transport.motor_state == (0, 0)
