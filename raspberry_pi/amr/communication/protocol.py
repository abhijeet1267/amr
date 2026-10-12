"""AMR serial protocol — pure, I/O-free logic.

This module is the single source of truth for the text protocol spoken between
the Raspberry Pi and the Arduino. The Arduino firmware (C++) implements the
exact same grammar; :mod:`amr.communication.arduino_serial` handles the I/O and
uses these functions to build/parse lines.

The canonical, human-readable specification is in ``docs/serial_protocol.md``.

Protocol overview (newline-terminated, verbs are case-insensitive):

    Pi -> Arduino (commands)
        PING
        STATUS
        STOP
        VERSION
        SENSOR
        MOVE L=<int> R=<int>          # -255 .. +255
        F | B | L | R | S             # legacy baseline commands (back-compat)
        ENV                           # DHT11 temperature/humidity
        GAS                           # MQ gas sensor raw ADC reading
        LCD <line0>|<line1>           # set the 16x2 I2C LCD
        BUZZ <freqHz> [<ms>]          # buzzer (freq 0 = stop), optional duration

    Arduino -> Pi (responses)
        PONG
        ACK <verb> [args...]          # e.g. "ACK MOVE L=1 R=1"
        ERR <code> [message...]       # e.g. "ERR RANGE out of range"
        STATUS L=<int> R=<int> MODE=<str>
        SENSOR F=<int> L=<int> R=<int> B=<int>
        ENV T=<int> H=<int>           # degC / %RH; -1 == invalid/unmeasured
        GAS RAW=<int>                 # 0..1023; -1 == no pin assigned
        VERSION <semver>
        WATCHDOG TRIGGERED            # unsolicited safety event
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

#: Protocol version reported by the firmware and expected by the Pi.
PROTOCOL_VERSION = "1.1"

#: Allowed speed range. Positive = forward, negative = reverse, 0 = stop.
MIN_SPEED = -255
MAX_SPEED = 255

#: Allowed buzzer frequency range (Hz). 0 is a special "stop" value.
MIN_BUZZ_HZ = 20
MAX_BUZZ_HZ = 20000

# --- command verbs --------------------------------------------------------- #
PING = "PING"
STATUS = "STATUS"
STOP = "STOP"
VERSION = "VERSION"
MOVE = "MOVE"
SENSOR = "SENSOR"
ENV = "ENV"
GAS = "GAS"
LCD = "LCD"
BUZZ = "BUZZ"

# --- legacy single-character commands (existing F/B/L/R/S baseline) -------- #
LEGACY_FORWARD = "F"
LEGACY_BACKWARD = "B"
LEGACY_LEFT = "L"
LEGACY_RIGHT = "R"
LEGACY_STOP = "S"

#: Legacy command -> (left_speed, right_speed) preset. Turning left means the
#: right side goes forward and the left side reverses (and vice-versa).
LEGACY_PRESETS: dict[str, tuple[int, int]] = {
    LEGACY_FORWARD: (1, 1),
    LEGACY_BACKWARD: (-1, -1),
    LEGACY_LEFT: (-1, 1),
    LEGACY_RIGHT: (1, -1),
    LEGACY_STOP: (0, 0),
}

# --- error codes ----------------------------------------------------------- #
ERR_PARSE = "PARSE"
ERR_RANGE = "RANGE"
ERR_STATE = "STATE"
ERR_UNKNOWN = "UNKNOWN"


class ProtocolError(Exception):
    """Base class for protocol-level errors."""


class ProtocolRangeError(ProtocolError):
    """A speed value is outside ``[MIN_SPEED, MAX_SPEED]``."""


class ProtocolParseError(ProtocolError):
    """A command/response could not be parsed."""


# --------------------------------------------------------------------------- #
# Response model
# --------------------------------------------------------------------------- #
@dataclass
class Response:
    """A parsed line received from the Arduino.

    ``kind`` is one of: ``PONG`` ``ACK`` ``ERR`` ``STATUS`` ``SENSOR`` ``ENV``
    ``GAS`` ``VERSION`` ``WATCHDOG`` ``UNKNOWN`` ``EMPTY``.
    ``ok`` is ``False`` only for ``ERR`` and ``UNKNOWN``.
    The optional fields are populated depending on ``kind``.
    """

    kind: str
    raw: str
    ok: bool
    verb: Optional[str] = None
    code: Optional[str] = None
    message: Optional[str] = None
    left: Optional[int] = None
    right: Optional[int] = None
    mode: Optional[str] = None
    front: Optional[int] = None
    rear: Optional[int] = None
    version: Optional[str] = None

    #: ``ENV``: temperature (degC) and humidity (%RH). ``-1`` == invalid.
    temperature_c: Optional[int] = None
    humidity_pct: Optional[int] = None
    #: ``GAS``: raw ADC count (0..1023). ``-1`` == no pin assigned.
    gas_raw: Optional[int] = None

    # convenience predicates ------------------------------------------------ #
    def is_ack(self) -> bool:
        return self.kind == "ACK"

    def is_error(self) -> bool:
        return self.kind == "ERR"

    def is_pong(self) -> bool:
        return self.kind == "PONG"

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"Response({self.kind}, ok={self.ok}, raw={self.raw!r})"


# --------------------------------------------------------------------------- #
# Response parsing (Arduino -> Pi)
# --------------------------------------------------------------------------- #
def _extract_int(line: str, key: str) -> Optional[int]:
    m = re.search(re.escape(key) + r"(-?\d+)", line)
    return int(m.group(1)) if m else None


def _extract_value(line: str, key: str) -> Optional[str]:
    m = re.search(re.escape(key) + r"(\S+)", line)
    return m.group(1) if m else None


def parse_response(line: str) -> Response:
    """Parse a single Arduino->Pi line into a :class:`Response`.

    Parsing is tolerant: a partially-populated ``STATUS``/``SENSOR`` line still
    yields the fields that are present (others ``None``). Unrecognised lines
    become ``kind="UNKNOWN"`` with ``ok=False`` (safe failure, never an
    exception).
    """
    if line is None:
        return Response(kind="UNKNOWN", raw="", ok=False)
    text = line.strip()
    if not text:
        return Response(kind="EMPTY", raw=line, ok=True)

    upper = text.upper()

    if upper == "PONG":
        return Response(kind="PONG", raw=line, ok=True)

    if upper == "WATCHDOG TRIGGERED":
        return Response(kind="WATCHDOG", raw=line, ok=False)

    if upper.startswith("VERSION"):
        version = _extract_value(text, " ")
        # "VERSION 1.0" -> value after the space
        parts = text.split(" ", 1)
        version = parts[1].strip() if len(parts) > 1 else None
        return Response(kind="VERSION", raw=line, ok=True, version=version)

    if upper.startswith("ERR"):
        rest = text[3:].strip()
        parts = rest.split(" ", 1)
        code = parts[0].upper() if parts else ERR_UNKNOWN
        message = parts[1] if len(parts) > 1 else ""
        return Response(kind="ERR", raw=line, ok=False, code=code, message=message)

    if upper.startswith("ACK"):
        rest = text[3:].strip()
        verb = rest.split(" ", 1)[0].upper() if rest else ""
        return Response(kind="ACK", raw=line, ok=True, verb=verb)

    if upper.startswith("STATUS"):
        return Response(
            kind="STATUS",
            raw=line,
            ok=True,
            left=_extract_int(text, "L="),
            right=_extract_int(text, "R="),
            mode=_extract_value(text, "MODE="),
        )

    if upper.startswith("SENSOR"):
        return Response(
            kind="SENSOR",
            raw=line,
            ok=True,
            front=_extract_int(text, "F="),
            left=_extract_int(text, "L="),
            right=_extract_int(text, "R="),
            rear=_extract_int(text, "B="),
        )

    if upper.startswith("ENV"):
        return Response(
            kind="ENV",
            raw=line,
            ok=True,
            temperature_c=_extract_int(text, "T="),
            humidity_pct=_extract_int(text, "H="),
        )

    if upper.startswith("GAS"):
        return Response(
            kind="GAS",
            raw=line,
            ok=True,
            gas_raw=_extract_int(text, "RAW="),
        )

    return Response(kind="UNKNOWN", raw=line, ok=False)


# --------------------------------------------------------------------------- #
# Command building (Pi -> Arduino)
# --------------------------------------------------------------------------- #
def _validate_speed(value: int) -> int:
    iv = int(value)
    if iv < MIN_SPEED or iv > MAX_SPEED:
        raise ProtocolRangeError(
            f"speed {iv} out of range [{MIN_SPEED}, {MAX_SPEED}]"
        )
    return iv


def build_move(left: int, right: int) -> str:
    """Build a ``MOVE`` command, validating both speeds are in range."""
    left = _validate_speed(left)
    right = _validate_speed(right)
    return f"MOVE L={left} R={right}"


def build_stop() -> str:
    return STOP


def build_ping() -> str:
    return PING


def build_status() -> str:
    return STATUS


def build_version() -> str:
    return VERSION


def build_sensor() -> str:
    """Request an immediate sensor report."""
    return SENSOR


def build_env() -> str:
    """Request a DHT11 temperature/humidity reading."""
    return ENV


def build_gas() -> str:
    """Request an MQ gas sensor raw reading."""
    return GAS


def build_lcd(line0: str = "", line1: str = "") -> str:
    """Build an ``LCD`` command: two lines joined by ``|``.

    The firmware splits on the first ``|``. Newlines are stripped because the
    protocol is line-based; a ``|`` inside the text is not supported.
    """
    a = (line0 or "").replace("\r", " ").replace("\n", " ")
    b = (line1 or "").replace("\r", " ").replace("\n", " ")
    return f"{LCD} {a}|{b}"


def build_buzz(freq_hz: int = 0, duration_ms: Optional[int] = None) -> str:
    """Build a ``BUZZ`` command.

    ``freq_hz`` 0 stops the buzzer. A non-zero frequency must be within
    ``[MIN_BUZZ_HZ, MAX_BUZZ_HZ]``. ``duration_ms`` (optional) auto-stops the
    tone after that many milliseconds; ``None`` leaves it running.
    """
    f = int(freq_hz)
    if f != 0 and (f < MIN_BUZZ_HZ or f > MAX_BUZZ_HZ):
        raise ProtocolRangeError(
            f"buzzer frequency {f} out of range [0 or {MIN_BUZZ_HZ}..{MAX_BUZZ_HZ}]"
        )
    if duration_ms is None:
        return f"{BUZZ} {f}"
    ms = int(duration_ms)
    if ms < 0:
        raise ProtocolRangeError(f"buzzer duration {ms} must be >= 0")
    return f"{BUZZ} {f} {ms}"


def legacy_command(char: str) -> str:
    """Normalise a legacy single-character command. Raises if not valid."""
    c = (char or "").strip().upper()
    if c not in LEGACY_PRESETS:
        raise ProtocolParseError(f"invalid legacy command {char!r}")
    return c
