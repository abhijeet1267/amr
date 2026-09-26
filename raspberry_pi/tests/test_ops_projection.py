"""C5e — AMR operations projection tests.

The projection is the only new backend surface in this milestone, so the tests
focus on two things: that it reports the runtime honestly, and that it cannot
become a second runtime. A panel that quietly turns "unknown" into "0" is the
failure mode that matters here, not a missing feature.
"""

from __future__ import annotations

import json
import pathlib
import re
import urllib.request

import pytest

from amr.telemetry import OPS_SCHEMA_VERSION, build_ops_state
from amr.telemetry.ops import (
    DEGRADED,
    FAULT,
    HEALTHY,
    NOT_AVAILABLE,
    NOT_CONNECTED,
    NOT_TESTED,
    WARNING,
)
from conftest import NoActuation


def _console(**over):
    """A C11-shaped console payload with everything populated."""
    base = {
        "schema_version": "1.0",
        "simulated": True,
        "read_only": True,
        "robot": {"robot_id": "AMR-01", "connected": True, "last_error": None,
                  "mode": "AUTONOMOUS",
                  "orientation": {"yaw": 1.6179},
                  "position": {"x": 1.0, "y": 2.0}},
        "safety": {"action": "PROCEED", "emergency_stop": False,
                   "hazard_active": False, "hazard_critical": False,
                   "latched": False, "state": "NORMAL"},
        "system": {"status": "OK", "errors": [], "uptime": 12.5,
                   "connected": True},
        "camera": {"status": "SIMULATION", "source_name": "SimulatedCamera",
                   "width": 1280, "height": 720, "error": None,
                   "frame_id": 4, "timestamp": 1000.0},
        "navigation": {"state": "MOVING", "current_goal": "shelf_a",
                       "route": [{"x": 1}, {"x": 2}],
                       "availability": "AVAILABLE", "source": "SIMULATION"},
        "mission": {"availability": "AVAILABLE", "phase": "NAVIGATE",
                    "state": "ACTIVE", "current_task_type": "PICK",
                    "current_task_status": "RUNNING",
                    "destination": "shelf_a", "completed_tasks": 1,
                    "total_tasks": 3, "failed_tasks": 0,
                    "mission_progress": 0.33, "task_progress": 0.4},
        "hazards": {"state": "NORMAL", "active": 0, "critical": 0,
                    "source": "SIMULATION"},
        "hazard_list": {"active": []},
        "sensors": {"rows": [], "source": "SIMULATION",
                    "availability": "AVAILABLE"},
        "battery": {"percentage": None, "voltage": None,
                    "source": "UNAVAILABLE", "charging": None},
        "replay": {"state": "NO_RECORDING"},
        "recording": {"active": False},
    }
    for key, value in over.items():
        base[key] = value
    return base


@pytest.fixture
def con():
    """The populated console payload every test starts from."""
    return _console()


# --------------------------------------------------------------------------- #
# Health — categorical, never an invented percentage
# --------------------------------------------------------------------------- #
class TestHealth:
    def test_all_good_is_healthy(self, con):
        assert build_ops_state(con)["health"]["overall"] == HEALTHY

    def test_health_is_categorical_not_a_made_up_percentage(self, con):
        health = build_ops_state(con)["health"]
        # A numeric score would imply a weighting the project cannot justify.
        assert health["score"] is None
        assert health["overall"] in (HEALTHY, DEGRADED, "WARNING", FAULT)

    def test_health_explains_itself(self, con):
        """The verdict must always be traceable to a named subsystem."""
        health = build_ops_state(con)["health"]
        assert health["components"]
        for comp in health["components"]:
            assert comp["component"] and comp["state"] and comp["reason"]

    def test_missing_camera_degrades_but_is_not_a_fault(self, con):
        con["camera"] = {"status": "UNAVAILABLE", "error": "picamera2 unavailable"}
        assert build_ops_state(con)["health"]["overall"] == DEGRADED

    def test_camera_error_is_a_fault(self, con):
        con["camera"] = {"status": "ERROR", "error": "sensor fault"}
        assert build_ops_state(con)["health"]["overall"] == FAULT

    def test_critical_hazard_is_a_fault(self, con):
        con["safety"] = dict(con["safety"], hazard_critical=True)
        assert build_ops_state(con)["health"]["overall"] == FAULT

    def test_emergency_stop_is_a_fault(self, con):
        con["safety"] = dict(con["safety"], emergency_stop=True)
        health = build_ops_state(con)["health"]
        assert health["overall"] == FAULT
        safety = [c for c in health["components"] if c["component"] == "safety"][0]
        assert "emergency" in safety["reason"].lower()

    def test_active_hazard_is_a_warning(self, con):
        con["safety"] = dict(con["safety"], hazard_active=True)
        assert build_ops_state(con)["health"]["overall"] == "WARNING"

    def test_controller_error_is_a_fault(self, con):
        con["robot"] = dict(con["robot"], last_error="link lost")
        assert build_ops_state(con)["health"]["overall"] == FAULT

    def test_worst_component_wins(self, con):
        con["camera"] = {"status": "UNAVAILABLE"}
        con["safety"] = dict(con["safety"], hazard_critical=True)
        # A fault must outrank the degraded camera beneath it.
        assert build_ops_state(con)["health"]["overall"] == FAULT


