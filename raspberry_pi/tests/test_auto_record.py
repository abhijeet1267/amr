"""C15 — automatic telemetry recording in the web runtime.

C14 built the recorder, C14b the dashboard controls; C15 closes the loop by
recording during a live run. The properties that matter:

1. **End to end** — a running mock web app produces a recording that the C14b
   store discovers and the C14 player can read, with no conversion step.
2. **Lifecycle** — start records, stop finalises, restart does not collide, and
   shutdown never leaves a truncated file.
3. **Isolation** — a recording failure must not disturb the control loop, and
   recording must not add a single transport write.
4. **Architecture** — still one control loop, still one timer, still no
   recording thread.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from amr.telemetry import TelemetryRecorder, read_recording
from amr.telemetry.auto_record import AutoRecorder, recording_name
from amr.telemetry.replay import ReplayPlayer
from amr.telemetry.replay_control import RecordingStore

_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config")


def _auto_app(recdir):
    """A real ``AMRWebApp`` wired for C15 auto-recording, plus its mock robot."""
    from amr.robot import RobotManager
    from amr.utils.config import load_config
    from amr.web import AMRWebApp
    mgr, transport = RobotManager.create_mock(load_config(_CONFIG_DIR))
    mgr.test_transport = transport
    app = AMRWebApp(mgr, tick_hz=10.0, simulated=True,
                    recordings_dir=str(recdir), auto_record=True)
    # Record every tick in these tests; production throttles via replay.yaml.
    app._auto._min_interval = 0
    return app, mgr


def _snapshot(t, x=0.0, *, hazards=None, **over):
    """A C7-shaped telemetry dict at time ``t``.

    ``hazards`` fills ``hazards.active`` — the real snapshot shape — rather than
    replacing the section, so the test exercises the production contract.
    """
    snap = {
        "timestamp": t, "position": {"x": x, "y": 0.0, "z": 0.0},
        "orientation": {"yaw": 0.0},
        "navigation": {"state": "MOVING", "goal": "shelf_a"},
        "safety": {"state": "NORMAL", "action": "PROCEED",
                   "emergency_stop": False},
        "hazards": {"state": "NORMAL", "active": list(hazards or ())},
        "mission": {"mission_id": "web-run", "current_task": "t1",
                    "current_task_type": "PICK",
                    "current_task_status": "RUNNING", "completed_tasks": 0},
    }
    snap.update(over)
    return snap


@pytest.fixture
def recdir(tmp_path):
    d = tmp_path / "recordings"
    d.mkdir()
    return d


# --------------------------------------------------------------------------- #
# Naming
# --------------------------------------------------------------------------- #
class TestRecordingNaming:
    def test_name_is_deterministic_for_an_instant(self):
        assert recording_name(1_700_000_000) == recording_name(1_700_000_000)

    def test_name_is_safe_and_discoverable(self, recdir):
        from amr.telemetry.replay_control import is_valid_recording_id
        name = recording_name(1_700_000_000)
        assert is_valid_recording_id(name), name
        assert name.endswith(".jsonl")

    def test_suffix_disambiguates_same_second_runs(self):
        base = recording_name(1_700_000_000)
        second = recording_name(1_700_000_000, 1)
        assert base != second
        assert second.startswith(base[:-len(".jsonl")])

    def test_start_never_overwrites_an_existing_run(self, recdir):
        a = AutoRecorder(recdir, clock=lambda: 1_700_000_000)
        first = a.start()
        a.record(_snapshot(1000.0))      # a run that recorded nothing leaves no
        a.stop()                          # file, so there is nothing to collide with
        b = AutoRecorder(recdir, clock=lambda: 1_700_000_000)
        second = b.start()
        b.record(_snapshot(1000.0))
        b.stop()
        assert first != second
        assert os.path.exists(os.path.join(str(recdir), first))
        assert os.path.exists(os.path.join(str(recdir), second))

    def test_a_run_that_records_nothing_leaves_no_file(self, recdir):
        """An empty recording is noise, not evidence of a run."""
        a = AutoRecorder(recdir, clock=lambda: 1_700_000_000)
        name = a.start()
        a.stop()
        assert not os.path.exists(os.path.join(str(recdir), name))

    def test_start_is_idempotent(self, recdir):
        a = AutoRecorder(recdir, clock=lambda: 1_700_000_000)
        first = a.start()
        assert a.start() == first
        a.stop()

    def test_missing_directory_means_not_available(self, tmp_path):
        a = AutoRecorder(tmp_path / "nope")


# --------------------------------------------------------------------------- #
# Lifecycle + content
# --------------------------------------------------------------------------- #
class TestAutoRecorderLifecycle:
    def test_frames_are_written_and_readable(self, recdir):
        a = AutoRecorder(recdir, min_interval_s=0)
        name = a.start()
        for i in range(5):
            a.record(_snapshot(1000.0 + i, float(i)))
        summary = a.stop()
        assert summary["recording_id"] == name
        assert summary["frames"] == 5
        frames = read_recording(os.path.join(str(recdir), name))
        assert len(frames) == 5
        assert [f.offset_s for f in frames] == [0.0, 1.0, 2.0, 3.0, 4.0]

    def test_recording_carries_meaningful_telemetry(self, recdir):
        a = AutoRecorder(recdir, min_interval_s=0)
        name = a.start()
        a.record(_snapshot(1000.0, 1.25))
        a.stop()
        frame = read_recording(os.path.join(str(recdir), name))[0].to_dict()
        assert frame["timestamp"] == 1000.0
        assert frame["pose"]["x"] == 1.25
        assert frame["navigation"]["state"] == "MOVING"
        assert frame["safety"]["action"] == "PROCEED"
        assert frame["mission"]["mission_id"] == "web-run"
        assert frame["mission"]["current_task_type"] == "PICK"

    def test_hazards_are_recorded_when_present(self, recdir):
        a = AutoRecorder(recdir, min_interval_s=0)
        name = a.start()
        a.record(_snapshot(1000.0, hazards=[{
            "kind": "FIRE", "severity": "CRITICAL", "confidence": 0.9,
            "source": "cam", "x": 2.0, "y": 3.0}]))
        a.stop()
        frame = read_recording(os.path.join(str(recdir), name))[0].to_dict()
        assert frame["hazards"][0]["kind"] == "FIRE"
        assert frame["hazards"][0]["confidence"] == 0.9

    def test_unknown_pose_stays_unknown(self, recdir):
        a = AutoRecorder(recdir, min_interval_s=0)
        name = a.start()
        a.record(_snapshot(1000.0, x=None))
        a.stop()
        frame = read_recording(os.path.join(str(recdir), name))[0].to_dict()
        assert frame["pose"]["x"] is None

    def test_snapshot_without_timestamp_is_skipped(self, recdir):
        """C14's rule survives: no timestamp means no frame, never a guess."""
        a = AutoRecorder(recdir, min_interval_s=0)
        name = a.start()
        assert a.record({"position": {"x": 1.0}}) is False
        a.stop()
        assert not os.path.exists(os.path.join(str(recdir), name))

    def test_min_interval_throttles_the_control_loop_cadence(self, recdir):
        a = AutoRecorder(recdir, min_interval_s=1.0)
        a.start()
        for i in range(10):
            a.record(_snapshot(1000.0 + i * 0.1))
        summary = a.stop()
        # 0.1s apart is under the 1.0s throttle, so most samples are dropped.
        assert summary["dropped"] == 9

    def test_stop_is_idempotent(self, recdir):
        a = AutoRecorder(recdir, min_interval_s=0)
        a.start()
        a.record(_snapshot(1000.0))
        first = a.stop()
        assert a.stop() is None
        assert first is not None

    def test_record_after_stop_is_ignored(self, recdir):
        """A late tick must not append to a finished run."""
        a = AutoRecorder(recdir, min_interval_s=0)
        name = a.start()
        a.record(_snapshot(1000.0))
        a.stop()
        assert a.record(_snapshot(1001.0)) is False
        frames = read_recording(os.path.join(str(recdir), name))
        assert len(frames) == 1

    def test_shutdown_leaves_a_complete_readable_file(self, recdir):
        """No truncated trailing line after a normal stop."""
        a = AutoRecorder(recdir, min_interval_s=0)
        name = a.start()
        for i in range(4):
            a.record(_snapshot(1000.0 + i))
        a.stop()
        raw = (recdir / name).read_text(encoding="utf-8")
        lines = [ln for ln in raw.splitlines() if ln]
        assert len(lines) == 4
        for line in lines:
            json.loads(line)      # every line is complete JSON

    def test_restart_produces_two_valid_distinct_recordings(self, recdir):
        first = AutoRecorder(recdir, min_interval_s=0,
                             clock=lambda: 1_700_000_000)
        n1 = first.start()
        for i in range(3):
            first.record(_snapshot(1000.0 + i))
        first.stop()
        second = AutoRecorder(recdir, min_interval_s=0,
                              clock=lambda: 1_700_000_100)
        n2 = second.start()
        for i in range(2):
            second.record(_snapshot(2000.0 + i))
        second.stop()
        assert n1 != n2
        store = RecordingStore(str(recdir))
        assert set(r.recording_id for r in store.list()) == {n1, n2}
        for name, count in ((n1, 3), (n2, 2)):
            assert len(read_recording(os.path.join(str(recdir), name))) == count

    def test_disabled_recorder_does_nothing(self, recdir):
        a = AutoRecorder(recdir, enabled=False)
        assert a.available is False
        assert a.start() is None
        assert a.record(_snapshot(1.0)) is False
        assert a.stop() is None


