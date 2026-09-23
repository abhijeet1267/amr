"""Ultrasonic sensor access over the serial protocol.

See the package docstring for the design. This module is pure Pi-side logic:
no pins, no SPI — only the structured protocol (``SENSOR`` command /
response) plus validation against :class:`SafetyConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..communication import protocol as P
from ..communication.arduino_serial import ArduinoSerial
from ..utils.config import SafetyConfig


@dataclass(frozen=True)
class UltrasonicReading:
    """One validated snapshot from the four ultrasonic sensors (cm).

    ``None`` means *invalid* (no echo, out of range, or field missing) —
    never "very far".
    """

    front: Optional[int] = None
    left: Optional[int] = None
    right: Optional[int] = None
    rear: Optional[int] = None

    @classmethod
    def from_response(cls, resp: P.Response) -> "UltrasonicReading":
        """Build a (raw) reading from a parsed ``SENSOR`` response."""
        return cls(
            front=resp.front,
            left=resp.left,
            right=resp.right,
            rear=resp.rear,
        )

    def all_invalid(self) -> bool:
        """``True`` when no direction has a valid reading."""
        return all(v is None for v in (self.front, self.left, self.right, self.rear))

    def as_dict(self) -> dict:
        return {
            "front": self.front,
            "left": self.left,
            "right": self.right,
            "rear": self.rear,
        }


class UltrasonicManager:
    """Validates and exposes ultrasonic readings from the controller."""

    def __init__(self, serial: ArduinoSerial, config: SafetyConfig):
        self._serial = serial
        self._min = config.sensor_min_valid_cm
        self._max = config.sensor_max_valid_cm

    # --- validation -------------------------------------------------------- #
    def _validate(self, value: Optional[int]) -> Optional[int]:
        """Normalise a raw sensor value; ``None`` when invalid.

        Invalid means: missing, ``-1`` (no echo), or outside the physically
        sensible window configured in ``safety.yaml``.
        """
        if value is None:
            return None
        iv = int(value)
        if iv < 0:
            return None
        if iv < self._min or iv > self._max:
            return None
        return iv

    # --- API --------------------------------------------------------------- #
    def poll(self) -> UltrasonicReading:
        """Issue a ``SENSOR`` command and return the validated reading."""
        resp = self._serial.sensor()
        raw = UltrasonicReading.from_response(resp)
        return UltrasonicReading(
            front=self._validate(raw.front),
            left=self._validate(raw.left),
            right=self._validate(raw.right),
            rear=self._validate(raw.rear),
        )

    def latest(self) -> Optional[UltrasonicReading]:
        """Most recent reading seen (poll or unsolicited), or ``None``."""
        resp = self._serial.last_sensor
        if resp is None:
            return None
        raw = UltrasonicReading.from_response(resp)
        return UltrasonicReading(
            front=self._validate(raw.front),
            left=self._validate(raw.left),
            right=self._validate(raw.right),
            rear=self._validate(raw.rear),
        )
