"""Backend projection tests for the Advanced Command Center.

These exercise the read-only projections the web layer added — hardware
inventory, command log, alert engine, and LCD state — directly, without a
server. The focus is the *honesty* rules that matter for a robot console:

* a value is present only when measured; ``None`` is never a fabricated zero;
* a 200 response is recorded as "accepted", not "the robot moved";
* an alert acknowledgement is a flag, not a cure;
* a physical safety alert cannot be cleared by the dashboard.
"""

from __future__ import annotations

import pytest

from amr.telemetry.hardware import (
    ComponentStatus,
    UltrasonicClass,
    build_hardware_inventory,
)
from amr.telemetry.command_log import CommandLog, CommandState
from amr.telemetry.alerts import AlertEngine, Severity
from amr.telemetry.lcd_state import LCD_COLUMNS, build_lcd_state


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _tele(connected=True, **over):
    """A minimal but realistic telemetry snapshot dict.

    Matches the real ``TelemetrySnapshot.to_dict()`` shape: the connection flag
    lives in the ``system`` section (the collector puts it there, not top-level).
    This is the shape that exposed a real bug where the hardware/alerts blocks
    read ``telemetry["connected"]`` (absent) and always reported disconnected.
    """
    base = {
        "simulated": False,
        "timestamp": 1000.0,
        "is_moving": False,
        "left_speed": 0,
        "right_speed": 0,
        "mode": "MANUAL",
        "system": {"connected": True, "mode": "MANUAL", "source": "LIVE",
                   "simulated": False, "last_error": None},
        "sensors": {
            "front_cm": 195, "left_cm": 155, "right_cm": 52, "rear_cm": 57,
            "temperature_c": None, "humidity_pct": None, "gas_raw": None,
            "source": "LIVE",
        },
        "camera": {"status": "LIVE", "source": "RaspberryPiCamera",
                    "width": 1280, "height": 720, "simulated": False,
                    "metadata": {"backend": "picamera2"}},
        "battery": {"percentage": None, "source": "UNAVAILABLE"},
        "safety": {"action": "PROCEED", "state": "MANUAL",
                    "emergency_stop": False, "reasons": [], "source": "LIVE"},
        "hazards": {"active": 0, "critical": 0, "kinds": []},
    }
    base.update(over)
    # `connected` is a first-class param that lands in the system section,
    # matching where TelemetryCollector puts it. (A stray top-level one is also
    # honoured for fixtures that predate the system section.)
    if connected is not True:
        base["system"]["connected"] = connected
        if "connected" in base:
            base["connected"] = connected
    return base


# Per-face stop thresholds, matching config/safety.yaml. The dashboard must
# classify with these (not a single global number), and the caution band is
# CAUTION_FACTOR * stop_cm — the same rule the SafetyManager applies.
_THRESH = {
    "front_stop_cm": 20, "left_stop_cm": 15, "right_stop_cm": 15, "rear_stop_cm": 20,
    "valid_max_cm": 400,
}
_ENV = {"gas_pin": None, "lcd_i2c_address": 0x27, "buzzer_pin": "A0"}


def _by_id(inv, cid):
    return next(c for c in inv.components if c.id == cid)


