"""Mock serial transport that faithfully emulates the Arduino controller.

This is a protocol-faithful fake: it parses real command lines and produces the
exact responses the firmware would emit. That means the *whole* high-level
stack (command API -> robot manager -> safety -> warehouse) can be exercised
with no hardware, and the same code path is used in unit tests and in
``python -m amr.main --mock``.

The mock tracks:

* current left/right motor speeds
* current robot mode (for ``STATUS``)
* front/left/right/rear ultrasonic distances
* DHT11 temperature/humidity and MQ gas readings
* the last LCD text and buzzer command (records only — display/audio have no
  effect the Pi can observe)
* an optional *comm-loss* simulation (``drop_after``) to test the Pi-side
  reaction to a crashed / disconnected Arduino (see docs/safety.md).
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ..communication import protocol as P


class MockSerialTransport:
    """Implements :class:`amr.communication.arduino_serial.SerialTransport`."""

    def __init__(
        self,
        start_distances: tuple[int, int, int, int] = (80, 40, 90, 120),
        drop_after: Optional[int] = None,
    ):
        self._open = False
        self._left = 0
        self._right = 0
        self._mode = "IDLE"
        # (front, left, right, rear) in cm
        self._dist: List[int] = list(start_distances)
        # DHT11 reading; -1 == invalid / not measured (matches the firmware).
        self._temp_c = 25
        self._humidity_pct = 50
        # MQ gas raw ADC count; -1 == no pin assigned (the shipped default).
        self._gas_raw = -1
        #: Last LCD line pair written (records only).
        self.lcd_text: Optional[Tuple[str, str]] = None
        #: Last buzzer command: (freq_hz, duration_ms_or_None).
        self.buzzer: Optional[Tuple[int, Optional[int]]] = None
        self.drop_after = drop_after
        self._cmd_count = 0
        #: Every command line written by the Pi, in order (for assertions).
        self.written: List[str] = []

    # --- SerialTransport interface ---------------------------------------- #
    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def write(self, line: str) -> None:
        if not self._open:
            raise ConnectionError("mock serial is not open")
        self.written.append(line)
        self._cmd_count += 1

    def read_line(self, timeout: float) -> Optional[str]:
        if not self._open:
            return None
        # Simulate a dead link: once the command count exceeds the limit, the
        # controller stops answering entirely (Pi-side must treat as lost).
        if self.drop_after is not None and self._cmd_count > self.drop_after:
            return None
        if not self.written:
            return None
        # Synchronous model: respond to the most recent command.
        return self._respond(self.written[-1])

    # --- test / mock-mode controls ---------------------------------------- #
    @property
    def motor_state(self) -> tuple[int, int]:
        return self._left, self._right

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def set_distances(self, front: int, left: int, right: int, rear: int) -> None:
        self._dist = [front, left, right, rear]

    def set_environment(self, temperature_c: int, humidity_pct: int) -> None:
        """Set the DHT11 reading. Use -1 for "invalid / not measured"."""
        self._temp_c = temperature_c
        self._humidity_pct = humidity_pct

    def set_gas(self, raw: int) -> None:
        """Set the MQ gas raw ADC count. -1 == no pin assigned."""
        self._gas_raw = raw

    # --- protocol emulation ----------------------------------------------- #
    def _respond(self, cmd: str) -> str:
        c = (cmd or "").strip()
        up = c.upper()

        if up == P.PING:
            return "PONG"
        if up == P.VERSION:
            return f"VERSION {P.PROTOCOL_VERSION}"
        if up == P.STOP:
            self._left = 0
            self._right = 0
            return "ACK STOP"
        if up == P.STATUS:
            return f"STATUS L={self._left} R={self._right} MODE={self._mode}"
        if up == P.SENSOR:
            f, l, r, b = self._dist
            return f"SENSOR F={f} L={l} R={r} B={b}"
        if up == P.ENV:
            return f"ENV T={self._temp_c} H={self._humidity_pct}"
        if up == P.GAS:
            return f"GAS RAW={self._gas_raw}"

        # LCD <line0>|<line1> : text is case-sensitive in the firmware, and the
        # mock records it verbatim so a test can assert what was displayed.
        if up.startswith(P.LCD):
            rest = c[3:].strip()
            if "|" in rest:
                line0, line1 = rest.split("|", 1)
            else:
                line0, line1 = rest, ""
            self.lcd_text = (line0.strip(), line1.strip())
            return "ACK LCD"

        # BUZZ <freqHz> [<ms>]
        if up.startswith(P.BUZZ):
            rest = c[4:].strip()
            parts = rest.split()
            try:
                freq = int(parts[0]) if parts else 0
            except ValueError:
                return "ERR PARSE bad buzzer frequency"
            if freq != 0 and (freq < P.MIN_BUZZ_HZ or freq > P.MAX_BUZZ_HZ):
                return "ERR RANGE out of range"
            ms: Optional[int] = None
            if len(parts) > 1:
                try:
                    ms = int(parts[1])
                except ValueError:
                    return "ERR PARSE bad buzzer duration"
                if ms < 0:
                    return "ERR RANGE out of range"
            self.buzzer = (freq, ms)
            return f"ACK BUZZ {freq}"

        m = re.match(r"^MOVE\s+L=(-?\d+)\s+R=(-?\d+)$", up)
        if m:
            left = int(m.group(1))
            right = int(m.group(2))
            if not (P.MIN_SPEED <= left <= P.MAX_SPEED and P.MIN_SPEED <= right <= P.MAX_SPEED):
                return "ERR RANGE out of range"
            self._left = left
            self._right = right
            return f"ACK MOVE L={left} R={right}"

        if up in P.LEGACY_PRESETS:
            self._left, self._right = P.LEGACY_PRESETS[up]
            return f"ACK {up}"

        return f"ERR UNKNOWN {up}"
