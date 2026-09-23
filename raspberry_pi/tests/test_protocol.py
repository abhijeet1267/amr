"""Tests for the serial protocol logic and the command API over a mock link.

These tests run with NO hardware: the mock transport emulates the Arduino.
"""

from __future__ import annotations

import pytest

from amr.communication import (
    ArduinoSerial,
    MIN_SPEED,
    MAX_SPEED,
    ProtocolParseError,
    ProtocolRangeError,
    SerialTimeout,
    build_move,
    build_ping,
    build_sensor,
    build_status,
    build_stop,
    build_version,
    legacy_command,
    parse_response,
)
from amr.communication.protocol import LEGACY_PRESETS, PROTOCOL_VERSION
from amr.mocks.mock_serial import MockSerialTransport


# --------------------------------------------------------------------------- #
# Command building
# --------------------------------------------------------------------------- #
def test_build_move_forward():
    assert build_move(1, 1) == "MOVE L=1 R=1"


def test_build_move_reverse():
    assert build_move(-1, -1) == "MOVE L=-1 R=-1"


def test_build_move_turn_left():
    assert build_move(-1, 1) == "MOVE L=-1 R=1"


def test_build_move_speeds():
    assert build_move(150, 150) == "MOVE L=150 R=150"


def test_build_move_range_bounds_ok():
    assert build_move(MIN_SPEED, MAX_SPEED) == "MOVE L=-255 R=255"


@pytest.mark.parametrize("left,right", [(256, 0), (0, -256), (1000, 1), (-300, -300)])
def test_build_move_out_of_range_raises(left, right):
    with pytest.raises(ProtocolRangeError):
        build_move(left, right)


def test_simple_command_builders():
    assert build_stop() == "STOP"
    assert build_ping() == "PING"
    assert build_status() == "STATUS"
    assert build_version() == "VERSION"
    assert build_sensor() == "SENSOR"


def test_legacy_command_valid():
    assert legacy_command("f") == "F"
    assert legacy_command("s") == "S"


def test_legacy_command_invalid():
    with pytest.raises(ProtocolParseError):
        legacy_command("X")
    with pytest.raises(ProtocolParseError):
        legacy_command("")


def test_legacy_presets_covers_baseline():
    assert set(LEGACY_PRESETS.keys()) == {"F", "B", "L", "R", "S"}
    assert LEGACY_PRESETS["S"] == (0, 0)
    assert LEGACY_PRESETS["F"] == (1, 1)
    assert LEGACY_PRESETS["B"] == (-1, -1)


# --------------------------------------------------------------------------- #
# Response parsing
# --------------------------------------------------------------------------- #
def test_parse_pong():
    r = parse_response("PONG")
    assert r.kind == "PONG" and r.ok and r.is_pong()


def test_parse_ack_move():
    r = parse_response("ACK MOVE L=1 R=1")
    assert r.kind == "ACK" and r.ok and r.verb == "MOVE"


def test_parse_ack_stop():
    r = parse_response("ACK STOP")
    assert r.kind == "ACK" and r.verb == "STOP"


def test_parse_err_range():
    r = parse_response("ERR RANGE out of range")
    assert r.kind == "ERR" and not r.ok and r.code == "RANGE"
    assert "out of range" in (r.message or "")


def test_parse_err_unknown_code_only():
    r = parse_response("ERR PARSE")
    assert r.kind == "ERR" and r.code == "PARSE"


def test_parse_status():
    r = parse_response("STATUS L=1 R=1 MODE=MANUAL")
    assert r.kind == "STATUS" and r.ok
    assert r.left == 1 and r.right == 1 and r.mode == "MANUAL"


def test_parse_sensor():
    r = parse_response("SENSOR F=82 L=45 R=91 B=120")
    assert r.kind == "SENSOR" and r.ok
    assert r.front == 82 and r.left == 45 and r.right == 91 and r.rear == 120