# --------------------------------------------------------------------------- #
# Hardware inventory
# --------------------------------------------------------------------------- #
class TestHardwareInventory:
    def test_every_expected_component_is_present(self):
        inv = build_hardware_inventory(_tele(), thresholds=_THRESH, env_config=_ENV)
        ids = {c.id for c in inv.components}
        for want in ("pi", "arduino", "motors", "us_front", "us_left",
                     "us_right", "us_rear", "dht11", "gas", "lcd", "buzzer",
                     "camera", "battery"):
            assert want in ids

    def test_connected_robot_reports_connected_controller(self):
        inv = build_hardware_inventory(_tele(), thresholds=_THRESH, env_config=_ENV)
        assert inv.controller_connected is True
        assert _by_id(inv, "arduino").status is ComponentStatus.CONNECTED
        assert _by_id(inv, "pi").status is ComponentStatus.CONNECTED

    def test_disconnected_robot_is_not_shown_healthy(self):
        inv = build_hardware_inventory(
            _tele(connected=False,
                  sensors={"front_cm": None, "left_cm": None,
                           "right_cm": None, "rear_cm": None,
                           "temperature_c": None, "humidity_pct": None,
                           "gas_raw": None, "source": "UNAVAILABLE"}),
            thresholds=_THRESH, env_config=_ENV,
        )
        assert inv.controller_connected is False
        assert _by_id(inv, "arduino").status is ComponentStatus.UNAVAILABLE
        # A missing link must never read as ONLINE.
        assert inv.state in ("DISCONNECTED", "OFFLINE", "SIMULATION")
        assert inv.state not in ("ONLINE",)

    def test_absent_sensors_are_configured_not_zero(self):
        """A missing DHT11 / gas must be CONFIGURED (or UNAVAILABLE), never 0."""
        inv = build_hardware_inventory(_tele(), thresholds=_THRESH, env_config=_ENV)
        dht = _by_id(inv, "dht11")
        gas = _by_id(inv, "gas")
        assert dht.value is None
        assert gas.value is None
        assert dht.status is ComponentStatus.CONFIGURED
        assert gas.status is ComponentStatus.CONFIGURED

    def test_battery_unavailable_is_not_zero_percent(self):
        inv = build_hardware_inventory(_tele(), thresholds=_THRESH, env_config=_ENV)
        batt = _by_id(inv, "battery")
        assert batt.value is None
        assert batt.status is ComponentStatus.UNAVAILABLE

    def test_ultrasonic_classification_uses_per_face_thresholds(self):
        # Per-face bands: <stop -> TOO_CLOSE, stop<=v<2*stop -> CAUTION, else CLEAR.
        # front_stop=20 (band 20-40), right_stop=15 (band 15-30).
        inv = build_hardware_inventory(_tele(), thresholds=_THRESH, env_config=_ENV)
        assert _by_id(inv, "us_front").classification == "CLEAR"   # 195 cm, well clear
        assert _by_id(inv, "us_right").classification == "CLEAR"   # 52 cm, clear of band 30

        # A front reading inside its caution band (20..40) -> CAUTION.
        inv2 = build_hardware_inventory(
            _tele(sensors={"front_cm": 30, "left_cm": 200, "right_cm": 200,
                            "rear_cm": 200, "temperature_c": None,
                            "humidity_pct": None, "gas_raw": None,
                            "source": "LIVE"}),
            thresholds=_THRESH, env_config=_ENV,
        )
        assert _by_id(inv2, "us_front").classification == "CAUTION"

        # A front reading below the stop distance -> TOO_CLOSE.
        inv3 = build_hardware_inventory(
            _tele(sensors={"front_cm": 10, "left_cm": 200, "right_cm": 200,
                            "rear_cm": 200, "temperature_c": None,
                            "humidity_pct": None, "gas_raw": None,
                            "source": "LIVE"}),
            thresholds=_THRESH, env_config=_ENV,
        )
        assert _by_id(inv3, "us_front").classification == "TOO_CLOSE"

    def test_dashboard_classification_matches_the_safety_manager(self):
        """The dashboard's per-face classification must agree with the robot's
        own SafetyManager for the same reading.

        This is the regression that motivated the per-face fix: a single global
        threshold would classify differently from the SafetyManager, which uses
        per-face stop distances and a CAUTION_FACTOR * stop caution band.
        """
        from amr.safety import SafetyAction, SafetyManager
        from amr.sensors import UltrasonicReading
        from amr.utils.config import SafetyConfig

        cfg = SafetyConfig()  # front/rear 20, left/right 15
        mgr = SafetyManager(cfg)

        def dashboard_class(dist):
            inv = build_hardware_inventory(
                _tele(sensors={"front_cm": dist, "left_cm": dist,
                                "right_cm": dist, "rear_cm": dist,
                                "temperature_c": None, "humidity_pct": None,
                                "gas_raw": None, "source": "LIVE"}),
                thresholds={
                    "front_stop_cm": cfg.front_stop_distance_cm,
                    "left_stop_cm": cfg.left_stop_distance_cm,
                    "right_stop_cm": cfg.right_stop_distance_cm,
                    "rear_stop_cm": cfg.rear_stop_distance_cm,
                    "valid_max_cm": cfg.sensor_max_valid_cm,
                },
                env_config=_ENV,
            )
            return {c.id: c.classification for c in inv.components}

        # 100 cm on all faces: SafetyManager -> PROCEED; dashboard -> all CLEAR.
        reading = UltrasonicReading(front=100, left=100, right=100, rear=100)
        assert mgr.check(reading, connected=True).action is SafetyAction.PROCEED
        classes = dashboard_class(100)
        assert classes["us_front"] == "CLEAR" and classes["us_rear"] == "CLEAR"
        assert classes["us_left"] == "CLEAR" and classes["us_right"] == "CLEAR"

        # Front 15 cm: SafetyManager -> STOP (front < 20). Dashboard front
        # -> TOO_CLOSE; other faces (15cm) are at their own stop boundary.
        reading2 = UltrasonicReading(front=15, left=100, right=100, rear=100)
        assert mgr.check(reading2, connected=True).action is SafetyAction.STOP
        classes2 = build_hardware_inventory(
            _tele(sensors={"front_cm": 15, "left_cm": 100, "right_cm": 100,
                            "rear_cm": 100, "temperature_c": None,
                            "humidity_pct": None, "gas_raw": None,
                            "source": "LIVE"}),
            thresholds={
                "front_stop_cm": cfg.front_stop_distance_cm,
                "left_stop_cm": cfg.left_stop_distance_cm,
                "right_stop_cm": cfg.right_stop_distance_cm,
                "rear_stop_cm": cfg.rear_stop_distance_cm,
                "valid_max_cm": cfg.sensor_max_valid_cm,
            },
            env_config=_ENV,
        )
        assert _by_id(classes2, "us_front").classification == "TOO_CLOSE"

        # Front 35 cm: SafetyManager -> WAIT (20 <= 35 < 40 = 2*20). Dashboard
        # front -> CAUTION. This is the band that differs from a naive
        # "below 40 = obstacle" and must match the manager's WAIT.
        reading3 = UltrasonicReading(front=35, left=200, right=200, rear=200)
        assert mgr.check(reading3, connected=True).action is SafetyAction.WAIT
        classes3 = build_hardware_inventory(
            _tele(sensors={"front_cm": 35, "left_cm": 200, "right_cm": 200,
                            "rear_cm": 200, "temperature_c": None,
                            "humidity_pct": None, "gas_raw": None,
                            "source": "LIVE"}),
            thresholds={
                "front_stop_cm": cfg.front_stop_distance_cm,
                "left_stop_cm": cfg.left_stop_distance_cm,
                "right_stop_cm": cfg.right_stop_distance_cm,
                "rear_stop_cm": cfg.rear_stop_distance_cm,
                "valid_max_cm": cfg.sensor_max_valid_cm,
            },
            env_config=_ENV,
        )
        assert _by_id(classes3, "us_front").classification == "CAUTION"

    def test_no_echo_is_not_an_obstacle(self):
        """A None reading is NO_ECHO, never an obstacle or a 0."""
        inv = build_hardware_inventory(
            _tele(sensors={"front_cm": None, "left_cm": 200, "right_cm": 200,
                            "rear_cm": 200, "temperature_c": None,
                            "humidity_pct": None, "gas_raw": None,
                            "source": "LIVE"}),
            thresholds=_THRESH, env_config=_ENV,
        )
        assert _by_id(inv, "us_front").classification == UltrasonicClass.NO_ECHO.value
        assert _by_id(inv, "us_front").value is None

    def test_simulated_is_labeled(self):
        inv = build_hardware_inventory(_tele(simulated=True), thresholds=_THRESH,
                                        env_config=_ENV)
        assert inv.state == "SIMULATION"
        assert _by_id(inv, "arduino").simulated is True
        assert _by_id(inv, "us_front").simulated is True

    def test_out_of_range_is_flagged_not_clamped(self):
        inv = build_hardware_inventory(
            _tele(sensors={"front_cm": 900, "left_cm": 200, "right_cm": 200,
                            "rear_cm": 200, "temperature_c": None,
                            "humidity_pct": None, "gas_raw": None,
                            "source": "LIVE"}),
            thresholds=_THRESH, env_config=_ENV,
        )
        assert _by_id(inv, "us_front").classification == UltrasonicClass.OUT_OF_RANGE.value

    def test_to_dict_is_json_safe(self):
        inv = build_hardware_inventory(_tele(), thresholds=_THRESH, env_config=_ENV)
        d = inv.to_dict()
        assert d["backend_online"] is True
        assert isinstance(d["components"], list)
        # Every component round-trips its status as a string.
        for c in d["components"]:
            assert isinstance(c["status"], str)


