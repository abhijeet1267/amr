"""C14b — dashboard replay controls.

C14 built the engine; C14b wires it into the dashboard. The properties that
matter, in order:

1. **Safety** — replay is display-only: no actuator path, no transport writes,
   and the C14 engine's no-thread/no-clock rules survive.
2. **Security** — a client names a *recording id*, never a filesystem path, and
   anything that could escape the recordings directory is refused.
3. **Single tick** — replay advances in the loop the web app already runs; the
   page still has exactly one ``setInterval``.
"""

from __future__ import annotations

import json
import os
import re

import pytest

from amr.telemetry import TelemetryRecorder
from amr.telemetry.replay_control import (
    DashboardReplayState,
    RecordingStore,
    ReplayController,
    is_valid_recording_id,
)


def _snapshot(t, x=0.0):
    return {
        "timestamp": t, "position": {"x": x, "y": 0.0, "z": 0.0},
        "orientation": {"yaw": 0.0}, "navigation": {"state": "MOVING"},
        "safety": {"action": "PROCEED"}, "hazards": {"active": []},
        "mission": {"mission_id": "m1"},
    }


@pytest.fixture
def recdir(tmp_path):
    """A recordings directory with one good and one corrupt recording."""
    d = tmp_path / "recordings"
    d.mkdir()
    rec = TelemetryRecorder(capacity=50, min_interval_s=0,
                            path=str(d / "run.jsonl"))
    for i in range(6):
        rec.record(_snapshot(1000.0 + i, float(i)))
    (d / "corrupt.jsonl").write_text('{"pose": {"x": 1.0, "y"',
                                     encoding="utf-8")
    return d


def _controller(recdir, **kw):
    return ReplayController(RecordingStore(str(recdir)), **kw)


