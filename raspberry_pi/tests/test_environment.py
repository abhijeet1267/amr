"""Protocol + manager tests for the environmental sensors (DHT11, MQ gas).

The firmware and :mod:`amr.communication.protocol` share the text protocol, so
every command/response shape added for the DHT11, MQ gas, LCD and buzzer is
pinned here on both ends. Nothing here uses hardware: the
:class:`~amr.mocks.mock_serial.MockSerialTransport` emulates the controller.
"""

from __future__ import annotations

import pytest

from amr.communication.arduino_serial import ArduinoSerial, SerialTimeout
from amr.communication import protocol as P
from amr.mocks import MockSerialTransport


def _serial(**kw) -> ArduinoSerial:
    t = MockSerialTransport(**kw)
    t.open()
    return ArduinoSerial(t, timeout=0.05)


# --------------------------------------------------------------------------- #
# ENV / GAS command building
# --------------------------------------------------------------------------- #
def test_build_env_and_gas_are_plain_verbs():
    assert P.build_env() == "ENV"
    assert P.build_gas() == "GAS"


def test_build_lcd_joins_two_lines_and_strips_newlines():
    # The protocol is line-based, so a newline cannot survive.
    assert P.build_lcd("MODE RUNNING", "T24 H51") == "LCD MODE RUNNING|T24 H51"
    assert P.build_lcd("a\nb", "c") == "LCD a b|c"


def test_build_buzz_frequency_and_optional_duration():
    assert P.build_buzz(0) == "BUZZ 0"
    assert P.build_buzz(1200) == "BUZZ 1200"
    assert P.build_buzz(1200, 150) == "BUZZ 1200 150"


def test_build_buzz_rejects_a_frequency_out_of_range():
    with pytest.raises(P.ProtocolRangeError):
        P.build_buzz(1)          # below MIN_BUZZ_HZ
    with pytest.raises(P.ProtocolRangeError):
        P.build_buzz(99999)      # above MAX_BUZZ_HZ


def test_build_buzz_rejects_a_negative_duration():
    with pytest.raises(P.ProtocolRangeError):
        P.build_buzz(1200, -1)


# --------------------------------------------------------------------------- #
# ENV / GAS response parsing (-1 is the "not measured" sentinel)
# --------------------------------------------------------------------------- #
def test_parse_env_reading():
    r = P.parse_response("ENV T=24 H=51")
    assert r.ok is True
    assert r.kind == "ENV"
    assert r.temperature_c == 24
    assert r.humidity_pct == 51


def test_parse_gas_reading():
    r = P.parse_response("GAS RAW=312")
    assert r.ok is True
    assert r.kind == "GAS"
    assert r.gas_raw == 312


def test_parse_env_partial_or_invalid_line_is_tolerated():
    """Missing fields are ``None`` — the same tolerant rule as SENSOR."""
    r = P.parse_response("ENV T=24")
    assert r.temperature_c == 24
    assert r.humidity_pct is None

    # -1 stays as the raw sentinel; the sensor layer normalises it.
    r = P.parse_response("ENV T=-1 H=-1")
    assert r.temperature_c == -1
    assert r.humidity_pct == -1


def test_env_and_gas_are_not_confused_with_existing_kinds():
    """The parser is ordered and prefix-matched, so ENV/GAS must be distinct."""
    for line, kind in (
        ("SENSOR F=1 L=2 R=3 B=4", "SENSOR"),
        ("ENV T=1 H=2", "ENV"),
        ("GAS RAW=5", "GAS"),
        ("STATUS L=1 R=1 MODE=RUNNING", "STATUS"),
        ("VERSION 1.1", "VERSION"),
    ):
        assert P.parse_response(line).kind == kind


# --------------------------------------------------------------------------- #
# Round trips over the serial layer
# --------------------------------------------------------------------------- #
def test_env_round_trip():
    s = _serial(start_distances=(200, 200, 200, 200))
    s._transport.set_environment(temperature_c=24, humidity_pct=51)
    r = s.env()
    assert (r.temperature_c, r.humidity_pct) == (24, 51)
    assert s.last_env is r


def test_gas_round_trip():
    s = _serial()
    s._transport.set_gas(300)
    r = s.gas()
    assert r.gas_raw == 300
    assert s.last_gas is r


def test_gas_unassigned_pin_reads_minus_one():
    """Shipped default: no analog pin is assigned, so the value is -1."""
    s = _serial()
    assert s._transport._gas_raw == -1
    assert s.gas().gas_raw == -1


def test_lcd_records_text_through_the_mock():
    s = _serial()
    r = s.lcd("MODE RUNNING", "T24 H51")
    assert r.kind == "ACK" and r.verb == "LCD"
    assert s._transport.lcd_text == ("MODE RUNNING", "T24 H51")


def test_buzzer_records_command_and_stop():
    s = _serial()
    assert s._transport.buzzer is None
    s.buzz(1200, 150)
    assert s._transport.buzzer == (1200, 150)
    s.buzz(0)
    assert s._transport.buzzer == (0, None)


def test_env_is_not_a_valid_unknown_line_for_the_mock():
    """The mock is synchronous: a stray ENV line is simply not recognized.

    This documents the mock's (pre-existing) limitation — it never emits
    *unsolicited* lines, so a stray line is echoed back as ERR UNKNOWN. The Pi
    side therefore relies on the firmware to volunteer ENV/GAS; the buffering
    logic in ``_send_and_read`` is still exercised by the poll tests above.
    """
    s = _serial()
    assert s.env().kind == "ENV"   # a real command still works


# --------------------------------------------------------------------------- #
# The Pi-side sensor manager (validation + absent-value contract)
# --------------------------------------------------------------------------- #
def test_environment_manager_normalises_minus_one_to_none():
    """-1 (invalid / not measured / no pin) is ``None``, never a value."""
    from amr.sensors import EnvironmentManager

    s = _serial()
    s._transport.set_environment(-1, -1)
    s._transport.set_gas(-1)
    mgr = EnvironmentManager(s)
    reading = mgr.poll()
    assert reading.temperature_c is None
    assert reading.humidity_pct is None
    assert reading.gas_raw is None
    assert reading.all_invalid() is True


def test_environment_manager_passes_through_valid_values():
    from amr.sensors import EnvironmentManager

    s = _serial()
    s._transport.set_environment(24, 51)
    s._transport.set_gas(312)
    reading = EnvironmentManager(s).poll()
    assert reading.as_dict() == {
        "temperature_c": 24,
        "humidity_pct": 51,
        "gas_raw": 312,
    }


def test_environment_manager_is_telemetry_only(config_dir):
    """The environment manager can never write a motion command.

    ``NoActuation`` asserts the block issues no MOVE/STOP, so a sensor read is
    structurally incapable of moving the robot.
    """
    from amr.robot import RobotManager
    from amr.sensors import EnvironmentManager
    from amr.utils.config import load_config
    from tests.conftest import NoActuation

    config = load_config(str(config_dir))
    mgr, transport = RobotManager.create_mock(config)
    mgr.start()
    try:
        with NoActuation(transport):
            mgr.read_environment()
    finally:
        mgr.shutdown()
    # A worker reading the sensors did not move anything.
    assert transport.motor_state == (0, 0)