# --------------------------------------------------------------------------- #
# Command log — acceptance is not execution
# --------------------------------------------------------------------------- #
class TestCommandLog:
    def test_succeeded_does_not_claim_motion(self):
        log = CommandLog()
        r = log.create("forward", {"speed": 50}, environment="SIMULATION")
        log.mark_validated(r.command_id)
        log.mark_succeeded(r.command_id, {"ok": True}, executed=None)
        assert r.state is CommandState.SUCCEEDED
        assert r.executed is None  # not assumed True from an acceptance

    def test_rejection_is_recorded(self):
        log = CommandLog()
        r = log.create("forward", {"speed": 50})
        log.mark_rejected(r.command_id, "safety veto")
        assert r.state is CommandState.REJECTED
        assert "safety veto" in r.error

    def test_unknown_command_rejected(self):
        log = CommandLog()
        r = log.create("bogus", {})
        log.mark_rejected(r.command_id, "unknown command")
        assert r.state is CommandState.REJECTED

    def test_environment_is_recorded(self):
        log = CommandLog()
        r = log.create("stop", {}, environment="SIMULATION")
        assert r.environment == "SIMULATION"
        assert r.to_dict()["environment"] == "SIMULATION"

    def test_counts_by_state(self):
        log = CommandLog()
        a = log.create("stop", {}); log.mark_succeeded(a.command_id, {})
        b = log.create("forward", {"speed": 5})
        log.mark_rejected(b.command_id, "range")
        c = log.create("mode", {"mode": "MANUAL"})
        log.mark_failed(c.command_id, "boom")
        assert log.count_by_state() == {"SUCCEEDED": 1, "REJECTED": 1, "FAILED": 1}

    def test_latest_is_most_recent_first_and_bounded(self):
        log = CommandLog(maxlen=3)
        for i in range(5):
            r = log.create("stop", {"n": i}); log.mark_succeeded(r.command_id, {})
        latest = log.latest()
        assert len(latest) == 3
        # Most recent param first.
        assert latest[0].params["n"] == 4
        assert log.to_dict(limit=10)["total"] == 3

    def test_duration_is_measured(self):
        log = CommandLog()
        r = log.create("stop", {})
        log.mark_succeeded(r.command_id, {})
        assert r.to_dict()["duration_ms"] >= 0


