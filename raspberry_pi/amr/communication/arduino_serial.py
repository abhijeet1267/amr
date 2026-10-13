"""High-level Pi-side serial API.

:mod:`amr.communication.arduino_serial` wraps a *transport* (real USB serial or
a mock) and exposes a clean, synchronous command API:

    ser = ArduinoSerial(ArduinoSerialTransport(port="/dev/ttyACM0"))
    ser.connect()
    ser.ping()
    ser.move(left=150, right=150)
    ser.stop()

Design notes
------------
* **Transport is pluggable** — anything implementing :class:`SerialTransport`
  works. :class:`ArduinoSerialTransport` uses pyserial (imported lazily so mock
  / dev mode runs without pyserial installed). Tests and ``--mock`` mode use
  :class:`amr.mocks.mock_serial.MockSerialTransport`.
* **Synchronous request/response** — each call writes a command and reads until
  it sees the expected response, an ``ERR``, or a timeout. All ``SENSOR``
  reports (polled or unsolicited) are buffered into
  :attr:`ArduinoSerial.last_sensor`.
* **Safe failure** — timeouts raise :class:`SerialTimeout`; a bad link raises
  :class:`ConnectionError`. Callers (the robot manager) decide the safe action.
"""

from __future__ import annotations

import time
from typing import Optional, Protocol

from ..logging import get_logger
from . import protocol as P


class SerialTimeout(Exception):
    """No expected response was received within the timeout window."""


class SerialTransport(Protocol):
    """Minimal transport interface (line-oriented).

    Implementations must be safe to call repeatedly and must return ``None``
    from :meth:`read_line` when no data is available (rather than blocking
    forever or raising).
    """

    def write(self, line: str) -> None:
        """Write one command line (newline added by the transport)."""
        ...

    def read_line(self, timeout: float) -> Optional[str]:
        """Return one received line, or ``None`` if none within timeout."""
        ...

    def open(self) -> None:
        ...

    def close(self) -> None:
        ...

    @property
    def is_open(self) -> bool:
        ...


class ArduinoSerialTransport:
    """pyserial-backed transport. pyserial is imported lazily."""

    #: Opening the port toggles DTR, which RESETS an Arduino UNO. The board then
    #: spends ~1.5 s in its bootloader before the sketch runs, so a command sent
    #: immediately gets no answer. Measured on the real UNO (2026-10-13):
    #: PING right after open -> b'' ; PING after a 2 s settle -> b'PONG'.
    #: Every mock is instant, so no test could catch this — only hardware.
    DEFAULT_SETTLE_S = 2.0

    #: Known Arduino USB (vid, pid) signatures, used only to *discover* the port
    #: when the configured one is missing. The Uno CDC-ACM reports 2341:0043;
    #: CH340-based clones report 1a86:7523. The stable /dev/serial/by-id symlink
    #: is preferred over these because it does not change on re-enumeration.
    _ARDUINO_SIGNATURES = (
        (0x2341, 0x0043),  # Arduino UNO R3 (CDC ACM)
        (0x1a86, 0x7523),  # CH340G (many "Uno" clones)
    )

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        timeout: float = 1.0,
        settle_s: float = DEFAULT_SETTLE_S,
    ):
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._settle_s = settle_s
        self._ser = None

    def _resolve_port(self) -> str:
        """The port to open: the configured one, or a discovered Arduino.

        The device node for a USB CDC Arduino is *not* stable — the board can
        re-enumerate as ``/dev/ttyACM0`` one boot and ``/dev/ttyACM1`` the next
        (observed on the real UNO, 2026-10-13). A hard-coded port then fails with
        "No such file or directory" and the whole stack aborts at startup. So:
        if the configured port exists, use it (config wins); otherwise discover
        the Arduino, preferring the stable ``/dev/serial/by-id`` symlink and
        falling back to a VID:PID match. This is read-only discovery — it opens
        no port and toggles no pins.
        """
        import os

        if os.path.exists(self._port):
            return self._port

        # 1) The stable by-id symlink: usb-Arduino_<serial> or usb-1a86_<serial>.
        byid = "/dev/serial/by-id"
        try:
            for name in sorted(os.listdir(byid)):
                if name.lower().startswith("usb-arduino") or \
                   name.lower().startswith("usb-2341") or \
                   name.lower().startswith("usb-1a86") or \
                   "arduino" in name.lower():
                    return os.path.join(byid, name)
        except OSError:
            pass

        # 2) Match by the Arduino's USB VID:PID via pyserial's list_ports.
        try:
            import serial.tools.list_ports as lp

            for cand in lp.comports():
                if (cand.vid, cand.pid) in self._ARDUINO_SIGNATURES:
                    return cand.device
        except Exception:  # noqa: BLE001 - discovery is best-effort
            pass

        # 3) Nothing found: keep the configured port so the caller raises the
        #    usual, actionable "could not open the controller link" error.
        return self._port

    def open(self) -> None:
        import serial  # lazy import — optional dependency

        if self._ser is None:
            self._ser = serial.Serial(
                self._resolve_port(), self._baudrate, timeout=self._timeout
            )
            # Let the board finish rebooting before we speak to it, then drop
            # whatever it printed in the meantime (the `AMR FW READY` banner and
            # any partial line). Without this the first PING always times out.
            if self._settle_s > 0:
                time.sleep(self._settle_s)
            self._ser.reset_input_buffer()

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def write(self, line: str) -> None:
        if self._ser is None:
            raise ConnectionError("serial transport is not open")
        self._ser.write((line + "\r\n").encode("utf-8"))
        self._ser.flush()

    def read_line(self, timeout: float) -> Optional[str]:
        if self._ser is None:
            raise ConnectionError("serial transport is not open")
        raw = self._ser.readline()
        if not raw:
            return None
        text = raw.decode("utf-8", errors="replace").strip()
        return text or None