# --------------------------------------------------------------------------- #
# Sensors — the "never turn unknown into zero" rules
# --------------------------------------------------------------------------- #
class TestSensorMatrix:
    def test_camera_row_uses_real_status(self, con):
        rows = {r["sensor"]: r for r in build_ops_state(con)["sensors"]}
        assert rows["camera"]["state"] == "AVAILABLE"
        assert rows["camera"]["value"] == "1280 × 720"

    def test_unwired_sensors_are_listed_not_hidden(self, con):
        names = {r["sensor"] for r in build_ops_state(con)["sensors"]}
        for expected in ("ultrasonic", "gas_sensor", "imu", "battery",
                         "encoder_left", "encoder_right"):
            assert expected in names, expected

    def test_not_connected_is_distinct_from_not_available(self, con):
        rows = {r["sensor"]: r for r in build_ops_state(con)["sensors"]}
        assert rows["gas_sensor"]["state"] == NOT_CONNECTED
        assert rows["battery"]["state"] == NOT_AVAILABLE

    def test_missing_battery_is_never_zero(self, con):
        """The single most important honesty rule in this module."""
        row = [r for r in build_ops_state(con)["sensors"]
               if r["sensor"] == "battery"][0]
        assert row["value"] is None
        assert row["state"] == NOT_AVAILABLE

    def test_real_battery_value_is_shown(self, con):
        con["battery"] = {"percentage": 78.0, "voltage": 24.1,
                          "source": "LIVE", "charging": False}
        row = [r for r in build_ops_state(con)["sensors"]
               if r["sensor"] == "battery"][0]
        assert row["value"] == "78%"
        assert row["state"] == "AVAILABLE"

    def test_existing_sensor_rows_are_passed_through(self, con):
        con["sensors"] = {"rows": [{"sensor": "ultrasonic", "value": 37}],
                          "source": "LIVE", "availability": "AVAILABLE"}
        rows = [r for r in build_ops_state(con)["sensors"]
                if r["sensor"] == "ultrasonic"]
        assert len(rows) == 1
        assert rows[0]["state"] == "AVAILABLE" and rows[0]["value"] == 37


# --------------------------------------------------------------------------- #
# System layers
# --------------------------------------------------------------------------- #
class TestSystemLayers:
    def test_hardware_layers_are_never_claimed(self, con):
        layers = {r["layer"]: r for r in build_ops_state(con)["system"]}
        assert layers["arduino"]["state"] == NOT_TESTED
        assert layers["pi_hardware"]["state"] == NOT_TESTED

    def test_simulation_is_stated_plainly(self, con):
        layers = {r["layer"]: r for r in build_ops_state(con)["system"]}
        assert layers["robot_controller"]["state"] == "SIMULATION"

    def test_a_working_web_page_does_not_claim_a_robot(self, con):
        """A served request proves the server, not the machine."""
        layers = {r["layer"]: r for r in build_ops_state(con)["system"]}
        assert layers["web_server"]["state"] == "CONNECTED"
        assert layers["robot_controller"]["state"] != "CONNECTED"