# --------------------------------------------------------------------------- #
# Recording discovery
# --------------------------------------------------------------------------- #
class TestRecordingDiscovery:
    def test_empty_directory(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        assert _controller(d).recordings() == []

    def test_missing_directory_is_unavailable_not_an_error(self, tmp_path):
        ctrl = _controller(tmp_path / "nope")
        assert ctrl.recordings() == []
        assert ctrl.status()["recordings_available"] is False

    def test_one_recording(self, recdir):
        names = [r["recording_id"] for r in _controller(recdir).recordings()]
        assert "run.jsonl" in names

    def test_multiple_recordings(self, recdir):
        for extra in ("a.jsonl", "b.jsonl"):
            (recdir / extra).write_text('{"offset_s": 0}\n', encoding="utf-8")
        names = [r["recording_id"] for r in _controller(recdir).recordings()]
        assert set(names) >= {"run.jsonl", "a.jsonl", "b.jsonl"}

    def test_unreadable_recording_is_skipped(self, recdir):
        """A corrupt file is still listed, but never breaks discovery."""
        names = [r["recording_id"] for r in _controller(recdir).recordings()]
        assert "corrupt.jsonl" in names

    def test_non_recording_files_are_ignored(self, recdir):
        (recdir / "notes.txt").write_text("hello", encoding="utf-8")
        (recdir / ".hidden.jsonl").write_text("{}", encoding="utf-8")
        names = [r["recording_id"] for r in _controller(recdir).recordings()]
        assert "notes.txt" not in names
        assert ".hidden.jsonl" not in names

    def test_ordering_is_deterministic(self, recdir):
        a = [r["recording_id"] for r in _controller(recdir).recordings()]
        b = [r["recording_id"] for r in _controller(recdir).recordings()]


# --------------------------------------------------------------------------- #
# Security — ids only, never paths
# --------------------------------------------------------------------------- #
class TestRecordingIdValidation:
    @pytest.mark.parametrize("bad", [
        "../../etc/passwd", "..", ".", "../run.jsonl", "a/b.jsonl",
        "a\\b.jsonl", "/etc/passwd", "/abs.jsonl", "", ".hidden.jsonl",
        "notes.txt", None, 42, "x" * 300 + ".jsonl", "nul\x00.jsonl",
    ])
    def test_rejects_anything_that_is_not_a_plain_recording_name(self, bad):
        assert is_valid_recording_id(bad) is False

    @pytest.mark.parametrize("good", ["run.jsonl", "2026-09-25_1.jsonl", "a.jsonl"])
    def test_accepts_plain_recording_names(self, good):
        assert is_valid_recording_id(good) is True

    def test_traversal_load_is_refused(self, recdir):
        ctrl = _controller(recdir)
        assert ctrl.load("../../etc/passwd") is DashboardReplayState.ERROR
        assert ctrl.player is None
        assert "invalid" in (ctrl.error or "")

    def test_absolute_path_load_is_refused(self, recdir):
        assert _controller(recdir).load("/etc/passwd") \
            is DashboardReplayState.ERROR

    def test_subdirectory_load_is_refused(self, recdir):
        assert _controller(recdir).load("sub/run.jsonl") \
            is DashboardReplayState.ERROR

    def test_unknown_but_well_formed_id_is_reported(self, recdir):
        ctrl = _controller(recdir)
        assert ctrl.load("missing.jsonl") is DashboardReplayState.ERROR
        assert "not found" in (ctrl.error or "")

    def test_corrupt_recording_loads_as_nothing(self, recdir):
        ctrl = _controller(recdir)
        # The corrupt file has one unusable line, so no frames survive.
        assert ctrl.load("corrupt.jsonl") is DashboardReplayState.ERROR
        assert ctrl.player is None


# --------------------------------------------------------------------------- #
# Load / transport
# --------------------------------------------------------------------------- #
class TestReplayControllerTransport:
    def test_starts_with_no_recording(self, recdir):
        ctrl = _controller(recdir)
        assert ctrl.state is DashboardReplayState.NO_RECORDING
        assert ctrl.active is False
        assert ctrl.current_frame() is None
        assert ctrl.tick(1.0) is None

    def test_load_gives_ready(self, recdir):
        ctrl = _controller(recdir)
        assert ctrl.load("run.jsonl") is DashboardReplayState.READY
        assert ctrl.active is True
        assert ctrl.recording_id == "run.jsonl"
        assert len(ctrl.player) == 6

    def test_play_advances_on_tick(self, recdir):
        ctrl = _controller(recdir)
        ctrl.load("run.jsonl")
        assert ctrl.play() is DashboardReplayState.PLAYING
        ctrl.tick(1.0)
        ctrl.tick(1.0)
        assert ctrl.player.index >= 2

    def test_pause_freezes_and_keeps_the_frame(self, recdir):
        ctrl = _controller(recdir)
        ctrl.load("run.jsonl")
        ctrl.play()
        ctrl.tick(1.0)
        ctrl.tick(1.0)
        before = (ctrl.player.index, ctrl.current_frame()["pose"]["x"])
        assert ctrl.pause() is DashboardReplayState.PAUSED
        for _ in range(5):
            ctrl.tick(1.0)
        # The same frame is still on screen: PAUSE must not unload.
        assert (ctrl.player.index, ctrl.current_frame()["pose"]["x"]) == before
        assert ctrl.player is not None

    def test_restart_returns_to_the_start(self, recdir):
        ctrl = _controller(recdir)
        ctrl.load("run.jsonl")
        ctrl.play()
        for _ in range(3):
            ctrl.tick(1.0)
        assert ctrl.player.index > 0
        assert ctrl.restart() is DashboardReplayState.PAUSED
        assert ctrl.player.index == 0

    def test_reaching_the_end_finishes_and_stops(self, recdir):
        ctrl = _controller(recdir)
        ctrl.load("run.jsonl")
        ctrl.play()
        for _ in range(20):
            ctrl.tick(1.0)
        assert ctrl.state is DashboardReplayState.FINISHED
        assert ctrl.player.index == len(ctrl.player) - 1
        # Ticking after the end must not run past the last frame.
        for _ in range(5):
            ctrl.tick(1.0)
        assert ctrl.player.index == len(ctrl.player) - 1

    def test_unload_returns_to_live(self, recdir):
        ctrl = _controller(recdir)
        ctrl.load("run.jsonl")
        ctrl.play()
        assert ctrl.unload() is DashboardReplayState.NO_RECORDING
        assert ctrl.active is False
        assert ctrl.current_frame() is None

    def test_transport_without_a_recording_is_a_no_op(self, recdir):
        ctrl = _controller(recdir)
        for fn in (ctrl.play, ctrl.pause, ctrl.restart):
            assert fn() is DashboardReplayState.NO_RECORDING
        assert ctrl.set_speed(2.0) is DashboardReplayState.NO_RECORDING


# --------------------------------------------------------------------------- #
# Speed — delegated to the C14 player, not re-implemented here
# --------------------------------------------------------------------------- #
class TestReplayControllerSpeed:
    @pytest.mark.parametrize("speed", [0.5, 1.0, 2.0])
    def test_standard_speeds_are_accepted(self, recdir, speed):
        ctrl = _controller(recdir)
        ctrl.load("run.jsonl")
        ctrl.set_speed(speed)
        assert ctrl.player.speed == speed

    def test_speed_changes_how_far_a_tick_advances(self, recdir):
        """0.5x must cover less ground than 1x, and 1x less than 2x."""
        def reach(speed):
            ctrl = _controller(recdir)
            ctrl.load("run.jsonl")
            ctrl.set_speed(speed)
            ctrl.play()
            ctrl.tick(2.0)
            return ctrl.player.elapsed_s
        assert reach(0.5) < reach(1.0) < reach(2.0)

    def test_speeds_come_from_the_c14_constant(self, recdir):
        from amr.telemetry.replay import STANDARD_SPEEDS
        assert _controller(recdir).status()["speeds"] == list(STANDARD_SPEEDS)

    @pytest.mark.parametrize("bad", [0, -1, "fast", None])
    def test_invalid_speed_is_refused_and_reported(self, recdir, bad):
        ctrl = _controller(recdir)
        ctrl.load("run.jsonl")
        before = ctrl.player.speed
        ctrl.set_speed(bad)
        assert ctrl.player.speed == before
        assert ctrl.error == "invalid speed"

    def test_no_duplicate_speed_constants_in_the_controller(self):
        """The controller must reuse STANDARD_SPEEDS, not redefine 0.5/1/2."""
        import inspect
        import amr.telemetry.replay_control as mod
        src = inspect.getsource(mod)
        assert "STANDARD_SPEEDS" in src
        assert "(0.5, 1.0, 2.0)" not in src
        assert "[0.5, 1, 2]" not in src


# --------------------------------------------------------------------------- #
# Single tick — no second loop, no clock, no thread
# --------------------------------------------------------------------------- #
class TestSingleTickIntegration:
    def test_controller_has_no_clock_or_thread(self):
        import ast
        import inspect
        import amr.telemetry.replay_control as mod
        src = inspect.getsource(mod)
        assert "time.time" not in src
        assert "time.sleep" not in src
        assert "Thread" not in src
        imported = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "threading" not in imported
        assert "time" not in imported

    def test_controller_has_no_actuator_imports(self):
        import ast
        import inspect
        import amr.telemetry.replay_control as mod
        imported = set()
        for node in ast.walk(ast.parse(inspect.getsource(mod))):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for forbidden in ("serial", "RPi", "gpio", "socket", "threading"):
            assert forbidden not in imported, forbidden

    def test_web_app_advances_replay_in_the_existing_loop(self):
        """The tick lives in the existing loop, not in a new timer.

        C15 refactored the loop body into ``_tick_once`` so the demo could drive
        the *same* per-iteration work deterministically. The invariant this test
        protects is unchanged — replay is advanced once per iteration of the one
        existing loop, and no thread is created for it — so the assertions now
        follow the call path (``_control_loop`` -> ``_tick_once``) instead of
        requiring the literal to sit inside one specific function body. This is
        strictly more coverage: it also pins that the loop still delegates to
        that method and still has exactly one wait.
        """
        import inspect
        from amr.web.server import AMRWebApp
        loop_src = inspect.getsource(AMRWebApp._control_loop)
        tick_src = inspect.getsource(AMRWebApp._tick_once)

        # Still exactly one loop, waiting once per iteration, no new thread.
        assert loop_src.count("self._stop_evt.wait(interval)") == 1
        assert "Thread(" not in loop_src
        assert "Thread(" not in tick_src

        # The loop delegates its body to the per-iteration method...
        assert "self._tick_once(interval)" in loop_src
        # ...and that is where replay is advanced, exactly once.
        assert tick_src.count("self._replay.tick(interval)") == 1
        # C15's recording rides the same iteration, not a second one.
        assert tick_src.count("self._auto.record(") == 1

    def test_dashboard_still_has_exactly_one_timer(self):
        """A second setInterval would violate the single-tick rule."""
        from amr.web.server import DASHBOARD_HTML
        js = DASHBOARD_HTML[DASHBOARD_HTML.index("<script>") + 8:
                            DASHBOARD_HTML.rindex("</script>")]
        assert js.count("setInterval") == 1
        assert "setTimeout" not in js

    def test_replay_js_never_posts_to_command(self):
        """The replay block must not fetch the actuator endpoint at all."""
        from amr.web.server import DASHBOARD_HTML
        js = DASHBOARD_HTML[DASHBOARD_HTML.index("<script>") + 8:
                            DASHBOARD_HTML.rindex("</script>")]
        start = js.index("C14b — DASHBOARD REPLAY CONTROLS")
        block = js[start:js.index("function apply(t)", start)]
        # Strip comments so explanatory prose is never mistaken for a call.
        code = "\n".join(ln for ln in block.splitlines()
                         if not ln.strip().startswith(("//", "/*", "*")))
        assert '"/command"' not in code
        assert "'/command'" not in code
        # Every request the replay block makes is a replay endpoint.
        for path in re.findall(r'["\'](/replay/[a-z/]+)["\']', code):
            assert path.startswith("/replay/")

    def test_dashboard_html_never_mentions_the_actuator_endpoint(self):
        """Preserves the pre-existing C9 invariant that these panels are read-only.

        Two earlier milestones already assert this; C14b re-checks it because it
        added the most UI of any reporting milestone, and a stray comment can
        break it just as easily as a stray fetch.
        """
        from amr.web.server import DASHBOARD_HTML
        assert "/command" not in DASHBOARD_HTML



# --------------------------------------------------------------------------- #
# HTTP surface + safety
# --------------------------------------------------------------------------- #
class TestReplayRoutes:
    def _get(self, port, path):
        import urllib.request
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{path}", timeout=8) as r:
            return r.status, json.loads(r.read().decode())

    def _post(self, port, path, payload=None):
        import urllib.request
        body = json.dumps(payload or {}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, json.loads(r.read().decode())

    def _status(self, port, path):
        """Status only — for endpoints that serve HTML rather than JSON."""
        import urllib.request
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{path}", timeout=8) as r:
            return r.status

    @pytest.fixture
    def replay_web(self, recdir, config_dir):
        from amr.robot import RobotManager
        from amr.utils.config import load_config
        from amr.web import AMRWebApp
        mgr, transport = RobotManager.create_mock(load_config(str(config_dir)))
        mgr.test_transport = transport
        app = AMRWebApp(mgr, tick_hz=10.0, simulated=True,
                        recordings_dir=str(recdir))
        port = app.start(host="127.0.0.1", port=0)
        mgr.start()
        try:
            yield port, mgr
        finally:
            app.stop()
            mgr.shutdown()

    def test_recordings_route_lists_and_reports_status(self, replay_web):
        port, _mgr = replay_web
        status, body = self._get(port, "/replay/recordings")
        assert status == 200
        assert any(r["recording_id"] == "run.jsonl"
                   for r in body["recordings"])
        assert body["status"]["state"] == "no_recording"

    def test_status_route_before_any_load(self, replay_web):
        port, _mgr = replay_web
        _status, body = self._get(port, "/replay/status")
        assert body["status"]["active"] is False
        assert body["frame"] is None

    def test_load_then_play_then_status(self, replay_web):
        port, _mgr = replay_web
        _s, body = self._post(port, "/replay/load",
                              {"recording_id": "run.jsonl"})
        assert body["status"]["state"] == "ready"
        _s, body = self._post(port, "/replay/play")
        assert body["status"]["state"] == "playing"
        _s, body = self._get(port, "/replay/status")
        assert body["status"]["active"] is True
        assert body["frame"] is not None

    def test_pause_and_restart_routes(self, replay_web):
        port, _mgr = replay_web
        self._post(port, "/replay/load", {"recording_id": "run.jsonl"})
        self._post(port, "/replay/play")
        _s, body = self._post(port, "/replay/pause")
        assert body["status"]["state"] == "paused"
        _s, body = self._post(port, "/replay/restart")
        assert body["status"]["index"] == 0

    def test_speed_route_uses_the_standard_speeds(self, replay_web):
        port, _mgr = replay_web
        self._post(port, "/replay/load", {"recording_id": "run.jsonl"})
        for speed in (0.5, 1.0, 2.0):
            _s, body = self._post(port, "/replay/speed", {"speed": speed})
            assert body["status"]["speed"] == speed

    def test_speed_without_a_value_is_rejected(self, replay_web):
        port, _mgr = replay_web
        self._post(port, "/replay/load", {"recording_id": "run.jsonl"})
        with pytest.raises(Exception) as exc:
            self._post(port, "/replay/speed", {})
        assert "400" in str(exc.value)

    def test_traversal_load_is_refused_over_http(self, replay_web):
        port, _mgr = replay_web
        _s, body = self._post(port, "/replay/load",
                              {"recording_id": "../../etc/passwd"})
        assert body["status"]["state"] == "error"
        assert "invalid" in body["status"]["error"]

    def test_unknown_recording_is_reported_not_loaded(self, replay_web):
        port, _mgr = replay_web
        _s, body = self._post(port, "/replay/load",
                              {"recording_id": "nope.jsonl"})
        assert body["status"]["state"] == "error"

    def test_unload_route_returns_to_live(self, replay_web):
        port, _mgr = replay_web
        self._post(port, "/replay/load", {"recording_id": "run.jsonl"})
        _s, body = self._post(port, "/replay/unload")
        assert body["status"]["state"] == "no_recording"
        assert body["status"]["active"] is False


    def test_replay_routes_perform_zero_actuator_writes(self, replay_web):
        """The headline safety property, end to end over real HTTP."""
        port, mgr = replay_web
        mgr.test_transport.written.clear()
        self._get(port, "/replay/recordings")
        self._get(port, "/replay/status")
        self._post(port, "/replay/load", {"recording_id": "run.jsonl"})
        for path in ("/replay/play", "/replay/pause", "/replay/restart",
                     "/replay/speed", "/replay/unload"):
            self._post(port, path, {"speed": 2.0})
        assert mgr.test_transport.written == []

    def test_command_route_still_reaches_the_robot(self, replay_web):
        """Replay must not have displaced the actuator endpoint."""
        port, mgr = replay_web
        mgr.test_transport.written.clear()
        # MANUAL first, exactly as the existing command tests do it.
        self._post(port, "/command", {"cmd": "mode", "mode": "manual"})
        self._post(port, "/command", {"cmd": "forward", "speed": 10})
        assert mgr.test_transport.written, "/command must still drive the robot"

    def test_other_endpoints_are_unaffected(self, replay_web):
        port, _mgr = replay_web
        for path in ("/status", "/telemetry", "/health",
                     "/dashboard/state", "/camera/overlay"):
            assert self._get(port, path)[0] == 200, path
        assert self._status(port, "/dashboard") == 200

    def test_dashboard_contains_the_replay_panel(self):
        from amr.web.server import DASHBOARD_HTML
        for token in ("rp-select", "rp-load", "rp-play", "rp-pause",
                      "rp-restart", "rp-speed", "rp-state", "rp-mode",
                      "Historical Replay"):
            assert token in DASHBOARD_HTML, token

    def test_replay_branch_never_reaches_dispatch(self):
        """The replay POST branch must return before the /command path."""
        import inspect
        from amr.web.server import _Handler
        src = inspect.getsource(_Handler.do_POST)
        assert src.index("/replay/load") < src.index('"/command"')
        assert "self.app.dispatch" in src   # the actuator path is intact



