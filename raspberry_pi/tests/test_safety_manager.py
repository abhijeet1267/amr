"""Tests for the Layer-3 safety manager (deterministic rules only).

Thresholds from the default SafetyConfig:
front/rear stop = 20 cm, left/right stop = 15 cm, caution = 2x stop.
"""

from __future__ import annotations

from amr.safety import CAUTION_FACTOR, SafetyAction, SafetyManager
from amr.sensors import UltrasonicReading
from amr.utils.config import SafetyConfig


def _mgr() -> SafetyManager:
    return SafetyManager(SafetyConfig())


def _far() -> UltrasonicReading:
    return UltrasonicReading(front=100, left=100, right=100, rear=100)


# --- rule 1: comm ---------------------------------------------------------- #
def test_disconnected_stops_even_when_all_far():
    d = _mgr().check(_far(), connected=False)
    assert d.action is SafetyAction.STOP
    assert d.allowed is False
    assert "comm" in "; ".join(d.reasons)


# --- rule 2: sensor health ------------------------------------------------- #
def test_no_reading_at_all_stops():
    d = _mgr().check(None, connected=True)
    assert d.action is SafetyAction.STOP
    assert "no valid sensor data" in d.reasons


def test_all_invalid_readings_stop():
    d = _mgr().check(UltrasonicReading(), connected=True)
    assert d.action is SafetyAction.STOP


def test_single_invalid_direction_is_ignored():
    d = _mgr().check(
        UltrasonicReading(front=None, left=100, right=100, rear=100),
        connected=True,
    )
    assert d.action is SafetyAction.PROCEED
    assert d.allowed is True


# --- rule 3: stop thresholds ----------------------------------------------- #
def _front(v):
    return UltrasonicReading(front=v, left=100, right=100, rear=100)


def test_front_below_stop_distance():
    d = _mgr().check(_front(19), connected=True)
    assert d.action is SafetyAction.STOP
    assert any("front" in r for r in d.reasons)


def test_rear_below_stop_distance():
    d = _mgr().check(
        UltrasonicReading(front=100, left=100, right=100, rear=19),
        connected=True,
    )
    assert d.action is SafetyAction.STOP


def test_left_below_stop_distance():
    d = _mgr().check(
        UltrasonicReading(front=100, left=14, right=100, rear=100),
        connected=True,
    )
    assert d.action is SafetyAction.STOP


def test_right_at_stop_distance_is_not_a_stop_but_caution():
    # docs: stop only when *closer than* the threshold
    d = _mgr().check(
        UltrasonicReading(front=100, left=100, right=15, rear=100),
        connected=True,
    )
    assert d.action is SafetyAction.WAIT


def test_worst_outcome_wins():
    # rear in the stop zone, front in the caution zone -> STOP
    d = _mgr().check(
        UltrasonicReading(front=30, left=100, right=100, rear=10),
        connected=True,
    )
    assert d.action is SafetyAction.STOP


# --- rule 4: caution zone --------------------------------------------------- #
def test_caution_zone_waits_but_reasons_given():
    d = _mgr().check(_front(35), connected=True)
    assert d.action is SafetyAction.WAIT
    assert d.caution is True
    assert d.allowed is False
    assert len(d.reasons) == 1


def test_caution_factor_is_documented_default():
    assert CAUTION_FACTOR == 2.0


# --- rule 5: proceed -------------------------------------------------------- #
def test_all_far_proceeds():
    d = _mgr().check(_far(), connected=True)
    assert d.action is SafetyAction.PROCEED
    assert d.allowed is True
    assert d.reasons == ()


def test_can_move_predicate():
    mgr = _mgr()
    assert mgr.can_move(_far(), connected=True) is True
    assert mgr.can_move(_front(10), connected=True) is False
    assert mgr.can_move(_far(), connected=False) is False


def test_decision_str_includes_reasons():
    d = _mgr().check(_front(10), connected=True)
    s = str(d)
    assert s.startswith("STOP")
    assert "front" in s