# --------------------------------------------------------------------------- #
# Alert engine — acknowledge is a flag, not a cure
# --------------------------------------------------------------------------- #
class TestAlertEngine:
    def test_disconnection_raises_controller_alert(self):
        eng = AlertEngine()
        state = eng.poll(_tele(connected=False), now=1000.0)
        srcs = {a["source"] for a in state["active"]}
        assert "arduino" in srcs
        assert state["active_count"] >= 1

    def test_recovery_resolves_but_keeps_history(self):
        eng = AlertEngine()
        eng.poll(_tele(connected=False), now=1000.0)
        state2 = eng.poll(_tele(connected=True), now=1005.0)
        # The connection is back, so the controller alert is no longer active...
        assert all(a["source"] != "arduino" for a in state2["active"])
        # ...but it is retained in resolved history, not deleted.
        resolved_srcs = {a["source"] for a in state2["resolved"]}
        assert "arduino" in resolved_srcs

    def test_acknowledge_does_not_resolve(self):
        eng = AlertEngine()
        state = eng.poll(_tele(connected=False), now=1000.0)
        ardr = next(a for a in state["active"] if a["source"] == "arduino")
        assert eng.acknowledge(ardr["alert_id"]) is True
        # The condition is still present, so it is still active after the next
        # poll — acking did not clear it.
        state2 = eng.poll(_tele(connected=False), now=1001.0)
        ardr2 = next(a for a in state2["active"] if a["source"] == "arduino")
        assert ardr2["acknowledged"] is True
        assert ardr2["status"] == "ACTIVE"

    def test_acknowledge_unknown_id_is_false(self):
        eng = AlertEngine()
        assert eng.acknowledge("nope") is False

    def test_emergency_stop_is_critical_and_not_user_clearable(self):
        eng = AlertEngine()
        state = eng.poll(
            _tele(safety={"action": "PROCEED", "state": "SAFETY_STOP",
                           "emergency_stop": True, "reasons": ["E-STOP"],
                           "source": "LIVE"}),
            now=1000.0,
        )
        estop = next(a for a in state["active"] if a["source"] == "safety")
        assert estop["severity"] == Severity.CRITICAL.value
        assert estop["clearable_by_user"] is False
        assert state["critical_count"] >= 1

    def test_severity_ranking(self):
        assert Severity.CRITICAL.rank() > Severity.ERROR.rank()
        assert Severity.ERROR.rank() > Severity.WARNING.rank()
        assert Severity.WARNING.rank() > Severity.INFO.rank()

    def test_stale_telemetry_fires(self):
        eng = AlertEngine(stale_after_s=5.0)
        # Snapshot timestamp 1000, polled at 1010 -> 10 s old -> stale.
        state = eng.poll(_tele(), now=1010.0)
        srcs = {a["source"] for a in state["active"]}
        assert "telemetry" in srcs or "backend" in srcs

    def test_no_false_alert_when_healthy(self):
        """A healthy robot with *working* sensors has no active alerts."""
        eng = AlertEngine()
        tele = _tele(sensors={
            "front_cm": 195, "left_cm": 155, "right_cm": 52, "rear_cm": 57,
            "temperature_c": 24.0, "humidity_pct": 51, "gas_raw": 312,
            "source": "LIVE",
        })
        state = eng.poll(tele, now=1000.0)
        assert state["active_count"] == 0

    def test_absent_dht11_is_an_info_not_a_fault(self):
        """A missing (but configured) DHT11 is INFO, never ERROR/CRITICAL."""
        eng = AlertEngine()
        state = eng.poll(_tele(), now=1000.0)
        dht = [a for a in state["active"] if a["source"] == "dht11"]
        assert dht, "a configured-but-silent DHT11 should be surfaced"
        assert dht[0]["severity"] == Severity.INFO.value

    def test_duplicate_suppression_one_alert_per_condition(self):
        eng = AlertEngine()
        for i in range(10):
            state = eng.poll(_tele(connected=False), now=1000.0 + i)
        ardr = [a for a in state["active"] if a["source"] == "arduino"]
        assert len(ardr) == 1  # one alert, refreshed, not ten

    def test_camera_error_alert(self):
        eng = AlertEngine()
        state = eng.poll(
            _tele(camera={"status": "ERROR", "source": "RaspberryPiCamera",
                           "error": "acquire failed"}),
            now=1000.0,
        )
        assert any(a["source"] == "camera" for a in state["active"])


