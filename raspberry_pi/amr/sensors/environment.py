"""Environmental sensor access over the serial protocol (DHT11 + MQ gas).

Mirrors :mod:`amr.sensors.ultrasonic`: the Pi holds no pins and touches no
hardware — it issues ``ENV`` / ``GAS`` commands and validates the readings.

* A DHT11 value of ``-1`` means *invalid / not measured* (no sensor, failed
  read, or checksum mismatch) and is normalised to ``None`` — never a fake 0.
* A gas raw value of ``-1`` means *no pin assigned* (the shipped default) and
  is normalised to ``None``. These readings are **telemetry only**: they never
  reach :class:`~amr.robot.robot_manager.RobotManager` and cannot block motion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..communication import protocol as P
from ..communication.arduino_serial import ArduinoSerial


@dataclass(frozen=True)
class EnvironmentReading:
    """One validated snapshot from the DHT11 and MQ gas sensors.

    All fields are ``None`` until a valid reading arrives. ``None`` is the
    *absent* sentinel (matching the ultrasonic contract), never a value of 0.
    """

    temperature_c: Optional[int] = None
    humidity_pct: Optional[int] = None
    gas_raw: Optional[int] = None      # 0..1023 ADC count, or None

    @classmethod
    def from_env(cls, resp: P.Response) -> "EnvironmentReading":
        """Build a reading from a parsed ``ENV`` response (gas stays None)."""
        return cls(
            temperature_c=cls._clean(resp.temperature_c),
            humidity_pct=cls._clean(resp.humidity_pct),
            gas_raw=None,
        )

    @classmethod
    def merge(cls, base: "EnvironmentReading", gas_resp: P.Response) -> "EnvironmentReading":
        """Combine an ENV reading with a GAS reading into one snapshot."""
        return cls(
            temperature_c=base.temperature_c,
            humidity_pct=base.humidity_pct,
            gas_raw=cls._clean(gas_resp.gas_raw),
        )

    @staticmethod
    def _clean(value: Optional[int]) -> Optional[int]:
        """``None`` or ``-1`` (invalid/unmeasured) -> ``None``; else the value."""
        if value is None or value < 0:
            return None
        return value

    def all_invalid(self) -> bool:
        return all(v is None for v in (self.temperature_c, self.humidity_pct, self.gas_raw))

    def as_dict(self) -> dict:
        return {
            "temperature_c": self.temperature_c,
            "humidity_pct": self.humidity_pct,
            "gas_raw": self.gas_raw,
        }


class EnvironmentManager:
    """Validates and exposes DHT11 / gas readings from the controller."""

    def __init__(self, serial: ArduinoSerial):
        self._serial = serial

    def poll_env(self) -> EnvironmentReading:
        """Issue an ``ENV`` command and return the validated reading."""
        resp = self._serial.env()
        return EnvironmentReading.from_env(resp)

    def poll_gas(self) -> int:
        """Issue a ``GAS`` command; returns the raw count or ``-1``."""
        resp = self._serial.gas()
        return -1 if resp.gas_raw is None else resp.gas_raw

    def poll(self) -> EnvironmentReading:
        """Full environment snapshot: one ``ENV`` plus one ``GAS`` command.

        Both commands are sent in sequence; a failure of either is recorded as
        ``None`` rather than raising, so the telemetry section degrades
        gracefully (the same fail-safe rule as the ultrasonic layer).
        """
        try:
            env = self.poll_env()
        except Exception:  # noqa: BLE001 - a sensor fault must not break the loop
            env = EnvironmentReading()
        try:
            gas_resp = self._serial.gas()
        except Exception:  # noqa: BLE001
            gas_resp = P.Response(kind="GAS", raw="", ok=True, gas_raw=None)
        return EnvironmentReading.merge(env, gas_resp)

    def latest(self) -> Optional[EnvironmentReading]:
        """Most recent ENV+GAS readings buffered by the serial layer, if any."""
        env_resp = self._serial.last_env
        gas_resp = self._serial.last_gas
        if env_resp is None and gas_resp is None:
            return None
        env = (
            EnvironmentReading.from_env(env_resp)
            if env_resp is not None
            else EnvironmentReading()
        )
        if gas_resp is None:
            return env
        return EnvironmentReading.merge(env, gas_resp)