# --------------------------------------------------------------------------- #
# Identity, navigation, mission
# --------------------------------------------------------------------------- #
class TestIdentityAndNavigation:
    def test_identity_comes_from_the_runtime(self, con):
        ident = build_ops_state(con)["identity"]
        assert ident["robot_id"] == "AMR-01"
        assert ident["simulated"] is True

    def test_missing_robot_id_is_not_invented(self, con):
        con["robot"] = dict(con["robot"], robot_id=None)
        assert build_ops_state(con)["identity"]["robot_id"] == "UNIDENTIFIED"

    def test_heading_is_converted_from_radians(self, con):
        import math
        nav = build_ops_state(con)["navigation"]
        # 1.6179 rad is the authoritative yaw in the fixture.
        assert nav["heading_deg"] == pytest.approx(math.degrees(1.6179), abs=0.1)

    def test_distance_to_target_is_not_fabricated(self, con):
        """The runtime exposes no measured range; inventing one is not allowed."""
        assert build_ops_state(con)["navigation"]["distance_m"] is None

    def test_planner_named_only_when_attached(self, con):
        assert build_ops_state(con)["navigation"]["planner"] == "LocalNavigator"
        con["navigation"] = dict(con["navigation"], availability="NOT AVAILABLE")
        assert build_ops_state(con)["navigation"]["planner"] is None


class TestMissionTimeline:
    def test_current_step_is_marked_current(self, con):
        steps = build_ops_state(con)["mission"]["timeline"]
        states = {s["step"]: s["state"] for s in steps}
        assert states["PICK"] == "current"
        assert states["PLACE"] == "pending"

    def test_later_step_marks_earlier_ones_done(self, con):
        con["mission"] = dict(con["mission"], current_task_type="PLACE")
        states = {s["step"]: s["state"] for s in
                  build_ops_state(con)["mission"]["timeline"]}
        assert states["PICK"] == "done" and states["PLACE"] == "current"

    def test_completed_mission_marks_everything_done(self, con):
        con["mission"] = dict(con["mission"], phase="COMPLETED")
        for step in build_ops_state(con)["mission"]["timeline"]:
            assert step["state"] == "done"

    def test_idle_mission_is_all_pending(self, con):
        con["mission"] = dict(con["mission"], phase="IDLE")
        for step in build_ops_state(con)["mission"]["timeline"]:
            assert step["state"] == "pending"

    def test_statistics_pass_through_real_counters(self, con):
        stats = build_ops_state(con)["mission"]["statistics"]
        assert stats["tasks_completed"] == 1
        assert stats["tasks_total"] == 3
        assert stats["tasks_failed"] == 0


# --------------------------------------------------------------------------- #
# Hazard centre, alerts, performance
# --------------------------------------------------------------------------- #
class TestHazardCentre:
    def test_bbox_is_reported_as_image_space_only(self, con):
        con["hazard_list"] = {"active": [{
            "kind": "OBSTACLE", "severity": "WARNING", "confidence": 0.7,
            "source": "camera_front", "raised_at": 5.0,
            "metadata": {"bbox": [10, 20, 60, 80]},
        }]}
        current = build_ops_state(con)["hazards"]["current"]
        assert current["bbox_image_px"] == [10, 20, 60, 80]
        assert current["coordinate_space"] == "image"
        # The C13 rule: an image bbox is never promoted to a world position.
        assert current["world_location"] is None

    def test_confidence_survives(self, con):
        con["hazard_list"] = {"active": [{
            "kind": "PERSON", "severity": "WARNING", "confidence": 0.91,
            "source": "camera_front", "metadata": {},
        }]}
        current = build_ops_state(con)["hazards"]["current"]
        assert current["confidence"] == pytest.approx(0.91)

    def test_hazard_without_bbox_has_no_coordinate_space(self, con):
        con["hazard_list"] = {"active": [{
            "kind": "SMOKE", "severity": "CRITICAL", "confidence": 0.9,
            "source": "sensor", "metadata": {},
        }]}
        current = build_ops_state(con)["hazards"]["current"]
        assert current["bbox_image_px"] is None
        assert current["coordinate_space"] is None
        assert current["world_location"] is None

    def test_no_hazards_means_no_current(self, con):
        assert build_ops_state(con)["hazards"]["current"] is None


