"""Motor driver layer (Pi side).

Defines the motor abstraction and the real (Arduino-backed) implementation:

* :class:`MotorDriver` — a structural interface (``typing.Protocol``) that
  every motor driver must satisfy.
  :class:`~amr.mocks.mock_motor.MockMotorDriver` satisfies it without
  inheritance, so the differential-drive layer is fully testable offline.
* :class:`ArduinoMotorDriver` — drives the motors through the structured
  serial protocol (``MOVE`` / ``STOP``).

PWM note
--------
Real speed control on the L298N (ENA/ENB) lives *behind the firmware HAL*
(``firmware/.../motor_control.h``) and stays ``NOT_VERIFIED`` until the
wiring is physically confirmed. This driver therefore sends *speed commands*
and never touches pins — the controller owns the hardware.

Sign convention (must match protocol + firmware)
------------------------------------------------
positive = forward, negative = reverse, 0 = stopped.

Error contract
--------------
* :class:`MotorError` — the driver is in a bad state, or the controller
  *explicitly rejected* a command (``ERR ...`` response).
* :class:`~amr.communication.arduino_serial.SerialTimeout` /
  ``ConnectionError`` — link-layer problems. They propagate *unwrapped* so
  the caller (robot manager / safety) can distinguish "the controller said
  no" from "the controller went silent".
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..communication import protocol as P
from ..communication.arduino_serial import ArduinoSerial, SerialTimeout


class MotorError(Exception):
    """Raised when a motor command is rejected or the driver is unusable."""


def clamp_speed(
    value: int,
    min_speed: int = P.MIN_SPEED,
    max_speed: int = P.MAX_SPEED,
) -> int:
    """Clamp ``value`` into ``[min_speed, max_speed]``.

    Unlike the protocol builder (:func:`amr.communication.protocol.build_move`),
    this never raises — it is the defensive last line before a command leaves
    the Pi.
    """
    iv = int(value)
    return max(min_speed, min(max_speed, iv))


@runtime_checkable
class MotorDriver(Protocol):
    """Structural interface for motor drivers (Mock + Arduino both fit)."""

    def set_speed(self, left: int, right: int) -> None:
        """Command the left/right wheel speeds (clamped by the driver)."""
        ...

    def stop(self) -> None:
        """Command an immediate stop."""
        ...

    def is_enabled(self) -> bool:
        """Return ``True`` when the driver can accept commands."""
        ...


class ArduinoMotorDriver:
    """A :class:`MotorDriver` backed by the structured serial protocol.

    Speeds are clamped to ``[−max_speed, +max_speed]`` before transmission;
    ``max_speed`` should come from ``config/robot.yaml`` (``motors.max_speed``)
    and must be a physically validated value.
    """

    def __init__(self, serial: ArduinoSerial, max_speed: int = 255):
        if not (1 <= max_speed <= P.MAX_SPEED):
            raise MotorError(f"max_speed {max_speed} out of range [1, {P.MAX_SPEED}]")
        self._serial = serial
        self._max_speed = int(max_speed)

    @property
    def max_speed(self) -> int:
        return self._max_speed

    @property
    def serial(self) -> ArduinoSerial:
        """The underlying serial API (for status/sensor passthrough)."""
        return self._serial

    def is_enabled(self) -> bool:
        """``True`` while the serial link is open."""
        return self._serial.is_connected

    def set_speed(self, left: int, right: int) -> None:
        """Command ``MOVE``; raises :class:`MotorError` on explicit rejection."""
        left = clamp_speed(left, -self._max_speed, self._max_speed)
        right = clamp_speed(right, -self._max_speed, self._max_speed)
        resp = self._serial.move(left, right)
        if not resp.ok:
            raise MotorError(f"controller rejected MOVE: {resp.raw!r}")

    def stop(self) -> None:
        """Command ``STOP``; raises :class:`MotorError` on explicit rejection."""
        resp = self._serial.stop()
        if not resp.ok:
            raise MotorError(f"controller rejected STOP: {resp.raw!r}")
