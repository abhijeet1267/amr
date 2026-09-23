"""Pi <-> Arduino serial communication layer.

* :mod:`amr.communication.protocol` — pure protocol logic (no I/O).
* :mod:`amr.communication.arduino_serial` — high-level command API over a
  transport (real serial or a mock).
"""

from .protocol import (
    PROTOCOL_VERSION,
    MIN_SPEED,
    MAX_SPEED,
    ProtocolError,
    ProtocolRangeError,
    ProtocolParseError,
    Response,
    build_move,
    build_stop,
    build_ping,
    build_status,
    build_version,
    build_sensor,
    legacy_command,
    parse_response,
)
from .arduino_serial import (
    ArduinoSerial,
    ArduinoSerialTransport,
    SerialTransport,
    SerialTimeout,
)

__all__ = [
    "PROTOCOL_VERSION",
    "MIN_SPEED",
    "MAX_SPEED",
    "ProtocolError",
    "ProtocolRangeError",
    "ProtocolParseError",
    "Response",
    "build_move",
    "build_stop",
    "build_ping",
    "build_status",
    "build_version",
    "build_sensor",
    "legacy_command",
    "parse_response",
    "ArduinoSerial",
    "ArduinoSerialTransport",
    "SerialTransport",
    "SerialTimeout",
]
