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

    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 1.0):
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._ser = None

    def open(self) -> None:
        import serial  # lazy import — optional dependency

        if self._ser is None:
            self._ser = serial.Serial(
                self._port, self._baudrate, timeout=self._timeout
            )
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
