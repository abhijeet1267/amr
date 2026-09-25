"""C11 — advanced telemetry + mission monitoring console tests.

Includes the **JavaScript syntax check** that C10 made mandatory. C10 shipped a
dashboard-wide break that every pytest test passed over, because the tests
asserted on HTML *text* while the failure was in the executed script. These
tests extract the served ``<script>`` bodies and run ``node --check`` on them.

Node is a *validation tool only* — the AMR never imports it. When it is
unavailable the syntax test **skips with an explicit reason** (it never silently
passes), and Node-free structural tests still run so the suite retains coverage
on a machine without Node.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from amr.telemetry import (
    CONSOLE_SCHEMA_VERSION,
    NOT_AVAILABLE,
    build_console_state,
    component_health,
    hazard_summary,
    route_progress_points,
    source_of,
)
from amr.web.server import DASHBOARD_HTML, INDEX_HTML

NODE = shutil.which("node")


def _telemetry(**over) -> dict:
    """A minimal, fully-populated C7 telemetry dict for console tests."""
    base = {
        "schema_version": "1.0",
        "timestamp": 1000.0,
        "simulated": True,
        "position": {"x": 2.0, "y": 3.0, "z": 0.0, "source": "SIMULATION"},
        "orientation": {"yaw": 1.57, "source": "SIMULATION"},
        "velocity": {"linear": 0.35, "angular": 0.1, "source": "SIMULATION"},
        "navigation": {"state": "MOVING", "current_goal": "shelf_c",
                       "route": [{"x": 2.0, "y": 3.0}, {"x": 4.0, "y": 1.5}],
                       "progress": 0.5, "avoidance": None,
                       "source": "SIMULATION"},
        "safety": {"state": "NORMAL", "action": "PROCEED", "emergency_stop": False,
                   "reasons": [], "hazard_state": "NORMAL", "hazard_latched": False,
                   "source": "SIMULATION"},
        "hazards": {"state": "WARNING", "latched": False, "active": [], "recent": [],
                    "events_recorded": 0, "source": "SIMULATION"},
        "battery": {"percentage": None, "voltage": None, "charging": None,
                    "source": "UNAVAILABLE"},
        "sensors": {"ultrasonic": [], "source": "SIMULATION"},
        "mission": {"mission_id": "m-1", "current_task": "pick",
                    "current_task_type": "pick", "current_task_status": "RUNNING",
                    "queued": 1, "completed_tasks": 2, "failed_tasks": 0,
                    "source": "SIMULATION"},
        "camera": {"status": "SIMULATION", "source_name": "SimulatedCamera",
                   "device": None, "resolution": "640x480", "fps": None,
                   "source": "SIMULATION", "width": 640, "height": 480,
                   "format": "png", "frame_id": 5, "timestamp": 1000.0,
                   "has_frame": True, "error": None},
        "system": {"uptime": 12.0, "software_version": "0.1.0",
                   "robot_id": "AMR-01", "connected": True, "mode": "AUTONOMOUS",
                   "last_error": None, "source": "SIMULATION"},
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# Console state
# --------------------------------------------------------------------------- #
class TestConsoleState:
    def test_schema_and_read_only_flag(self):
        c = build_console_state(_telemetry())
        assert c["schema_version"] == CONSOLE_SCHEMA_VERSION
        assert c["telemetry_schema_version"] == "1.0"
        assert c["read_only"] is True

    def test_robot_panel_copies_position_yaw_velocity(self):
        r = build_console_state(_telemetry())["robot"]
        assert r["robot_id"] == "AMR-01"
        assert r["position"]["x"] == 2.0 and r["position"]["y"] == 3.0
        assert r["orientation"]["yaw"] == 1.57
        assert r["velocity"]["linear"] == 0.35
        assert r["connected"] is True
        assert r["mode"] == "AUTONOMOUS"

    def test_navigation_and_route_progress(self):
        n = build_console_state(_telemetry())["navigation"]
        assert n["state"] == "MOVING"
        assert n["current_goal"] == "shelf_c"
        assert n["route"]["waypoints"] == 2
        assert n["route"]["progress_available"] is True
        assert n["route"]["progress_pct"] == pytest.approx(50.0)

    def test_safety_panel_is_copied_not_redecided(self):
        s = build_console_state(_telemetry())["safety"]
        assert s["action"] == "PROCEED"
        assert s["emergency_stop"] is False
        assert s["hazard_active"] == 0

    def test_mission_panel(self):
        m = build_console_state(_telemetry())["mission"]
        assert m["mission_id"] == "m-1"
        assert m["current_task"] == "pick"
        assert m["completed_tasks"] == 2
        assert m["state"] == "ACTIVE"

    def test_camera_panel(self):
        c = build_console_state(_telemetry())["camera"]
        assert c["status"] == "SIMULATION"
        assert c["width"] == 640 and c["height"] == 480

    def test_source_and_simulated_flags(self):
        c = build_console_state(_telemetry())
        assert c["simulated"] is True
        assert c["source"] == "SIMULATION"

    def test_payload_is_json_serialisable(self):
        json.dumps(build_console_state(_telemetry(), health={}, map_snapshot={},
                                       twin={}))

    def test_deterministic(self):
        assert build_console_state(_telemetry()) == build_console_state(_telemetry())


# --------------------------------------------------------------------------- #
# Absence / honesty — the core C11 contract
# --------------------------------------------------------------------------- #
class TestAbsenceIsPreserved:
    def test_battery_unavailable_is_not_zero(self):
        b = build_console_state(_telemetry())["battery"]
        assert b["percentage"] is None and b["voltage"] is None
        assert b["source"] == "UNAVAILABLE"
        assert b["availability"] == "NOT AVAILABLE"
        assert b["note"] == "no battery source in this build"

    def test_battery_reports_real_values_when_present(self):
        t = _telemetry(battery={"percentage": 78.0, "voltage": 24.1,
                                "charging": False, "source": "LIVE"})
        b = build_console_state(t)["battery"]
        assert b["percentage"] == 78.0
        assert b["source"] == "LIVE"
        assert b["availability"] == "AVAILABLE"

    def test_empty_telemetry_degrades_to_unavailable(self):
        c = build_console_state({})
        assert c["source"] == "LIVE"  # not simulated
        assert c["battery"]["source"] == "UNAVAILABLE"
        assert c["mission"]["state"] == "Mission data unavailable"
        assert c["robot"]["position"]["x"] is None
        # With no data at all, the summary must not invent a healthy robot.
        assert c["system"]["degraded"]

    def test_value_formatter_keeps_none_as_na(self):
        from amr.telemetry.console import _value
        assert _value(None) == NOT_AVAILABLE
        assert _value(0) == "0"           # a real zero is a value
        assert _value(1.5, ".1f") == "1.5"

    def test_source_of_handles_missing_and_enum(self):
        from amr.telemetry import DataSource
        assert source_of({}) == "UNAVAILABLE"
        assert source_of({"source": DataSource.LIVE}) == "LIVE"
        assert source_of({"source": "SIMULATION"}) == "SIMULATION"


# --------------------------------------------------------------------------- #
# Mission states
# --------------------------------------------------------------------------- #
class TestMissionStates:
    @pytest.mark.parametrize("mission,expected", [
        ({"mission_id": "m", "current_task": "pick", "current_task_status": "RUNNING",
          "completed_tasks": 1, "failed_tasks": 0, "source": "SIMULATION"}, "ACTIVE"),
        ({"mission_id": "m", "current_task": None, "current_task_status": None,
          "completed_tasks": 3, "failed_tasks": 0, "source": "SIMULATION"}, "COMPLETED"),
        ({"mission_id": "m", "current_task": "pick", "current_task_status": "RUNNING",
          "completed_tasks": 0, "failed_tasks": 1, "source": "SIMULATION"}, "FAILED"),
        ({"mission_id": None, "current_task": None, "completed_tasks": 0,
          "failed_tasks": 0, "source": "UNAVAILABLE"}, "Mission data unavailable"),
    ])
    def test_mission_state(self, mission, expected):
        c = build_console_state(_telemetry(mission=mission))
        assert c["mission"]["state"] == expected


# --------------------------------------------------------------------------- #
# Hazards
# --------------------------------------------------------------------------- #
class TestHazardPanel:
    def test_world_located_hazard_counts_placed(self):
        t = _telemetry(hazards={"state": "WARNING", "latched": False,
                                "source": "SIMULATION", "events_recorded": 1,
                                "active": [{"kind": "FIRE", "severity": "CRITICAL",
                                            "source": "cam", "confidence": 0.9}]})
        m = {"hazards": [{"kind": "FIRE"}], "unlocated": []}
        h = build_console_state(t, map_snapshot=m)["hazards"]
        assert h["active"] == 1
        assert h["critical"] == 1
        assert h["placed"] == 1
        assert h["unlocated"] == 0
        assert h["kinds"] == ["FIRE"]

    def test_image_only_hazard_is_unlocated_not_placed(self):
        t = _telemetry(hazards={"state": "WARNING", "latched": False,
                                "source": "SIMULATION", "events_recorded": 1,
                                "active": [{"kind": "PERSON", "severity": "WARNING",
                                            "source": "cam", "confidence": 0.7}]})
        m = {"hazards": [], "unlocated": [{"kind": "PERSON"}]}
        h = build_console_state(t, map_snapshot=m)["hazards"]
        assert h["active"] == 1
        assert h["placed"] == 0
        assert h["unlocated"] == 1  # reported, not placed in the world

    def test_non_critical_hazard_not_counted_critical(self):
        t = _telemetry(hazards={"state": "WARNING", "latched": False,
                                "source": "SIMULATION", "events_recorded": 0,
                                "active": [{"kind": "OBSTACLE", "severity": "WARNING"}]})
        h = build_console_state(t)["hazards"]
        assert h["critical"] == 0

    def test_hazard_summary_handles_missing_input(self):
        h = hazard_summary({}, {})
        assert h["active"] == 0 and h["placed"] == 0 and h["unlocated"] == 0


# --------------------------------------------------------------------------- #
# Route progress
# --------------------------------------------------------------------------- #
class TestRouteProgress:
    def test_progress_is_reported_not_recomputed(self):
        r = route_progress_points(_telemetry())
        assert r["progress"] == 0.5
        assert r["progress_pct"] == 50.0
        assert "straight-line" in r["progress_basis"]

    def test_no_route_returns_none(self):
        assert route_progress_points(
            _telemetry(navigation={"state": "IDLE", "source": "SIMULATION"})) is None

    def test_progress_clamped_to_0_1(self):
        r = route_progress_points(_telemetry(navigation={
            "state": "MOVING", "route": [{}], "progress": 1.5,
            "source": "SIMULATION"}))
        assert r["progress_pct"] == 100.0

    def test_nan_progress_is_not_available(self):
        r = route_progress_points(_telemetry(navigation={
            "state": "MOVING", "route": [{}], "progress": float("nan"),
            "source": "SIMULATION"}))
        assert r["progress_available"] is False
        assert r["progress_pct"] is None


# --------------------------------------------------------------------------- #
# System health
# --------------------------------------------------------------------------- #
class TestSystemHealth:
    def test_components_listed_with_source(self):
        rows = component_health(_telemetry(), {"ok": True})
        names = {r["component"] for r in rows}
        assert {"api", "battery", "camera", "navigation", "safety", "sensors"} <= names
        batt = next(r for r in rows if r["component"] == "battery")
        assert batt["source"] == "UNAVAILABLE"
        assert batt["availability"] == "NOT AVAILABLE"

    def test_degraded_lists_unavailable_components(self):
        c = build_console_state(_telemetry(), health={"ok": True})
        assert "battery" in c["system"]["degraded"]

    def test_health_errors_are_carried(self):
        c = build_console_state(_telemetry(), health={"ok": True,
                                                      "status": "DEGRADED",
                                                      "errors": ["x"]})
        assert c["system"]["status"] == "DEGRADED"
        assert c["system"]["errors"] == ["x"]


# --------------------------------------------------------------------------- #
# JavaScript syntax — MANDATORY (C11 §24)
# --------------------------------------------------------------------------- #
def _extract_scripts(html: str) -> list:
    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)


class TestDashboardJavaScriptSyntax:
    """Regression guard for the C10 dashboard-wide JS break.

    The C10 bug was invisible to pytest because the tests asserted on HTML text
    while the failure was in the executed script. These tests run the real
    validator (``node --check``) against the *served* JavaScript.
    """

    def test_scripts_are_present_in_dashboard(self):
        assert _extract_scripts(DASHBOARD_HTML), "dashboard must ship a <script>"

    def test_dashboard_script_is_syntactically_valid(self, tmp_path):
        if not NODE:
            pytest.skip("node not installed: JS syntax NOT verified "
                        "(install Node to enable this check)")
        scripts = _extract_scripts(DASHBOARD_HTML)
        assert scripts
        for i, js in enumerate(scripts):
            f = tmp_path / f"dashboard_{i}.js"
            f.write_text(js, encoding="utf-8")
            proc = subprocess.run([NODE, "--check", str(f)],
                                  capture_output=True, text=True)
            assert proc.returncode == 0, (
                f"dashboard script {i} has invalid JS:\n{proc.stderr}")

    def test_index_script_is_syntactically_valid(self, tmp_path):
        if not NODE:
            pytest.skip("node not installed: JS syntax NOT verified")
        for i, js in enumerate(_extract_scripts(INDEX_HTML)):
            f = tmp_path / f"index_{i}.js"
            f.write_text(js, encoding="utf-8")
            proc = subprocess.run([NODE, "--check", str(f)],
                                  capture_output=True, text=True)
            assert proc.returncode == 0, proc.stderr

    def test_dashboard_script_has_no_actuation_endpoint(self):
        """C11 must not introduce a control path in the browser."""
        for js in _extract_scripts(DASHBOARD_HTML):
            for banned in ("/move", "/drive", "/navigate", "/mission/start"):
                assert banned not in js, f"dashboard JS must not call {banned}"

    def test_dashboard_uses_the_single_console_endpoint(self):
        joined = "\n".join(_extract_scripts(DASHBOARD_HTML))
        assert 'fetch("/dashboard/state"' in joined
        # The per-tick poll must not also fetch telemetry/map/twin directly.
        tick = joined.split("function poll(")[-1]
        assert '"/telemetry"' not in tick
        assert '"/map"' not in tick
        assert '"/digital-twin"' not in tick

    def test_dashboard_contains_c11_panels(self):
        html = DASHBOARD_HTML
        for panel_id in ("o-source", "o-robot", "o-nav", "o-safety", "o-mission",
                         "o-hazards", "m-state", "g-name", "health"):
            assert f'id="{panel_id}"' in html, f"missing C11 panel {panel_id}"