class TestAlertsAndPerformance:
    def test_hazard_raises_a_warning_alert(self, con):
        con["hazards"] = dict(con["hazards"], active=1)
        alerts = build_ops_state(con)["alerts"]
        assert any(a["severity"] == "warning" for a in alerts)

    def test_alerts_are_deduplicated(self, con):
        con["hazards"] = dict(con["hazards"], active=1)
        alerts = build_ops_state(con)["alerts"]
        keys = [(a["severity"], a["category"], a["message"]) for a in alerts]
        assert len(keys) == len(set(keys))

    def test_no_alerts_when_all_is_quiet(self, con):
        assert build_ops_state(con)["alerts"] == []

    def test_perf_exposes_hz_and_nils_the_unmeasured(self, con):
        perf = build_ops_state(con, tick_hz=1.0)["performance"]
        assert perf["dashboard_hz"] == 1.0
        for key in ("api_latency_ms", "camera_fps", "inference_fps",
                    "inference_latency_ms"):
            assert perf[key] is None, key

    def test_replay_summary_absent_without_a_recording(self, con):
        summary = build_ops_state(con)["replay_summary"]
        assert summary["available"] is False
        assert summary["reason"]

    def test_replay_summary_reports_only_loaded_data(self, con):
        con["replay"] = {"state": "FINISHED", "recording_id": "run-1",
                         "frames": 479, "total_frames": 479, "speed": 1.0}
        summary = build_ops_state(con)["replay_summary"]
        assert summary["available"] is True
        assert summary["frames"] == 479


# --------------------------------------------------------------------------- #
# Integration + safety invariants
# --------------------------------------------------------------------------- #
class TestOpsIntegration:
    def test_projection_cannot_reach_an_actuator(self):
        """Source-level: ops.py must not import control or transport code.

        Checked against the *import* graph, not raw substrings: the module
        legitimately contains the word "serial" in the human-readable detail
        string "serial link", and a naive substring scan would flag that
        perfectly harmless label.
        """
        import ast

        import amr.telemetry.ops as mod
        tree = ast.parse(pathlib.Path(mod.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        blob = " ".join(imported)
        for banned in ("gpio", "RPi", "serial", "robot", "control", "web",
                       "pwm", "estop", "transport"):
            assert banned not in blob, banned

    def test_projection_introduces_no_loop_or_timer(self):
        """No polling, sleep or thread may be added by the projection."""
        import amr.telemetry.ops as mod
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        for banned in ("time.sleep", "sleep(", "threading", "Thread(",
                       "while True", "time.time", "asyncio", "setInterval"):
            assert not re.search(rf"\b{re.escape(banned)}", src), banned

    def test_console_state_carries_ops_in_one_request(self, web):
        _app, port, _mgr = web
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/dashboard/state", timeout=10) as r:
            state = json.loads(r.read().decode())
        ops = state["ops"]
        assert ops["schema_version"] == OPS_SCHEMA_VERSION
        assert ops["read_only"] is True
        for key in ("identity", "health", "sensors", "system", "navigation",
                    "mission", "hazards", "performance", "alerts",
                    "safety_history", "replay_summary"):
            assert key in ops, key

    def test_reading_ops_writes_nothing_to_the_transport(self, web):
        _app, port, mgr = web
        with NoActuation(mgr.test_transport):
            for _ in range(3):
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/dashboard/state",
                        timeout=10) as r:
                    json.loads(r.read().decode())

    def test_garbage_input_does_not_crash_the_projection(self):
        for bad in (None, {}, [], "nonsense", {"robot": "not-a-dict"}):
            ops = build_ops_state(bad)
            assert ops["health"]["overall"] in (HEALTHY, DEGRADED, "WARNING",
                                                FAULT)
            assert isinstance(ops["sensors"], list)


