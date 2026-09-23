"""In-process hardware mocks for development and testing.

These let the *entire* high-level stack run with no physical robot attached:

* :class:`~amr.mocks.mock_serial.MockSerialTransport` — emulates the Arduino
  (responds to real protocol commands, tracks motor state, reports sensors).
* :class:`~amr.mocks.mock_motor.MockMotorDriver` — records commanded speeds.
* :class:`~amr.mocks.mock_sensor.MockUltrasonicSensor` — programmable ranges.
* :class:`~amr.mocks.mock_camera.MockCamera` — fake availability / frames.
"""

from .mock_serial import MockSerialTransport
from .mock_motor import MockMotorDriver
from .mock_sensor import MockUltrasonicSensor
from .mock_camera import MockCamera

__all__ = [
    "MockSerialTransport",
    "MockMotorDriver",
    "MockUltrasonicSensor",
    "MockCamera",
]