class ArduinoSerial:
    """Synchronous command API over a :class:`SerialTransport`."""

    def __init__(
        self,
        transport: SerialTransport,
        timeout: float = 1.0,
        logger=None,
    ):
        self._transport = transport
        self._timeout = timeout
        self.log = logger or get_logger("serial")
        #: Most recent sensor report seen (polling or unsolicited).
        self.last_sensor: Optional[P.Response] = None
        #: Most recent DHT11 environment report seen (polling or unsolicited).
        self.last_env: Optional[P.Response] = None
        #: Most recent gas report seen (polling or unsolicited).
        self.last_gas: Optional[P.Response] = None

    # --- lifecycle --------------------------------------------------------- #
    def connect(self) -> None:
        self._transport.open()
        self.log.info("serial transport opened")

    def disconnect(self) -> None:
        self._transport.close()
        self.log.info("serial transport closed")

    @property
    def is_connected(self) -> bool:
        return self._transport.is_open

    # --- commands ---------------------------------------------------------- #
    def ping(self) -> bool:
        """Return ``True`` if the controller answers ``PING`` with ``PONG``."""
        try:
            resp = self._send_and_read(P.build_ping(), {"PONG"})
            return resp.kind == "PONG"
        except (SerialTimeout, ConnectionError):
            return False

    def version(self) -> P.Response:
        return self._send_and_read(P.build_version(), {"VERSION"})

    def status(self) -> P.Response:
        return self._send_and_read(P.build_status(), {"STATUS"})

    def sensor(self) -> P.Response:
        """Request and return an immediate sensor report."""
        return self._send_and_read(P.build_sensor(), {"SENSOR"})

    def env(self) -> P.Response:
        """Request a DHT11 temperature/humidity reading."""
        return self._send_and_read(P.build_env(), {"ENV"})

    def gas(self) -> P.Response:
        """Request an MQ gas sensor raw reading."""
        return self._send_and_read(P.build_gas(), {"GAS"})

    def lcd(self, line0: str = "", line1: str = "") -> P.Response:
        """Set the 16x2 I2C LCD to two lines of text."""
        return self._send_and_read(P.build_lcd(line0, line1), {"ACK"})

    def buzz(self, freq_hz: int = 0, duration_ms: Optional[int] = None) -> P.Response:
        """Drive the buzzer. ``freq_hz`` 0 stops it."""
        return self._send_and_read(P.build_buzz(freq_hz, duration_ms), {"ACK"})

    def move(self, left: int, right: int) -> P.Response:
        cmd = P.build_move(left, right)
        return self._send_and_read(cmd, {"ACK"})

    def stop(self) -> P.Response:
        return self._send_and_read(P.build_stop(), {"ACK"})

    def legacy(self, char: str) -> P.Response:
        """Send a legacy single-character command (F/B/L/R/S)."""
        cmd = P.legacy_command(char)
        return self._send_and_read(cmd, {"ACK"})

    # --- internals --------------------------------------------------------- #
    def _send_and_read(self, command: str, expected: set, timeout: Optional[float] = None) -> P.Response:
        if not self._transport.is_open:
            raise ConnectionError("serial transport is not open; call connect()")

        self.log.info("TX %s", command)
        self._transport.write(command)

        limit = timeout if timeout is not None else self._timeout
        deadline = time.monotonic() + limit
        malformed = 0
        max_malformed = 25

        while time.monotonic() < deadline:
            line = self._transport.read_line(self._timeout)
            if line is None:
                time.sleep(0.005)
                continue
            resp = P.parse_response(line)
            self.log.info("RX %s", line)

            # Sensor telemetry: always buffer (polled or unsolicited).
            if resp.kind == "SENSOR":
                self.last_sensor = resp
                if "SENSOR" in expected:
                    return resp
                continue

            # Environment telemetry: buffer, same rule as SENSOR.
            if resp.kind == "ENV":
                self.last_env = resp
                if "ENV" in expected:
                    return resp
                continue

            # Gas telemetry: buffer, same rule as SENSOR.
            if resp.kind == "GAS":
                self.last_gas = resp
                if "GAS" in expected:
                    return resp
                continue

            # A response we were expecting, or any explicit error -> terminal.
            if resp.kind in expected or resp.kind == "ERR":
                return resp

            # Anything else (unknown / empty / stray) — tolerate a few, then fail.
            if resp.kind != "EMPTY":
                malformed += 1
                if malformed >= max_malformed:
                    raise P.ProtocolParseError(
                        f"too many unparseable lines; last={line!r}"
                    )
            continue

        raise SerialTimeout(f"no response for {command!r} within {limit}s")