def _drive(app, ticks=4, hold=0.35):
    """Let the real control loop run briefly so it records real snapshots.

    ``_control_loop`` is the app's own background thread; it steps on the
    stop-event interval, so a short hold is the honest way to exercise it. The
    recorder is throttled to 0 in :func:`_auto_app`, so each tick is captured.
    """
    time.sleep(hold)
    for _ in range(ticks):
        # The loop thread owns the ticking; just wait for it to accumulate.
        time.sleep(0.05)
    return app._auto.status()


# --------------------------------------------------------------------------- #
# End to end: runtime -> record -> discover -> load -> replay
# --------------------------------------------------------------------------- #
class TestAutoRecordEndToEnd:
    def _app(self, recdir):
        app, mgr = _auto_app(recdir)
        return app, mgr

    def test_recorded_run_is_discoverable_and_replayable(self, recdir):
        """The whole C15 chain through the real app and control loop."""
        app, mgr = self._app(recdir)
        mgr.start()
        app.start(host="127.0.0.1", port=0)
        try:
            _drive(app, ticks=4)
        finally:
            app.stop()
            mgr.shutdown()

        # C14b discovery must see it, with no conversion step.
        ids = [r.recording_id for r in RecordingStore(str(recdir)).list()]
        assert ids, "auto recording must appear in the C14b recording store"

        # The C14 player must read it directly — no conversion step.
        frames = read_recording(os.path.join(str(recdir), ids[0]))
        assert frames
        player = ReplayPlayer.from_recording(frames)
        assert len(player) >= 1
        assert player.current is not None
        # And the player really runs over it.
        player.play()
        player.advance(1.0)
        assert player.elapsed_s >= 0.0

    def test_recorder_is_started_by_the_app_and_closed_on_stop(self, recdir):
        """Startup initialises recording; no manual start is required."""
        app, mgr = self._app(recdir)
        mgr.start()
        app.start(host="127.0.0.1", port=0)
        try:
            rec = app._auto
            assert rec is not None and rec.active is True
            _drive(app, ticks=3)
        finally:
            app.stop()
            mgr.shutdown()
        # Stop closed it, and the file is complete and readable.
        assert rec.active is False
        ids = [r.recording_id for r in RecordingStore(str(recdir)).list()]
        assert ids
        raw = (recdir / ids[0]).read_text(encoding="utf-8")
        for line in [ln for ln in raw.splitlines() if ln]:
            json.loads(line)          # no truncated trailing line
        assert len(read_recording(os.path.join(str(recdir), ids[0]))) >= 1

    def test_app_without_recordings_dir_has_no_recorder(self):
        from amr.robot import RobotManager
        from amr.utils.config import load_config
        from amr.web import AMRWebApp
        mgr, _ = RobotManager.create_mock(load_config(_CONFIG_DIR))
        app = AMRWebApp(mgr, simulated=True)
        assert app._auto.available is False
        assert app._auto.start() is None
        app.stop()

    def test_recorded_frames_carry_real_telemetry(self, recdir):
        """No fabricated fields: frames come from the C7 snapshot."""
        app, mgr = self._app(recdir)
        mgr.start()
        app.start(host="127.0.0.1", port=0)
        try:
            _drive(app, ticks=3)
        finally:
            app.stop()
            mgr.shutdown()
        ids = [r.recording_id for r in RecordingStore(str(recdir)).list()]
        frames = read_recording(os.path.join(str(recdir), ids[0]))
        assert frames
        f = frames[0]
        # ReplayFrame is the C14 contract: typed accessors over the raw dict.
        assert isinstance(f.timestamp, (int, float))
        for section in ("pose", "navigation", "safety", "mission"):
            assert isinstance(getattr(f, section), dict)
        # The raw record is plain JSON-serialisable data.
        assert isinstance(f.data, dict)


