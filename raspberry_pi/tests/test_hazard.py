"""Tests for the context-aware multi-hazard safety layer (``amr.hazard``).

Covers, with no ROS and no hardware:

* :mod:`amr.hazard.types` — severity/state ordering, tolerant parsing,
  ``HazardLocation`` duck typing, reading/event/status value objects.
* :mod:`amr.hazard.event_log` — bounded ring behaviour, record/escalate/resolve,
  JSONL export and the tolerant :func:`read_events` reader.
* :mod:`amr.hazard.sources` — threshold mapping, every source's fail-safe
  behaviour on missing data and on a raising callback, and the zone maths.
* :class:`~amr.hazard.manager.HazardManager` — the deterministic
  NORMAL/WARNING/SLOW/STOP/EMERGENCY decision, latching + operator acknowledge,
  event de-duplication/escalation, and the JSON snapshot.
* The integration seam: :meth:`RobotManager.attach_hazard` — proving the hazard
  layer can only *escalate* the existing gated stack (vetoes motion, forces
  ``SAFETY_STOP``, caps speed) and that behaviour is byte-identical when no
  hazard layer is attached.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from amr.hazard import (
    GasSensorSource,
    HazardEvent,
    HazardEventLog,
    HazardKind,
    HazardLocation,
    HazardManager,
    HazardReading,
    HazardSeverity,
    HazardState,
    HazardStatus,
    HazardZone,
    RestrictedZoneSource,
    RobotStateSource,
    VisionHazardSource,
    read_events,
    severity_for,
    zones_from_config,
)
from amr.robot import RobotCommandError, RobotManager, RobotMode
from amr.safety import SafetyAction
from amr.utils.config import HazardConfig, load_config


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
class FixedSource:
    """A source that returns whatever readings it is currently told to."""

    def __init__(self, readings=(), name: str = "fixed"):
        self.name = name
        self._readings = tuple(readings)

    def set(self, readings) -> None:
        self._readings = tuple(readings)

    def read(self):
        return self._readings


class BoomSource:
    """A source whose ``read()`` always raises (the fail-safe path)."""

    name = "boom"

    def read(self):
        raise RuntimeError("sensor bus dropped")


class MutablePose:
    """A mutable pose-like object (``HazardLocation.from_any`` duck-typing)."""

    def __init__(self, x: float = 0.0, y: float = 0.0, theta: float = 0.0):
        self.x, self.y, self.theta = x, y, theta


class FakeState:
    """Stand-in for ``RobotState`` without importing it."""

    def __init__(self, connected: bool = True, last_error=None):
        self.connected = connected
        self.last_error = last_error


class FakeNav:
    """Stand-in for ``NavResult`` without importing it."""

    def __init__(self, status, error=None):
        self.status = status
        self.error = error


def reading(kind=HazardKind.GAS, severity=HazardSeverity.WARNING, **kw) -> HazardReading:
    return HazardReading(kind=kind, severity=severity, **kw)


@pytest.fixture
def hazard_config() -> HazardConfig:
    """A hazard config with the layer switched on."""
    return HazardConfig(enabled=True)


@pytest.fixture
def manager(hazard_config) -> HazardManager:
    return HazardManager(hazard_config, sources=[FixedSource(name="fixed")])


# --------------------------------------------------------------------------- #
# types
# --------------------------------------------------------------------------- #
def test_severity_and_state_ranking_is_ordered():
    assert HazardSeverity.INFO.rank < HazardSeverity.WARNING.rank
    assert HazardSeverity.WARNING.rank < HazardSeverity.CRITICAL.rank
    ranks = [s.rank for s in (
        HazardState.NORMAL, HazardState.WARNING, HazardState.SLOW,
        HazardState.STOP, HazardState.EMERGENCY,
    )]
    assert ranks == sorted(ranks)


def test_worst_wins_and_motion_predicates():
    assert HazardState.WARNING.worst(HazardState.STOP) is HazardState.STOP
    assert HazardState.EMERGENCY.worst(HazardState.SLOW) is HazardState.EMERGENCY
    assert HazardState.NORMAL.blocks_motion is False
    assert HazardState.WARNING.blocks_motion is False
    assert HazardState.SLOW.blocks_motion is False
    assert HazardState.STOP.blocks_motion is True
    assert HazardState.EMERGENCY.blocks_motion is True
    assert HazardState.EMERGENCY.latches is True
    assert HazardState.STOP.latches is False


def test_parse_is_tolerant_and_fails_safe():
    assert HazardKind.parse("gas") is HazardKind.GAS
    assert HazardKind.parse(HazardKind.FIRE) is HazardKind.FIRE
    assert HazardKind.parse(None) is HazardKind.UNKNOWN
    assert HazardKind.parse("radon") is HazardKind.UNKNOWN
    # Unknown severity must NOT silently downgrade to INFO.
    assert HazardSeverity.parse("weird") is HazardSeverity.WARNING
    # Unknown state must not block the robot by itself.
    assert HazardState.parse("weird") is HazardState.NORMAL


def test_location_from_any_accepts_poses_sequences_and_none():
    class PoseLike:
        x, y, theta = 1.5, -2.0, 0.25

    loc = HazardLocation.from_any(PoseLike())
    assert (loc.x, loc.y, loc.theta) == (1.5, -2.0, 0.25)
    assert HazardLocation.from_any((3, 4)).theta == 0.0
    assert HazardLocation.from_any((3, 4, 1.0)).theta == 1.0
    assert HazardLocation.from_any(None) is None


def test_reading_describe_and_key():
    r = HazardReading(kind=HazardKind.GAS, value=1200, unit="ppm", source="mq2")
    assert "1200ppm" in r.describe()
    assert r.key == "GAS:mq2"
    assert r.is_critical is False
    r2 = HazardReading(kind=HazardKind.FIRE, source="mq2", message="flame seen")
    assert r2.describe() == "flame seen"


def test_event_resolution_and_escalation_preserve_identity():
    event = HazardEvent(
        event_id="hzd-0001",
        kind=HazardKind.GAS,
        severity=HazardSeverity.WARNING,
        state=HazardState.SLOW,
        message="gas 400ppm",
        raised_at=100.0,
    )
    assert event.resolved is False
    assert event.duration_s is None

    escalated = event.escalated_with(
        HazardSeverity.CRITICAL, HazardState.STOP, "gas 2000ppm"
    )
    assert escalated.event_id == event.event_id
    assert escalated.raised_at == event.raised_at      # identity preserved
    assert escalated.severity is HazardSeverity.CRITICAL
    assert escalated.message == "gas 2000ppm"

    cleared = escalated.resolved_with(cleared_at=130.0)
    assert cleared.resolved is True
    assert cleared.duration_s == pytest.approx(30.0)
    assert cleared.to_dict()["resolved"] is True


def test_status_predicates_and_serialisation():
    normal = HazardStatus()
    assert normal.allowed is True
    assert normal.blocks_motion is False
    assert normal.speed_scale == 1.0

    slow = HazardStatus(
        state=HazardState.SLOW,
        reasons=("gas 400ppm",),
        speed_scale=0.5,
        location=HazardLocation(x=1.0, y=2.0),
    )
    assert slow.caution is True
    assert slow.allowed is True
    assert str(slow) == "SLOW (gas 400ppm)"
    payload = slow.to_dict()
    assert payload["state"] == "SLOW"
    assert payload["location"]["x"] == 1.0
    assert json.dumps(payload)  # must be JSON-serialisable

    stop = HazardStatus(state=HazardState.STOP, speed_scale=0.0)
    assert stop.allowed is False
    assert stop.blocks_motion is True
    assert stop.worst(HazardState.EMERGENCY) is HazardState.EMERGENCY


# --------------------------------------------------------------------------- #
# event_log
# --------------------------------------------------------------------------- #
def _event(i: int, kind=HazardKind.GAS, severity=HazardSeverity.WARNING):
    return HazardEvent(
        event_id=f"hzd-{i:04d}",
        kind=kind,
        severity=severity,
        state=HazardState.SLOW,
        message=f"event {i}",
        raised_at=float(i),
        source="test",
    )


def test_log_is_bounded_and_keeps_the_newest():
    log = HazardEventLog(capacity=3)
    for i in range(1, 6):
        log.record(_event(i))
    ids = [e.event_id for e in log.history()]
    assert ids == ["hzd-0003", "hzd-0004", "hzd-0005"]
    assert len(log) == 3


def test_log_capacity_must_be_positive():
    with pytest.raises(ValueError):
        HazardEventLog(capacity=0)


def test_log_active_replace_resolve_and_counts():
    log = HazardEventLog(capacity=8)
    log.record(_event(1))
    log.record(_event(2, kind=HazardKind.FIRE, severity=HazardSeverity.CRITICAL))

    assert len(log.active()) == 2
    assert log.counts_by_kind() == {"GAS": 1, "FIRE": 1}

    # Escalating an existing event replaces it in place (same id, same slot).
    escalated = log.active()[0].escalated_with(
        HazardSeverity.CRITICAL, HazardState.STOP, "worse"
    )
    assert log.replace(escalated) is True
    assert log.history()[0].message == "worse"

    assert log.replace(_event(99)) is False       # unknown id
    assert log.resolve("hzd-0001") is True
    assert log.resolve("hzd-9999") is False
    assert len(log.active()) == 1
    assert log.resolve_all() == 1
    assert log.active() == ()
    assert log.resolve_all() == 0                 # idempotent

    assert len(log.recent(1)) == 1
    assert log.recent(0) == ()
    assert len(log.recent(99)) == len(log)
    log.clear()
    assert len(log) == 0


def test_log_exports_jsonl_and_reads_it_back(tmp_path):
    path = tmp_path / "nested" / "hazards.jsonl"
    log = HazardEventLog(capacity=4, path=str(path))
    assert log.path == str(path)
    log.record(_event(1))
    log.record(_event(2, kind=HazardKind.HUMAN))

    rows = read_events(str(path))
    assert len(rows) == 2
    assert rows[0]["event_id"] == "hzd-0001"
    assert rows[1]["kind"] == "HUMAN"
    assert rows[0]["resolved"] is False


def test_read_events_tolerates_missing_and_malformed_input(tmp_path):
    assert read_events(str(tmp_path / "absent.jsonl")) == ()

    dirty = tmp_path / "dirty.jsonl"
    dirty.write_text(
        '{"event_id": "a"}\nnot json at all\n\n{"event_id": "b"}\n[1,2,3]\n',
        encoding="utf-8",
    )
    rows = read_events(str(dirty))
    assert [r["event_id"] for r in rows] == ["a", "b"]


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #
def test_severity_for_thresholds_and_disabled_critical():
    assert severity_for(10, 100, 200) is HazardSeverity.INFO
    assert severity_for(100, 100, 200) is HazardSeverity.WARNING
    assert severity_for(200, 100, 200) is HazardSeverity.CRITICAL
    # critical_at = 0 disables the critical band (warn-only source).
    assert severity_for(9999, 100, 0) is HazardSeverity.WARNING


def test_gas_source_thresholds_and_silence_below_warn():
    holder = {"v": 0.0}
    src = GasSensorSource(
        lambda: holder["v"], name="mq2", warn_at=300, critical_at=1000
    )
    assert src.read() == ()                       # clean air says nothing

    holder["v"] = 500.0
    (warned,) = src.read()
    assert warned.kind is HazardKind.GAS
    assert warned.severity is HazardSeverity.WARNING
    assert "500ppm" in warned.message

    holder["v"] = 1500.0
    (critical,) = src.read()
    assert critical.severity is HazardSeverity.CRITICAL
    assert "critical" in critical.message


def test_gas_source_missing_data_and_crashing_reader_fail_safe():
    (missing,) = GasSensorSource(lambda: None, name="mq2").read()
    assert missing.kind is HazardKind.GAS
    assert missing.severity is HazardSeverity.WARNING
    # Opting out of the missing-data warning must be explicit, not accidental.
    assert GasSensorSource(lambda: None, missing_is_warning=False).read() == ()

    (fault,) = GasSensorSource(BoomSource().read, name="mq2").read()
    assert fault.kind is HazardKind.ROBOT_FAULT
    assert "failed" in fault.message


def test_vision_source_maps_detections_and_restamps_source():
    detections = [(HazardKind.FIRE, 0.9), (HazardKind.HUMAN, 0.2)]
    src = VisionHazardSource(
        lambda: detections, name="cam", warn_at=0.5, critical_at=0.8
    )
    readings = src.read()
    assert len(readings) == 1                     # 0.2 confidence is INFO -> silent
    assert readings[0].kind is HazardKind.FIRE
    assert readings[0].severity is HazardSeverity.CRITICAL
    assert readings[0].source == "cam"
    assert readings[0].unit == "confidence"
    assert "0.90" in readings[0].message

    (passthrough,) = VisionHazardSource(
        lambda: [HazardReading(kind=HazardKind.SMOKE)]
    ).read()
    assert passthrough.source == "vision"         # re-stamped from "unknown"
    assert passthrough.kind is HazardKind.SMOKE


def test_vision_source_handles_empty_and_crashing_detector():
    assert VisionHazardSource(lambda: None).read() == ()
    assert VisionHazardSource(lambda: []).read() == ()
    assert VisionHazardSource(lambda: ["nonsense", (HazardKind.FIRE,)]).read() == ()

    (fault,) = VisionHazardSource(BoomSource().read, name="cam").read()
    assert fault.kind is HazardKind.ROBOT_FAULT
    assert "detector failed" in fault.message


def test_robot_state_source_reports_link_loss_and_errors():
    (lost,) = RobotStateSource(lambda: FakeState(connected=False)).read()
    assert lost.kind is HazardKind.ROBOT_FAULT
    assert lost.severity is HazardSeverity.CRITICAL

    (errored,) = RobotStateSource(lambda: FakeState(last_error="motor fault")).read()
    assert errored.severity is HazardSeverity.WARNING
    assert "motor fault" in errored.message

    healthy = RobotStateSource(lambda: FakeState(), lambda: FakeNav("DONE"))
    assert healthy.read() == ()


def test_robot_state_source_reports_navigation_failure_and_crashes():
    failed = RobotStateSource(lambda: FakeState(), lambda: FakeNav("FAILED", "no path"))
    (nav,) = failed.read()
    assert "navigation failed" in nav.message
    assert "no path" in nav.message

    (state_down,) = RobotStateSource(BoomSource().read).read()
    assert "unavailable" in state_down.message

    nav_down = RobotStateSource(lambda: FakeState(), BoomSource().read)
    assert "nav unavailable" in nav_down.read()[0].message


def test_robot_state_source_accepts_enum_like_status():
    class Status:
        value = "CANCELLED"

    src = RobotStateSource(lambda: FakeState(), lambda: FakeNav(Status()))
    (nav,) = src.read()
    assert "cancelled" in nav.message


def test_zone_contains_normalises_swapped_bounds():
    zone = HazardZone(name="bay", x_min=2.0, x_max=1.0, y_min=1.0, y_max=0.0)
    assert (zone.x_min, zone.x_max) == (1.0, 2.0)
    assert (zone.y_min, zone.y_max) == (0.0, 1.0)
    assert zone.contains((1.5, 0.5)) is True
    assert zone.contains(MutablePose(x=1.5, y=0.5)) is True
    assert zone.contains((2.5, 0.5)) is False
    assert zone.contains(None) is False
    assert zone.to_dict()["name"] == "bay"


def test_zone_from_dict_requires_a_name():
    zone = HazardZone.from_dict(
        {"name": "aisle", "x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1,
         "severity": "warning"}
    )
    assert zone.severity is HazardSeverity.WARNING
    with pytest.raises(ValueError):
        HazardZone.from_dict({"x_min": 0})


def test_restricted_zone_source_uses_the_pose_provider():
    zone = HazardZone(name="bay", x_min=3.5, x_max=4.5, y_min=1.0, y_max=2.0)
    assert RestrictedZoneSource([zone]).read() == ()      # no provider -> silent

    (breach,) = RestrictedZoneSource([zone], pose_provider=lambda: (4.0, 1.5)).read()
    assert breach.kind is HazardKind.ZONE_BREACH
    assert breach.severity is HazardSeverity.CRITICAL
    assert "'bay'" in breach.message

    outside = RestrictedZoneSource([zone], pose_provider=lambda: (0.0, 0.0))
    assert outside.read() == ()

    no_pose = RestrictedZoneSource([zone], pose_provider=lambda: None)
    assert no_pose.read() == ()

    broken = RestrictedZoneSource([zone], pose_provider=BoomSource().read)
    assert "pose unavailable" in broken.read()[0].message


def test_zones_from_config_skips_invalid_entries():
    cfg = HazardConfig(
        zones=[
            {"name": "a"},
            {"no_name": True},        # invalid -> skipped
            HazardZone(name="b"),
            "junk",                   # invalid -> skipped
        ]
    )
    assert [z.name for z in zones_from_config(cfg)] == ["a", "b"]
    assert zones_from_config(HazardConfig()) == ()


# --------------------------------------------------------------------------- #
# manager
# --------------------------------------------------------------------------- #
def test_manager_is_normal_before_and_without_sources(hazard_config):
    empty = HazardManager(hazard_config)
    assert empty.state is HazardState.NORMAL      # sane default before any poll
    assert empty.speed_scale == 1.0
    assert empty.active_events() == ()

    status = empty.evaluate()
    assert status.state is HazardState.NORMAL
    assert status.allowed is True
    assert status.reasons == ()
    assert status.readings == ()


def test_gas_warning_slows_and_records_exactly_one_event(manager):
    src = FixedSource(name="mq2")
    manager.add_source(src)
    src.set([reading(HazardKind.GAS, source="mq2", message="gas 500ppm")])

    status = manager.evaluate()
    assert status.state is HazardState.SLOW
    assert status.speed_scale == 0.5
    assert manager.speed_scale == 0.5

    # Polling again must not create a second event for the same hazard.
    manager.evaluate()
    assert len(manager.events) == 1
    assert len(manager.active_events()) == 1


def test_warning_of_a_non_slow_kind_only_warns(manager):
    manager.add_source(
        FixedSource(
            [reading(HazardKind.TEMPERATURE, source="tmp")], name="tmp"
        )
    )
    status = manager.evaluate()
    assert status.state is HazardState.WARNING
    assert status.speed_scale == 1.0
    assert status.allowed is True


def test_critical_non_emergency_kind_stops_without_latching(manager):
    manager.add_source(
        FixedSource(
            [reading(HazardKind.ROBOT_FAULT, HazardSeverity.CRITICAL, source="rs")],
            name="rs",
        )
    )
    status = manager.evaluate()
    assert status.state is HazardState.STOP
    assert status.blocks_motion is True
    assert status.speed_scale == 0.0
    assert manager.latched is False


def test_critical_life_safety_kind_latches_until_acknowledged(manager):
    src = FixedSource(
        [reading(HazardKind.FIRE, HazardSeverity.CRITICAL, message="flame")],
        name="cam",
    )
    manager.add_source(src)

    status = manager.evaluate()
    assert status.state is HazardState.EMERGENCY
    assert status.latched is True
    assert status.speed_scale == 0.0

    # The reading clears, but the latch holds until an operator acknowledges.
    src.set([])
    held = manager.evaluate()
    assert held.state is HazardState.EMERGENCY
    assert held.latched is True
    assert any("acknowledgement" in r for r in held.reasons)

    acked = manager.acknowledge()
    assert acked.state is HazardState.NORMAL
    assert acked.latched is False
    assert manager.latched is False


def test_acknowledge_re_latches_while_the_hazard_remains(manager):
    src = FixedSource(
        [reading(HazardKind.FIRE, HazardSeverity.CRITICAL)], name="cam"
    )
    manager.add_source(src)
    manager.evaluate()
    manager.acknowledge()
    # The hazard is still present, so the next evaluation latches again.
    assert manager.evaluate().state is HazardState.EMERGENCY
    assert manager.latched is True


def test_acknowledge_is_a_noop_when_nothing_is_latched(hazard_config):
    quiet = HazardManager(hazard_config)
    assert quiet.acknowledge().state is HazardState.NORMAL
    assert quiet.latched is False


def test_worst_reading_wins(hazard_config):
    src = FixedSource(name="multi")
    mgr = HazardManager(hazard_config, sources=[src])

    src.set([
        reading(HazardKind.GAS, source="multi"),
        reading(HazardKind.ROBOT_FAULT, HazardSeverity.CRITICAL, source="multi"),
    ])
    assert mgr.evaluate().state is HazardState.STOP        # STOP outranks SLOW

    src.set([reading(HazardKind.GAS, source="multi")])
    assert mgr.evaluate().state is HazardState.SLOW


def test_events_escalate_in_place_and_resolve_when_cleared(manager):
    src = FixedSource(name="mq2")
    manager.add_source(src)

    src.set([reading(HazardKind.GAS, source="mq2")])
    manager.evaluate()
    first = manager.active_events()[0]
    assert first.severity is HazardSeverity.WARNING

    src.set([reading(HazardKind.GAS, HazardSeverity.CRITICAL, source="mq2")])
    manager.evaluate()
    active = manager.active_events()
    assert len(active) == 1                       # one hazard, not two events
    assert active[0].event_id == first.event_id   # same identity
    assert active[0].severity is HazardSeverity.CRITICAL
    assert len(manager.events) == 1               # replaced, not appended

    src.set([])
    manager.evaluate()
    assert manager.active_events() == ()
    recorded = manager.events.history()[0]
    assert recorded.resolved is True
    assert recorded.duration_s is not None


def test_source_crash_becomes_a_fail_safe_warning(hazard_config):
    mgr = HazardManager(hazard_config, sources=[BoomSource()])
    status = mgr.evaluate()
    assert status.state is HazardState.WARNING            # never silent
    assert status.readings[0].kind is HazardKind.ROBOT_FAULT
    assert "failed" in status.readings[0].message
    assert len(mgr.active_events()) == 1


def test_events_are_location_tagged_and_exported(tmp_path, hazard_config):
    path = tmp_path / "events.jsonl"
    cfg = dataclasses.replace(hazard_config, event_log_path=str(path))
    src = FixedSource([reading(HazardKind.HUMAN, source="cam")], name="cam")
    mgr = HazardManager(cfg, sources=[src])

    status = mgr.evaluate(location=(1.25, -0.5))
    assert status.location.x == 1.25
    assert mgr.active_events()[0].location.y == -0.5

    rows = read_events(str(path))
    assert len(rows) == 1
    assert rows[0]["location"] == {"x": 1.25, "y": -0.5, "theta": 0.0, "zone": None}
    assert rows[0]["kind"] == "HUMAN"

    # The location is remembered for later evaluations.
    assert mgr.evaluate().location.x == 1.25


def test_snapshot_is_json_safe_and_reports_state(manager):
    manager.add_source(FixedSource([reading(HazardKind.GAS, source="mq2")], name="mq2"))
    manager.evaluate()
    snap = manager.snapshot()
    assert snap["state"] == "SLOW"
    assert snap["speed_scale"] == 0.5
    assert snap["enabled"] is True
    assert snap["status"] == "NOT_VERIFIED"
    assert snap["blocks_motion"] is False
    assert "mq2" in snap["sources"]
    assert snap["events_recorded"] == 1
    assert snap["counts_by_kind"] == {"GAS": 1}
    assert len(snap["active_events"]) == 1
    json.dumps(snap)                              # the web layer must be able to


def test_from_config_wires_the_zone_source(hazard_config):
    cfg = dataclasses.replace(
        hazard_config,
        zones=[
            {"name": "bay", "x_min": 3.0, "x_max": 4.0, "y_min": 0.0,
             "y_max": 1.0, "severity": "CRITICAL"},
        ],
    )
    pose = MutablePose(x=0.0, y=0.0)
    mgr = HazardManager.from_config(cfg, pose_provider=lambda: pose)
    assert [getattr(s, "name") for s in mgr.sources] == ["zones"]
    assert mgr.evaluate().state is HazardState.NORMAL

    pose.x = 3.5                                  # robot drives into the bay
    assert mgr.evaluate().state is HazardState.STOP
    assert mgr.active_events()[0].kind is HazardKind.ZONE_BREACH

    pose.x = 0.0
    assert mgr.evaluate().state is HazardState.NORMAL


def test_from_config_without_zones_adds_no_source(hazard_config):
    mgr = HazardManager.from_config(hazard_config)
    assert mgr.sources == ()
    assert mgr.evaluate().state is HazardState.NORMAL


def test_extra_readings_are_merged_and_can_escalate(manager):
    status = manager.evaluate(
        extra=[reading(HazardKind.ZONE_BREACH, HazardSeverity.CRITICAL)]
    )
    assert status.state is HazardState.STOP        # ZONE_BREACH is not an emergency kind
    assert manager.active_events()[0].kind is HazardKind.ZONE_BREACH


def test_reset_clears_latch_and_events(manager):
    manager.add_source(
        FixedSource([reading(HazardKind.FIRE, HazardSeverity.CRITICAL)], name="cam")
    )
    manager.evaluate()
    assert manager.latched is True

    manager.reset()
    assert manager.latched is False
    assert len(manager.events) == 0
    assert manager.state is HazardState.NORMAL


def test_explicit_empty_emergency_kinds_disables_latching(hazard_config):
    src = FixedSource([reading(HazardKind.FIRE, HazardSeverity.CRITICAL)])
    mgr = HazardManager(
        dataclasses.replace(hazard_config, emergency_kinds=[]), sources=[src]
    )
    assert mgr.emergency_kinds == ()
    status = mgr.evaluate()
    assert status.state is HazardState.STOP        # STOP, not EMERGENCY
    assert mgr.latched is False


# --------------------------------------------------------------------------- #
# Integration: RobotManager (additive, opt-in — must not change existing paths)
# --------------------------------------------------------------------------- #
@pytest.fixture
def app_config(config_dir):
    return load_config(config_dir)


@pytest.fixture
def robot(app_config):
    mgr, transport = RobotManager.create_mock(app_config)
    mgr.start()
    return mgr, transport


def test_robot_behaviour_is_unchanged_with_no_hazard_layer(robot):
    mgr, _ = robot
    assert mgr.hazard is None
    assert mgr.hazard_snapshot() is None
    assert "hazard" not in mgr.snapshot()          # additive key stays absent
    assert mgr._scaled(123) == 123                 # speed scaling is identity


def test_hazard_slow_caps_the_commanded_speed(robot, hazard_config):
    mgr, transport = robot
    transport.set_distances(200, 200, 200, 200)
    src = FixedSource([reading(HazardKind.GAS, source="mq2")], name="mq2")
    mgr.attach_hazard(HazardManager(hazard_config, sources=[src]))
    mgr.request_mode(RobotMode.MANUAL)

    mgr.tick()
    assert mgr.hazard.state is HazardState.SLOW
    assert mgr.snapshot()["hazard"]["state"] == "SLOW"

    mgr.forward(100)
    assert mgr.drive.last_commanded == (50, 50)     # 0.5 x commanded


def test_hazard_emergency_vetoes_motion_and_forces_safety_stop(robot, hazard_config):
    mgr, transport = robot
    transport.set_distances(200, 200, 200, 200)
    src = FixedSource(
        [reading(HazardKind.FIRE, HazardSeverity.CRITICAL, message="flame")], name="cam"
    )
    mgr.attach_hazard(HazardManager(hazard_config, sources=[src]))
    mgr.request_mode(RobotMode.MANUAL)

    mgr.tick()
    assert mgr.hazard.state is HazardState.EMERGENCY
    assert mgr.state.mode is RobotMode.SAFETY_STOP
    assert (mgr.state.left_speed, mgr.state.right_speed) == (0, 0)

    # Motion is refused. The mode gate is the first line of defence, so that is
    # the error surfaced here; the hazard veto itself is covered below.
    with pytest.raises(RobotCommandError):
        mgr.forward(100)
    assert mgr.state.mode is RobotMode.SAFETY_STOP


def test_hazard_stop_vetoes_motion_at_the_gate(robot, hazard_config):
    """The hazard layer vetoes motion on its own, without a control-loop tick."""
    mgr, transport = robot
    transport.set_distances(200, 200, 200, 200)
    src = FixedSource(
        [reading(HazardKind.ZONE_BREACH, HazardSeverity.CRITICAL)], name="zones"
    )
    haz = HazardManager(hazard_config, sources=[src])
    mgr.attach_hazard(haz)
    mgr.request_mode(RobotMode.MANUAL)

    haz.evaluate()                                  # STOP, but no tick() yet
    assert mgr.state.mode is RobotMode.MANUAL       # mode still allows motion

    with pytest.raises(RobotCommandError) as excinfo:
        mgr.forward(100)
    assert "hazard veto" in str(excinfo.value)


def test_hazard_never_relaxes_the_layer3_proximity_gate(robot, hazard_config):
    """A hazard 'NORMAL' verdict must not clear a deterministic proximity STOP."""
    mgr, transport = robot
    transport.set_distances(5, 200, 200, 200)      # front stop threshold is 20 cm
    mgr.attach_hazard(HazardManager(hazard_config))  # no hazard sources at all

    decision = mgr.tick()
    assert decision.action is SafetyAction.STOP
    assert mgr.hazard.state is HazardState.NORMAL   # the hazard layer is happy...
    assert mgr.state.mode is RobotMode.SAFETY_STOP  # ...but Layer 3 still wins


def test_zone_breach_through_a_pose_provider_stops_the_robot(robot, hazard_config):
    mgr, transport = robot
    transport.set_distances(200, 200, 200, 200)
    cfg = dataclasses.replace(
        hazard_config,
        zones=[
            {"name": "bay", "x_min": 2.0, "x_max": 3.0, "y_min": 0.0, "y_max": 1.0},
        ],
    )
    pose = MutablePose(x=0.0, y=0.0)
    mgr.attach_hazard(
        HazardManager.from_config(cfg, pose_provider=lambda: pose)
    )

    mgr.tick()
    assert mgr.hazard.state is HazardState.NORMAL

    pose.x = 2.5                                   # robot enters the restricted bay
    mgr.tick()
    assert mgr.hazard.state is HazardState.STOP
    assert mgr.state.mode is RobotMode.SAFETY_STOP


def test_attaching_a_hazard_layer_does_not_disturb_a_healthy_stack(robot, hazard_config):
    mgr, transport = robot
    transport.set_distances(200, 200, 200, 200)
    mgr.attach_hazard(HazardManager(hazard_config))
    mgr.request_mode(RobotMode.MANUAL)

    assert mgr.tick().action is SafetyAction.PROCEED
    mgr.forward(100)
    assert mgr.drive.last_commanded == (100, 100)   # full speed, NORMAL state
    assert mgr.state.mode is RobotMode.MANUAL
