"""Tests for the Pi-side ultrasonic manager (validation over the protocol)."""

from __future__ import annotations

from amr.communication import protocol as P
from amr.communication.arduino_serial import ArduinoSerial
from amr.mocks import MockSerialTransport
from amr.sensors import UltrasonicManager, UltrasonicReading
from amr.utils.config import SafetyConfig


def _make(distances=(80, 40, 90, 120)):
    transport = MockSerialTransport(start_distances=distances)
    serial = ArduinoSerial(transport, timeout=0.05)
    serial.connect()
    mgr = UltrasonicManager(serial, SafetyConfig())
    return transport, serial, mgr


def test_poll_returns_valid_distances():
    _, _, mgr = _make((80, 40, 90, 120))
    r = mgr.poll()
    assert (r.front, r.left, r.right, r.rear) == (80, 40, 90, 120)
    assert r.all_invalid() is False


def test_poll_validates_out_of_range_as_invalid():
    transport, _, mgr = _make((9999, 40, 90, 120))  # front above max (400)
    r = mgr.poll()
    assert r.front is None
    assert (r.left, r.right, r.rear) == (40, 90, 120)


def test_poll_validates_below_min_as_invalid():
    transport, _, mgr = _make((80, 1, 90, 120))  # left below min (2)
    r = mgr.poll()
    assert r.left is None
    assert r.front == 80


def test_poll_normalises_no_echo_as_invalid():
    transport, _, mgr = _make((-1, -1, 90, 120))  # firmware "no echo"
    r = mgr.poll()
    assert r.front is None
    assert r.left is None
    assert (r.right, r.rear) == (90, 120)


def test_latest_is_none_before_any_poll():
    _, _, mgr = _make()
    assert mgr.latest() is None


def test_latest_tracks_last_poll():
    transport, _, mgr = _make((80, 40, 90, 120))
    assert mgr.latest() is None
    transport.set_distances(33, 22, 55, 77)
    mgr.poll()
    latest = mgr.latest()
    assert (latest.front, latest.left, latest.right, latest.rear) == (33, 22, 55, 77)


def test_from_response_with_partial_fields():
    resp = P.Response(kind="SENSOR", raw="SENSOR F=10", ok=True, front=10)
    r = UltrasonicReading.from_response(resp)
    assert r.front == 10
    assert r.left is None and r.right is None and r.rear is None


def test_all_invalid_predicate():
    assert UltrasonicReading().all_invalid() is True
    assert UltrasonicReading(front=50).all_invalid() is False


def test_as_dict():
    r = UltrasonicReading(front=1, left=None, right=3, rear=4)
    assert r.as_dict() == {"front": 1, "left": None, "right": 3, "rear": 4}