# --------------------------------------------------------------------------- #
# LCD state — intended content is never claimed as confirmed
# --------------------------------------------------------------------------- #
class TestLcdState:
    def test_rows_fit_the_physical_display(self):
        st = build_lcd_state(_tele(), connected=True)
        assert len(st.rows) == 2
        for row in st.rows:
            assert len(row) == LCD_COLUMNS

    def test_content_is_never_confirmed(self):
        """The LCD is write-only, so confirmation is always False."""
        st = build_lcd_state(_tele(), connected=True)
        assert st.content_confirmed is False
        # And the note says so, so the UI can label it as intended.
        assert "confirmed" in st.note.lower() or "intended" in st.note.lower()

    def test_emergency_precedes_command(self):
        st = build_lcd_state(
            _tele(safety={"action": "PROCEED", "state": "SAFETY_STOP",
                           "emergency_stop": True, "reasons": ["E-STOP"],
                           "source": "LIVE"}),
            connected=True, command_label="forward",
        )
        # The safety message wins the row over a stale command label.
        assert "STOP" in st.rows[1].upper() or "E-STOP" in st.rows[1].upper()

    def test_virtual_when_not_connected(self):
        st = build_lcd_state(_tele(), connected=False)
        assert st.connected is False
        assert "virtual" in st.note.lower()

    def test_mode_on_first_row(self):
        # MANUAL fits "MANUAL  DRIVING" within the 16-column physical display.
        st = build_lcd_state(_tele(mode="MANUAL", is_moving=True), connected=True)
        assert "MANUAL" in st.rows[0]
        assert "DRIVING" in st.rows[0]

    def test_long_mode_is_truncated_not_overflowed(self):
        # AUTONOMOUS + DRIVING is 19 chars; the display must clip to 16, never
        # silently overflow or drop the row.
        st = build_lcd_state(_tele(mode="AUTONOMOUS", is_moving=True), connected=True)
        assert len(st.rows[0]) == LCD_COLUMNS
        assert st.rows[0].startswith("AUTONOMOUS")
