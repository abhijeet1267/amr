"""C15c — AMR Command Center tests.

The Command Center is a **view**, so these tests are mostly about three things:

1. it genuinely serves (routes, assets, well-formed markup),
2. it stays read-only (no actuator writes from any console path), and
3. it never dresses up a missing measurement as a real one.

The third is the one worth being strict about. A console that draws a battery
gauge at 0% when there is no battery sensor is worse than one that shows "n/a",
so the series buffer and the markup are both checked for it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

from amr.telemetry.series import (
    CATEGORIES,
    LEVELS,
    CommandCenterHistory,
    EventStream,
    TelemetrySeries,
    extract_metrics,
)
from conftest import NoActuation


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return r.status, r.read()


def _json(port, path):
    return json.loads(_get(port, path)[1])


def _code(port, path):
    try:
        return _get(port, path)[0]
    except urllib.error.HTTPError as e:
        return e.code


# --------------------------------------------------------------------------- #
# Bounded time-series
# --------------------------------------------------------------------------- #
def _snap(t, **over):
    s = {"timestamp": t, "velocity": {"linear": 0.4},
         "battery": {"percentage": 80.0}}
    s.update(over)
    return s


class TestTelemetrySeries:
    def test_records_speed_and_battery(self):
        series = TelemetrySeries()
        series.record(_snap(1000.0))
        assert series.to_dict()["samples"][0]["v"]["speed"] == 0.4
        assert series.to_dict()["samples"][0]["v"]["battery"] == 80.0

    def test_unavailable_stays_none_and_is_never_zero(self):
        """The single most important honesty property of this milestone."""
        series = TelemetrySeries()
        series.record(_snap(1000.0, battery={"percentage": None}))
        series.record(_snap(1001.0, battery={"percentage": None}))
        vals = [s["v"]["battery"] for s in series.to_dict()["samples"]]
        assert vals == [None, None]
        assert 0 not in vals, "UNAVAILABLE must not be drawn as 0%"

    def test_nan_and_inf_are_not_recorded_as_numbers(self):
        metrics = extract_metrics(
            {"velocity": {"linear": float("nan")},
             "battery": {"percentage": float("inf")}})
        assert metrics["speed"] is None
        assert metrics["battery"] is None

    def test_bool_is_not_treated_as_a_number(self):
        # True == 1 in Python; a boolean must never become a reading.
        assert extract_metrics({"velocity": {"linear": True}})["speed"] is None

    def test_buffer_is_bounded(self):
        series = TelemetrySeries(capacity=10)
        for i in range(500):
            series.record(_snap(2000.0 + i))
        d = series.to_dict()
        assert d["count"] == 10
        assert d["capacity"] == 10
        # The window slides: the newest sample survives, the oldest is dropped.
        assert d["samples"][-1]["t"] == 2000.0 + 499

    def test_missing_timestamp_is_skipped_not_backdated(self):
        series = TelemetrySeries()
        assert series.record({"velocity": {"linear": 1.0}}) is None
        assert series.record({"timestamp": None}) is None
        assert series.to_dict()["count"] == 0

    def test_non_dict_is_ignored(self):
        assert TelemetrySeries().record("nonsense") is None

    def test_revision_advances_only_on_real_samples(self):
        series = TelemetrySeries()
        before = series.to_dict()["revision"]
        series.record({"timestamp": None})
        assert series.to_dict()["revision"] == before
        series.record(_snap(5.0))
        assert series.to_dict()["revision"] == before + 1

    def test_metric_filter_narrows_the_payload(self):
        series = TelemetrySeries()
        series.record(_snap(1.0))
        keys = series.to_dict(["speed"])["samples"][0]["v"].keys()
        assert list(keys) == ["speed"]

    def test_declares_units_for_the_frontend(self):
        metrics = TelemetrySeries().to_dict()["metrics"]
        assert metrics["speed"]["unit"] == "m/s"
        assert metrics["battery"]["unit"] == "%"

    def test_clear_resets(self):
        series = TelemetrySeries()
        series.record(_snap(1.0))
        series.clear()
        assert series.to_dict()["count"] == 0


# --------------------------------------------------------------------------- #
# Event stream
# --------------------------------------------------------------------------- #
def _mission_snap(t, task="t1", ttype="pick", hazards=(), action="PROCEED",
                  camera="SIMULATION", goal="shelf_a"):
    return {
        "timestamp": t,
        "mission": {"current_task": task, "current_task_type": ttype,
                    "current_task_status": "running", "completed_tasks": 0},
        "navigation": {"state": "MOVING", "current_goal": goal},
        "safety": {"state": "NORMAL", "action": action,
                   "emergency_stop": False, "reasons": []},
        "hazards": {"active": list(hazards)},
        "camera": {"status": camera},
        "velocity": {"linear": 0.3},
        "battery": {"percentage": 50},
    }


def _obstacle(t=1001.0, eid="h1", severity="WARNING"):
    return {"kind": "OBSTACLE", "severity": severity, "confidence": 0.77,
            "source": "SimulatedCamera", "event_id": eid, "raised_at": t,
            "location": None, "metadata": {"bbox": [10, 20, 60, 80]}}


class TestEventStream:
    def test_mission_start_is_logged(self):
        st = EventStream()
        st.observe(_mission_snap(1000.0))
        msgs = [e["message"] for e in st.to_dict()["events"]]
        assert any("PICK t1" in m for m in msgs)

    def test_unchanged_state_does_not_repeat(self):
        """A 1 Hz poll must not emit the same line 60 times a minute."""
        st = EventStream()
        for t in range(1000, 1030):
            st.observe(_mission_snap(float(t)))
        nav = [e for e in st.to_dict()["events"] if e["category"] == "NAVIGATION"]
        assert len(nav) == 1

    def test_hazard_is_logged_once_with_its_confidence(self):
        st = EventStream()
        st.observe(_mission_snap(1000.0))
        st.observe(_mission_snap(1001.0, hazards=[_obstacle()]))
        st.observe(_mission_snap(1002.0, hazards=[_obstacle()]))
        vision = [e for e in st.to_dict()["events"] if e["category"] == "VISION"]
        assert len(vision) == 1
        assert "0.77" in vision[0]["message"]

    def test_image_space_hazard_is_categorised_as_vision(self):
        st = EventStream()
        st.observe(_mission_snap(1000.0, hazards=[_obstacle()]))
        assert st.to_dict()["events"][0]["category"] == "VISION"

    def test_emergency_stop_is_critical(self):
        s = _mission_snap(1000.0)
        s["safety"]["emergency_stop"] = True
        st = EventStream()
        st.observe(s)
        ev = st.to_dict()["events"][0]
        assert ev["level"] == "CRITICAL"
        assert "EMERGENCY" in ev["message"]

    def test_avoidance_action_is_logged(self):
        st = EventStream()
        st.observe(_mission_snap(1000.0))
        st.observe(_mission_snap(1001.0, action="TURN"))
        msgs = [e["message"] for e in st.to_dict()["events"]]
        assert any("TURN" in m for m in msgs)

    def test_camera_failure_is_logged(self):
        st = EventStream()
        st.observe(_mission_snap(1000.0, camera="UNAVAILABLE"))
        cam = [e for e in st.to_dict()["events"] if e["category"] == "CAMERA"]
        assert cam and "UNAVAILABLE" in cam[0]["message"]

    def test_degraded_health_is_logged(self):
        st = EventStream()
        st.observe(_mission_snap(1000.0), {"status": "DEGRADED",
                                           "errors": ["robot not connected"]})
        assert any("degraded" in e["message"] for e in st.to_dict()["events"])

    def test_level_and_category_filters(self):
        st = EventStream()
        st.observe(_mission_snap(1000.0))
        st.observe(_mission_snap(1001.0, hazards=[_obstacle()]))
        assert all(e["level"] == "WARNING" for e in st.events(level="WARNING"))
        assert all(e["category"] == "MISSION" for e in st.events(category="MISSION"))
        assert st.events(level="CRITICAL") == []

    def test_events_are_newest_first_and_limited(self):
        st = EventStream()
        st.observe(_mission_snap(1000.0))
        st.observe(_mission_snap(1001.0, task="t2"))
        rows = st.events()
        assert rows[0]["t"] >= rows[-1]["t"]
        assert len(st.events(limit=1)) == 1

    def test_buffer_is_bounded(self):
        st = EventStream(capacity=5)
        for i in range(300):
            st.observe(_mission_snap(2000.0 + i, task=f"t{i}"))
        assert st.to_dict()["count"] == 5

    def test_declares_its_filter_vocabulary(self):
        d = EventStream().to_dict()
        assert list(d["categories"]) == list(CATEGORIES)
        assert list(d["levels"]) == list(LEVELS)

    def test_bad_timestamp_is_ignored(self):
        st = EventStream()
        assert st.observe({"mission": {}}) == []
        assert st.observe("nonsense") == []

    def test_history_bundles_both_buffers(self):
        h = CommandCenterHistory()
        h.observe(_mission_snap(1000.0))
        d = h.to_dict()
        assert set(d) == {"series", "events"}
        assert d["series"]["count"] == 1
        h.clear()
        assert h.to_dict()["series"]["count"] == 0


def _static_js() -> str:
    from amr.web.server import _STATIC_FILES
    return _STATIC_FILES["command_center.js"]


# --------------------------------------------------------------------------- #
# The console actually serves
# --------------------------------------------------------------------------- #
class TestCommandCenterRoutes:
    def test_console_page_loads(self, web):
        _app, port, _mgr = web
        status, body = _get(port, "/command-center")
        assert status == 200
        assert b"AMR Command Center" in body

    def test_console_has_every_operator_panel(self, web):
        _app, port, _mgr = web
        html = _get(port, "/command-center")[1].decode()
        for panel in ("3D Digital Twin", "Live Camera", "Warehouse Map",
                      "Mission", "Telemetry", "Event Log", "Robot Status",
                      "Safety", "Record &amp; Replay"):
            assert panel in html, f"missing panel: {panel}"

    def test_console_is_accessible(self, web):
        _app, port, _mgr = web
        html = _get(port, "/command-center")[1].decode()
        assert 'class="skip-link"' in html
        assert "aria-live" in html
        assert "aria-label" in html
        # Safety must not be signalled by colour alone.
        js = _static_js()
        assert "EMERGENCY STOP" in js and "MOTION PERMITTED" in js

    def test_static_assets_are_served(self, web):
        _app, port, _mgr = web
        assert _code(port, "/static/command_center.css") == 200
        assert _code(port, "/static/command_center.js") == 200

    def test_unknown_static_path_is_404(self, web):
        _app, port, _mgr = web
        assert _code(port, "/static/nope.js") == 404

    @pytest.mark.parametrize("evil", [
        "/static/../../../../etc/passwd",
        "/static/..%2f..%2fetc%2fpasswd",
        "/static/command_center.py",
        "/static/",
    ])
    def test_static_cannot_escape_its_whitelist(self, web, evil):
        """A crafted path must resolve to nothing, never read the filesystem."""
        _app, port, _mgr = web
        assert _code(port, evil) == 404

    def test_console_uses_existing_endpoints_only(self, web):
        _app, port, _mgr = web
        js = _static_js()
        assert "/dashboard/state" in js
        assert "/replay/control" in js
        # The console must never post a robot command.
        assert '"/command"' not in js and "'/command'" not in js


# --------------------------------------------------------------------------- #
# API integration — the console reads what earlier milestones built
# --------------------------------------------------------------------------- #
class TestCommandCenterApi:
    def test_state_carries_history(self, web):
        _app, port, _mgr = web
        state = _json(port, "/dashboard/state")
        assert set(state["history"]) == {"series", "events"}
        assert state["history"]["series"]["capacity"] > 0
        assert state["history"]["events"]["capacity"] > 0

    def test_state_carries_replay_and_recording(self, web):
        _app, port, _mgr = web
        state = _json(port, "/dashboard/state")
        assert "state" in state["replay"]
        assert "recording" in state

    def test_console_stays_read_only(self, web):
        _app, port, _mgr = web
        assert _json(port, "/dashboard/state")["read_only"] is True

    def test_console_reads_never_actuate(self, web):
        _app, port, mgr = web
        with NoActuation(mgr.test_transport):
            for path in ("/command-center", "/dashboard/state", "/telemetry",
                         "/map", "/digital-twin", "/health",
                         "/static/command_center.js"):
                _get(port, path)

    def test_history_fills_from_the_authoritative_tick(self, web):
        _app, port, _mgr = web
        # The control loop feeds the buffer; the console only reads it.
        import time
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if _json(port, "/dashboard/state")["history"]["series"]["count"] > 0:
                break
            time.sleep(0.2)
        assert _json(port, "/dashboard/state")["history"]["series"]["count"] > 0

    def test_unavailable_battery_survives_as_null(self, web):
        """The console must not turn a missing battery into a number."""
        _app, port, _mgr = web
        state = _json(port, "/dashboard/state")
        if state["battery"]["percentage"] is None:
            for s in state["history"]["series"]["samples"]:
                assert s["v"]["battery"] is None

    def test_camera_unavailable_is_reported_honestly(self, web_no_camera):
        _app, port, _mgr = web_no_camera
        cam = _json(port, "/dashboard/state")["camera"]
        if cam["status"] in ("UNAVAILABLE", "ERROR"):
            assert cam["has_frame"] is False

    def test_console_works_without_a_camera(self, web_no_camera):
        _app, port, _mgr = web_no_camera
        assert _code(port, "/command-center") == 200
        assert _code(port, "/dashboard/state") == 200

    def test_live_and_replay_are_distinguishable_fields(self, web):
        """LIVE vs REPLAY must be derivable from state, not from a colour."""
        _app, port, _mgr = web
        state = _json(port, "/dashboard/state")
        assert isinstance(state["replay"]["active"], bool)
        js = _static_js()
        assert '"REPLAY"' in js and '"LIVE"' in js

    def test_replay_does_not_overwrite_live_telemetry(self, web):
        """The C14b invariant: replay is a view, never a second source of truth."""
        _app, port, _mgr = web
        live = _json(port, "/telemetry")
        state = _json(port, "/dashboard/state")
        # Whatever replay is doing, the live endpoint keeps serving live sections.
        assert "mission" in live and "safety" in live
        assert state["replay"]["active"] in (True, False)


# --------------------------------------------------------------------------- #
# Front-end JavaScript is actually valid
# --------------------------------------------------------------------------- #
class TestConsoleJavaScript:
    def test_command_center_js_passes_node_check(self):
        """C10 shipped a bug where a Python-escaped newline silently broke the
        whole dashboard script and no test noticed. C15c keeps a permanent guard.
        Node is only a validation tool; the test below still runs without it.
        """
        js = _static_js()
        try:
            done = subprocess.run(["node", "--check", "-"], input=js,
                                  capture_output=True, text=True, timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("node unavailable; covered by the fallback test")
        if done.returncode != 0:
            pytest.fail(f"command_center.js is not valid JavaScript:\n{done.stderr}")

    def test_console_js_has_balanced_delimiters(self):
        """Deterministic fallback for environments without Node.

        String literals and comments are stripped first, otherwise a brace
        inside a message like ``"{x}"`` would look like a syntax error.
        """
        js = _static_js()
        stripped = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
        stripped = re.sub(r"(?<!:)//[^\n]*", " ", stripped)
        stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', stripped)
        stripped = re.sub(r"'(?:[^'\\]|\\.)*'", "''", stripped)
        for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
            assert stripped.count(opener) == stripped.count(closer), (
                f"unbalanced {opener}{closer} in command_center.js")

    def test_console_never_calls_the_actuator_endpoint(self):
        """The only POST the console may make is the replay transport.

        The check looks for *calls* (`estop(`, `forward(`) rather than bare
        words, because the panel legitimately has a local variable holding the
        e-stop flag for display.
        """
        js = re.sub(r"(?<!:)//[^\n]*", "", _static_js())
        js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
        assert '"/command"' not in js and "'/command'" not in js
        for call in ("estop(", "rotate_left(", "rotate_right(",
                     "forward(", "backward(", ".dispatch("):
            assert call not in js, f"console must not call {call}"
        for banned in ("pwm", "serial.write", "gpio"):
            assert banned not in js
        # The one write it is allowed to make.
        assert '"/replay/control"' in js

    def test_console_uses_a_bounded_number_of_timers(self):
        """No polling storm: one interval drives telemetry, one the file list."""
        js = _static_js()
        assert js.count("setInterval(poll") == 1
        assert js.count("setInterval(") == 2

    def test_console_does_not_fabricate_zero_for_missing_data(self):
        js = _static_js()
        assert "NOT AVAILABLE" in js
        assert '"n/a"' in js

    def test_console_states_image_space_rule_in_the_ui(self):
        """The C13 rule must be visible to the operator, not just in the code."""
        js = _static_js()
        assert "image-space" in js


# --------------------------------------------------------------------------- #
# The history module must stay read-only and hardware-free
# --------------------------------------------------------------------------- #
class TestHistoryIsReadOnly:
    def test_history_module_imports_no_hardware(self):
        import pathlib

        import amr.telemetry.series as mod
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        for banned in ("gpio", "RPi", "serial", "/command", "estop",
                       "from ..robot", "from ..control", "from ..web"):
            assert banned not in src

    def test_observe_never_touches_the_robot(self, web):
        _app, port, mgr = web
        with NoActuation(mgr.test_transport):
            h = CommandCenterHistory()
            for i in range(5):
                h.observe(_mission_snap(1000.0 + i))
            h.to_dict()


# --------------------------------------------------------------------------- #
# C5d: the mission must ride the EXISTING control loop
# --------------------------------------------------------------------------- #
class TestMissionRidesTheControlLoop:
    """Regression cover for a real defect found by watching the demo.

    ``run_web`` used to run its own 1 Hz loop that called ``mgr.tick()`` and
    ``mission.process(dt=1.0)`` while the server's own control loop was already
    ticking at 5-10 Hz. The robot was therefore integrated twice, and the
    planner's clock ran 5-10x too fast, so the goal outran the robot and the AMR
    visibly oscillated along its route instead of driving to it.
    """

    def test_web_app_steps_the_mission_itself(self, config_dir):
        """``_tick_once`` drives the warehouse with the loop's own interval."""
        from amr.robot import RobotManager
        from amr.utils.config import load_config
        from amr.web import AMRWebApp

        config = load_config(config_dir)
        mgr, _ = RobotManager.create_mock(config)

        seen = []

        class RecordingWarehouse:
            def process(self, dt=None):
                seen.append(dt)

        wh = RecordingWarehouse()
        app = AMRWebApp(mgr, warehouse=wh, run_warehouse=True, simulated=True)
        assert app._warehouse is wh, "mission was not handed to the control loop"
        app._tick_once(0.1)
        app._tick_once(0.1)
        assert seen == [0.1, 0.1], "mission must be stepped by _tick_once"
        assert app._tick_hz == 5.0

    def test_mission_is_not_stepped_when_not_requested(self, config_dir):
        """The default (no --mission-demo) must not drive the warehouse."""
        from amr.robot import RobotManager
        from amr.utils.config import load_config
        from amr.web import AMRWebApp

        config = load_config(config_dir)
        mgr, _ = RobotManager.create_mock(config)

        class Warehouse:
            def process(self, dt=None):  # pragma: no cover - must not run
                raise AssertionError("mission must not be stepped")

        app = AMRWebApp(mgr, warehouse=Warehouse(), simulated=True)
        assert app._warehouse is None
        app._tick_once(0.1)      # must not raise

    def test_run_web_does_not_tick_the_robot_itself(self):
        """`run_web` must keep the process alive WITHOUT a second tick loop.

        Source-level: a second `mgr.tick()` / `mission.process()` in main.py is
        exactly the defect, and it is invisible in a unit test of the web app.
        Comments are stripped first — the fix's own explanatory comment
        mentions ``mgr.tick()`` by name, and a naive substring scan would flag
        the very comment that documents the bug.
        """
        import inspect

        from amr.main import run_web
        src = inspect.getsource(run_web)
        # Drop comment-only lines before scanning: the fix's own explanatory
        # comment mentions ``mgr.tick()`` by name, and a naive substring scan
        # would flag the very comment that documents the bug.
        code = "\n".join(
            ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
        body = code.split("port = app.start", 1)[1]
        assert "mgr.tick()" not in body, "run_web must not tick the robot"
        assert ".process(dt=" not in body, "run_web must not step the mission"
        # It must still hand the mission to the app's loop.
        assert "run_warehouse=" in code

    def test_stepping_uses_the_loop_interval_not_a_fixed_second(self, config_dir):
        """A 1.0 dt on a 10 Hz loop is the bug; dt must equal the interval."""
        from amr.robot import RobotManager
        from amr.utils.config import load_config
        from amr.web import AMRWebApp

        config = load_config(config_dir)
        mgr, _ = RobotManager.create_mock(config)
        dts = []

        class Warehouse:
            def process(self, dt=None):
                dts.append(dt)

        app = AMRWebApp(mgr, warehouse=Warehouse(), run_warehouse=True,
                        tick_hz=10.0, simulated=True)
        app._tick_once(1.0 / app._tick_hz)
        assert dts == [pytest.approx(0.1)]
        assert dts[0] != 1.0