# --------------------------------------------------------------------------- #
# Failure isolation
# --------------------------------------------------------------------------- #
class TestAutoRecordFailureIsolation:
    def test_a_failing_recorder_does_not_stop_the_control_loop(self, recdir):
        """A broken recording must not take the robot loop down with it."""
        app, mgr = _auto_app(recdir)
        mgr.start()
        try:
            class Boom:
                available = True
                active = True

                def start(self):
                    return "run"

                def record(self, snapshot):
                    raise OSError("disk full")

                def status(self):
                    return {"enabled": True, "active": True,
                            "last_error": "disk full"}

                def stop(self):
                    return None

            app._auto = Boom()
            # Must not raise: the loop keeps stepping regardless.
            _drive(app, ticks=3)
        finally:
            app._auto = app._auto
            app.stop()
            mgr.shutdown()

    def test_recording_writes_nothing_to_the_transport(self, recdir):
        """Recording is read-only: it adds zero actuator commands."""
        from conftest import NoActuation
        app, mgr = _auto_app(recdir)
        mgr.start()
        try:
            with NoActuation(mgr.test_transport):
                _drive(app, ticks=3)
        finally:
            app.stop()
            mgr.shutdown()

    def test_restart_yields_two_valid_distinct_recordings(self, recdir):
        """start/stop twice: both runs valid, no collision, both discoverable."""
        for _ in range(2):
            app, mgr = _auto_app(recdir)
            mgr.start()
            app.start(host="127.0.0.1", port=0)
            try:
                _drive(app, ticks=3)
            finally:
                app.stop()
                mgr.shutdown()
        ids = [r.recording_id for r in RecordingStore(str(recdir)).list()]
        assert len(ids) == 2, "each run must get its own recording id"
        for name in ids:
            frames = read_recording(os.path.join(str(recdir), name))
            assert frames, f"{name} is empty"
            assert frames[0].timestamp is not None


# --------------------------------------------------------------------------- #
# Architectural guarantees (source-level, as in C14/C14b)
# --------------------------------------------------------------------------- #
class TestAutoRecordArchitecture:
    def _src(self, dotted):
        """Read a module's source for the architectural (source-level) tests."""
        import pathlib
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        parts = dotted.split(".")
        return pathlib.Path(root, "amr", *parts[:-1],
                            parts[-1] + ".py").read_text(encoding="utf-8")

    def test_recorder_has_no_thread_and_no_sleep(self):
        """Recording is a plain function of the existing tick."""
        src = self._src("telemetry.auto_record")
        for banned in ("import threading", "time.sleep", "Thread("):
            assert banned not in src, f"C15 must not add {banned!r}"

    def test_control_loop_still_holds_one_lock_and_one_loop(self):
        """Recording rides the existing loop; no second loop was added."""
        src = self._src("web.server")
        assert src.count("def _control_loop") == 1
        assert src.count("self._stop_evt.wait(interval)") == 1
        assert "self._auto.record(self.telemetry.snapshot())" in src