def test_parse_version():
    r = parse_response("VERSION 1.0")
    assert r.kind == "VERSION" and r.version == "1.0"


def test_parse_watchdog():
    r = parse_response("WATCHDOG TRIGGERED")
    assert r.kind == "WATCHDOG" and not r.ok


def test_parse_unknown():
    r = parse_response("garbage nonsense")
    assert r.kind == "UNKNOWN" and not r.ok


def test_parse_empty():
    assert parse_response("   ").kind == "EMPTY"


def test_parse_negative_speeds():
    r = parse_response("STATUS L=-150 R=150 MODE=AUTONOMOUS")
    assert r.left == -150 and r.right == 150 and r.mode == "AUTONOMOUS"


# --------------------------------------------------------------------------- #
# Command API over the mock transport (round trip)
# --------------------------------------------------------------------------- #
def _serial(drop_after=None, distances=(80, 40, 90, 120)):
    t = MockSerialTransport(start_distances=distances, drop_after=drop_after)
    s = ArduinoSerial(t, timeout=0.5)
    s.connect()
    return s, t


def test_ping_returns_true():
    s, _ = _serial()
    assert s.ping() is True
    assert "PING" in s._transport.written


def test_move_round_trip_updates_state():
    s, t = _serial()
    resp = s.move(150, 150)
    assert resp.is_ack() and resp.verb == "MOVE"
    assert t.motor_state == (150, 150)


def test_stop_zeroes_motors():
    s, t = _serial()
    s.move(120, 120)
    assert s.stop().is_ack()
    assert t.motor_state == (0, 0)


def test_status_reflects_mode():
    s, t = _serial()
    t.set_mode("MANUAL")
    r = s.status()
    assert r.kind == "STATUS" and r.mode == "MANUAL"


def test_sensor_poll_returns_distances():
    s, _ = _serial(distances=(11, 22, 33, 44))
    r = s.sensor()
    assert r.kind == "SENSOR"
    assert (r.front, r.left, r.right, r.rear) == (11, 22, 33, 44)


def test_version_matches_protocol():
    s, _ = _serial()
    r = s.version()
    assert r.kind == "VERSION" and r.version == PROTOCOL_VERSION


def test_legacy_command_moves_motors():
    s, t = _serial()
    r = s.legacy("F")
    assert r.is_ack() and t.motor_state == (1, 1)
    s.legacy("S")
    assert t.motor_state == (0, 0)


# --------------------------------------------------------------------------- #
# Failure handling
# --------------------------------------------------------------------------- #
def test_move_rejects_out_of_range_before_sending():
    s, t = _serial()
    with pytest.raises(ProtocolRangeError):
        s.move(500, 0)
    # Nothing should have been sent as a MOVE.
    assert not any(w.startswith("MOVE") for w in t.written)


def test_timeout_when_controller_stops_answering():
    # drop_after=1 -> the first command still answers, then the mock goes
    # silent to emulate a crashed / disconnected controller.
    s, _ = _serial(drop_after=1)
    assert s.ping() is True  # first command still answers
    with pytest.raises(SerialTimeout):
        s.move(1, 1)  # now the controller is "dead"


def test_arduino_side_range_error_reported():
    # Bypass Pi-side validation by writing an out-of-range MOVE directly, to
    # confirm the controller (mock) reports ERR RANGE.
    t = MockSerialTransport()
    t.open()
    t.write("MOVE L=999 R=0")
    r = parse_response(t.read_line(0.1))
    assert r.kind == "ERR" and r.code == "RANGE"


def test_requires_connection():
    s, _ = _serial()
    s.disconnect()
    with pytest.raises(ConnectionError):
        s.stop()


def test_ping_false_when_not_connected():
    t = MockSerialTransport()
    s = ArduinoSerial(t, timeout=0.2)
    # Not opened -> ping must safely return False, not raise.
    assert s.ping() is False
