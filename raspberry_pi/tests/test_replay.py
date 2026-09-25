"""C14 — telemetry recording and deterministic replay (offline engine).

C14 is the *engine* pass: a recorder that witnesses telemetry, and a replay
player that plays it back. There is no dashboard control and no HTTP route in
this milestone, so everything here is an offline library test.

The properties under test, in order of importance:

1. **Determinism** — the same recorded frames plus the same ``advance`` calls
   always produce the same on-screen frames. This is the whole reason the player
   is caller-driven rather than threaded.
2. **Boundedness** — a long run cannot grow memory without limit.
3. **Honesty** — an unknown pose stays unknown; a frame with no timestamp is
   skipped rather than recorded at the wrong moment.
4. **Read-only** — neither the recorder nor the player can reach an actuator.
"""

from __future__ import annotations

import json

import pytest

from amr.telemetry import (
    RECORDING_SCHEMA_VERSION,
    STANDARD_SPEEDS,
    ReplayPlayer,
    ReplayState,
    TelemetryRecorder,
    frame_from_snapshot,
    read_recording,
)


def snapshot(t, *, x=None, yaw=None, action="PROCEED", hazards=()):
    """A minimal C7-shaped telemetry dict at time ``t``."""
    return {
        "timestamp": t,
        "position": {"x": x, "y": 1.0, "z": 0.0},
        "orientation": {"yaw": yaw},
        "navigation": {"state": "MOVING", "goal": "shelf_a"},
        "safety": {"state": "NORMAL", "action": action,
                   "emergency_stop": False},
        "hazards": {"state": "NORMAL", "active": list(hazards)},
        "mission": {"mission_id": "m1", "current_task": "t1",
                    "current_task_type": "PICK",
                    "current_task_status": "RUNNING",
                    "completed_tasks": 0},
    }


def record_run(count=5, step=1.0, start=1000.0, **kw):
    rec = TelemetryRecorder(capacity=50, min_interval_s=0)
    for i in range(count):
        rec.record(snapshot(start + i * step, x=float(i), **kw))
    return rec


def _imports_of(module) -> set:
    import ast
    import inspect
    imported = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    return imported


# --------------------------------------------------------------------------- #
# Frame contract
# --------------------------------------------------------------------------- #
class TestReplayFrame:
    def test_frame_captures_the_fields_a_replay_needs(self):
        frame = frame_from_snapshot(snapshot(10.0, x=1.5, yaw=0.5))
        assert frame["schema_version"] == RECORDING_SCHEMA_VERSION
        assert frame["pose"]["x"] == 1.5
        assert frame["pose"]["yaw"] == 0.5
        assert frame["navigation"]["state"] == "MOVING"
        assert frame["safety"]["action"] == "PROCEED"
        assert frame["mission"]["current_task_type"] == "PICK"

    def test_unknown_pose_stays_unknown_not_zero(self):
        """A missing measurement must never be smoothed into a position."""
        frame = frame_from_snapshot(snapshot(10.0, x=None, yaw=None))
        assert frame["pose"]["x"] is None
        assert frame["pose"]["yaw"] is None

    def test_offset_is_relative_to_the_first_frame(self):
        f0 = frame_from_snapshot(snapshot(100.0), first_timestamp=100.0)
        f1 = frame_from_snapshot(snapshot(103.5), first_timestamp=100.0)
        assert f0["offset_s"] == 0.0
        assert f1["offset_s"] == pytest.approx(3.5)

    def test_frame_is_json_serialisable(self):
        frame = frame_from_snapshot(snapshot(10.0, x=1.0))
        assert json.loads(json.dumps(frame)) == frame

    def test_hazards_carry_kind_severity_and_location(self):
        frame = frame_from_snapshot(snapshot(10.0, hazards=[{
            "kind": "FIRE", "severity": "CRITICAL", "confidence": 0.9,
            "source": "cam", "x": 2.0, "y": 3.0}]))
        assert frame["hazards"] == [{
            "kind": "FIRE", "severity": "CRITICAL", "confidence": 0.9,
            "source": "cam", "x": 2.0, "y": 3.0}]

    def test_non_mapping_hazards_are_skipped(self):
        frame = frame_from_snapshot(
            snapshot(10.0, hazards=[None, 5, "x", {"kind": "SMOKE"}]))
        assert [h["kind"] for h in frame["hazards"]] == ["SMOKE"]

    def test_emergency_action_is_recorded(self):
        frame = frame_from_snapshot(snapshot(10.0, action="STOP"))
        assert frame["safety"]["action"] == "STOP"
        assert frame["safety"]["emergency_stop"] is False

    def test_empty_snapshot_is_survivable(self):
        frame = frame_from_snapshot({})
        assert frame["pose"]["x"] is None


# --------------------------------------------------------------------------- #
# Recorder
# --------------------------------------------------------------------------- #
class TestTelemetryRecorder:
    def test_records_frames_oldest_first(self):
        rec = record_run(4)
        assert len(rec) == 4
        assert [f.offset_s for f in rec.frames()] == [0.0, 1.0, 2.0, 3.0]

    def test_capacity_is_bounded(self):
        """A long run must not grow memory without limit."""
        rec = TelemetryRecorder(capacity=5, min_interval_s=0)
        for i in range(50):
            rec.record(snapshot(1000.0 + i, x=float(i)))
        assert len(rec) == 5
        assert rec.frames()[0].pose["x"] == 45.0
        assert rec.frames()[-1].pose["x"] == 49.0

    def test_capacity_must_be_positive(self):
        with pytest.raises(ValueError):
            TelemetryRecorder(capacity=0)

    def test_min_interval_filters_near_duplicates(self):
        rec = TelemetryRecorder(capacity=100, min_interval_s=1.0)
        rec.record(snapshot(100.0))
        assert rec.record(snapshot(100.2)) is None
        assert rec.record(snapshot(100.4)) is None
        assert rec.record(snapshot(101.5)) is not None
        assert len(rec) == 2
        assert rec.dropped == 2

    def test_min_interval_zero_records_everything(self):
        rec = TelemetryRecorder(capacity=100, min_interval_s=0)
        for i in range(10):
            rec.record(snapshot(1000.0 + i * 0.01))
        assert len(rec) == 10

    def test_frame_without_timestamp_is_skipped_not_misplaced(self):
        rec = TelemetryRecorder(capacity=10, min_interval_s=0)
        assert rec.record({"position": {"x": 1.0}}) is None
        assert len(rec) == 0
        assert rec.dropped == 1

    def test_explicit_timestamp_overrides_the_snapshot(self):
        rec = TelemetryRecorder(capacity=10, min_interval_s=0)
        frame = rec.record(snapshot(1.0), timestamp=500.0)
        assert frame.offset_s == 0.0 and frame.timestamp == 500.0

    def test_unusable_input_is_ignored(self):
        rec = TelemetryRecorder(capacity=10, min_interval_s=0)
        assert rec.record(None) is None
        assert rec.record("nonsense") is None
        assert len(rec) == 0

    def test_clear_resets_state_but_keeps_the_file(self, tmp_path):
        path = tmp_path / "run.jsonl"
        rec = TelemetryRecorder(capacity=10, min_interval_s=0, path=str(path))
        rec.record(snapshot(100.0))
        rec.clear()
        assert len(rec) == 0
        rec.record(snapshot(200.0))
        assert rec.frames()[0].offset_s == 0.0
        assert path.exists()

    def test_duration_is_the_span_of_recorded_frames(self):
        assert record_run(5).duration_s() == 4.0
        assert record_run(1).duration_s() == 0.0

    def test_snapshot_object_is_accepted(self):
        """A TelemetrySnapshot-shaped object works as well as a dict."""
        class Obj:
            def to_dict(self):
                return snapshot(100.0, x=3.0)
        rec = TelemetryRecorder(capacity=5, min_interval_s=0)
        frame = rec.record(Obj())
        assert frame is not None and frame.pose["x"] == 3.0


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
class TestRecordingPersistence:
    def test_round_trip_through_jsonl(self, tmp_path):
        path = tmp_path / "run.jsonl"
        rec = TelemetryRecorder(capacity=10, min_interval_s=0, path=str(path))
        for i in range(4):
            rec.record(snapshot(1000.0 + i, x=float(i)))
        loaded = read_recording(str(path))
        assert len(loaded) == 4
        assert [f.pose["x"] for f in loaded] == [0.0, 1.0, 2.0, 3.0]
        assert [f.offset_s for f in loaded] == [0.0, 1.0, 2.0, 3.0]

    def test_recording_is_append_only_across_runs(self, tmp_path):
        path = tmp_path / "run.jsonl"
        first = TelemetryRecorder(capacity=10, min_interval_s=0, path=str(path))
        first.record(snapshot(1000.0))
        first.clear()
        second = TelemetryRecorder(capacity=10, min_interval_s=0, path=str(path))
        second.record(snapshot(2000.0))
        assert len(read_recording(str(path))) == 2

    def test_each_line_is_one_json_object(self, tmp_path):
        path = tmp_path / "run.jsonl"
        rec = TelemetryRecorder(capacity=10, min_interval_s=0, path=str(path))
        for i in range(3):
            rec.record(snapshot(1000.0 + i))
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln]
        assert len(lines) == 3
        for line in lines:
            assert isinstance(json.loads(line), dict)

    def test_corrupt_line_is_skipped_not_fatal(self, tmp_path):
        """A truncated final line must not make a recording unplayable."""
        path = tmp_path / "run.jsonl"
        rec = TelemetryRecorder(capacity=10, min_interval_s=0, path=str(path))
        rec.record(snapshot(1000.0))
        rec.record(snapshot(1001.0))
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"pose": {"x": 1.0, "y"')  # interrupted write
        assert len(read_recording(str(path))) == 2

    def test_blank_lines_are_ignored(self, tmp_path):
        path = tmp_path / "run.jsonl"
        path.write_text('\n\n{"offset_s": 0.0}\n\n', encoding="utf-8")
        assert len(read_recording(str(path))) == 1

    def test_unwritable_path_warns_and_keeps_recording(self, tmp_path):
        """Persistence is best effort: a logging failure must not stop a run."""
        bad = tmp_path / "missing-dir" / "run.jsonl"
        rec = TelemetryRecorder(capacity=10, min_interval_s=0, path=str(bad))
        for i in range(3):
            rec.record(snapshot(1000.0 + i))
        assert len(rec) == 3


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #
class TestReplayTransport:
    def test_starts_paused_at_the_first_frame(self):
        p = ReplayPlayer(record_run(5).frames())
        assert p.state is ReplayState.PAUSED
        assert p.index == 0 and p.current.offset_s == 0.0

    def test_empty_recording_is_stopped_not_broken(self):
        p = ReplayPlayer()
        assert p.state is ReplayState.STOPPED
        assert p.current is None
        assert p.progress == 0.0 and p.duration_s == 0.0
        assert p.advance(1.0) is None
        p.play()
        assert p.state is ReplayState.STOPPED

    def test_play_pause_toggle(self):
        p = ReplayPlayer(record_run(5).frames())
        assert p.toggle() is ReplayState.PLAYING
        assert p.toggle() is ReplayState.PAUSED
        p.play()
        p.pause()
        assert p.state is ReplayState.PAUSED

    def test_paused_player_does_not_advance(self):
        p = ReplayPlayer(record_run(5).frames())
        for _ in range(10):
            assert p.advance(1.0).offset_s == 0.0
        assert p.index == 0

    def test_restart_returns_to_the_start_paused(self):
        p = ReplayPlayer(record_run(5).frames())
        p.play()
        for _ in range(4):
            p.advance(1.0)
        assert p.index > 0
        p.restart()
        assert p.index == 0 and p.state is ReplayState.PAUSED

    def test_playing_at_the_end_restarts(self):
        p = ReplayPlayer(record_run(3).frames())
        p.play()
        for _ in range(5):
            p.advance(1.0)
        assert p.state is ReplayState.STOPPED
        p.play()
        assert p.index == 0 and p.state is ReplayState.PLAYING

    def test_reaching_the_end_stops_and_holds_the_last_frame(self):
        p = ReplayPlayer(record_run(3).frames())
        p.play()
        for _ in range(5):
            frame = p.advance(1.0)
        assert p.state is ReplayState.STOPPED
        assert p.index == 2 and frame.offset_s == 2.0

    def test_does_not_wrap_around_silently(self):
        p = ReplayPlayer(record_run(3).frames())
        p.play()
        for _ in range(20):
            p.advance(1.0)
        assert p.index == 2, "a replay must not loop without being asked to"

    def test_seek_is_clamped(self):
        p = ReplayPlayer(record_run(5).frames())
        p.seek(99)
        assert p.index == 4
        p.seek(-5)
        assert p.index == 0

    def test_seek_seconds_picks_the_latest_frame_at_or_before(self):
        p = ReplayPlayer(record_run(5).frames())
        p.seek_seconds(2.4)
        assert p.current.offset_s == 2.0
        p.seek_seconds(99)
        assert p.index == 4

    def test_negative_elapsed_time_is_ignored(self):
        p = ReplayPlayer(record_run(5).frames())
        p.play()
        p.advance(1.0)
        before = p.index
        p.advance(-5.0)
        assert p.index == before

    def test_bad_elapsed_time_is_ignored(self):
        p = ReplayPlayer(record_run(3).frames())
        p.play()
        assert p.advance("nonsense") is not None
        assert p.state is ReplayState.PLAYING



# --------------------------------------------------------------------------- #
# Speed
# --------------------------------------------------------------------------- #
class TestReplaySpeed:
    @pytest.mark.parametrize("speed", STANDARD_SPEEDS)
    def test_standard_speeds_are_accepted(self, speed):
        p = ReplayPlayer(record_run(10).frames())
        p.speed = speed
        assert p.speed == speed

    def test_default_speed_is_1x(self):
        assert ReplayPlayer(record_run(3).frames()).speed == 1.0

    def test_half_speed_takes_twice_as_long_to_advance(self):
        frames = record_run(10).frames()
        fast, slow = ReplayPlayer(frames), ReplayPlayer(frames)
        fast.speed, slow.speed = 1.0, 0.5
        fast.play()
        slow.play()
        for _ in range(4):
            fast.advance(0.5)
            slow.advance(0.5)
        assert fast.index > slow.index

    def test_double_speed_advances_further_than_real_time(self):
        frames = record_run(10).frames()
        one, two = ReplayPlayer(frames), ReplayPlayer(frames)
        one.play()
        two.speed = 2.0
        two.play()
        for _ in range(2):
            one.advance(0.5)
            two.advance(0.5)
        assert two.index > one.index
        assert two.elapsed_s == pytest.approx(one.elapsed_s * 2)

    @pytest.mark.parametrize("bad", [0, -1, -0.5, float("nan")])
    def test_non_positive_speed_is_refused(self, bad):
        """A negative speed must not silently mean "rewind"."""
        p = ReplayPlayer(record_run(3).frames())
        with pytest.raises(ValueError):
            p.speed = bad

    def test_non_numeric_speed_is_refused(self):
        p = ReplayPlayer(record_run(3).frames())
        with pytest.raises(ValueError):
            p.speed = "fast"


# --------------------------------------------------------------------------- #
# Determinism — the reason this design exists
# --------------------------------------------------------------------------- #
class TestReplayDeterminism:
    def _run(self, frames, steps, speed=1.0):
        p = ReplayPlayer(frames)
        p.speed = speed
        p.play()
        return [p.advance(dt).offset_s for dt in steps]

    def test_same_inputs_yield_the_same_sequence(self):
        frames = record_run(8).frames()
        steps = [0.1, 0.4, 0.25, 0.9, 0.3, 0.7, 0.2, 1.1, 0.6, 0.5]
        assert self._run(frames, steps) == self._run(frames, steps)

    def test_determinism_holds_across_speeds(self):
        frames = record_run(8).frames()
        steps = [0.3, 0.3, 0.6, 0.2, 0.5, 0.5]
        assert self._run(frames, steps, 0.5) == self._run(frames, steps, 0.5)
        assert self._run(frames, steps, 2.0) == self._run(frames, steps, 2.0)

    def test_recording_the_same_run_twice_replays_identically(self):
        def make():
            rec = TelemetryRecorder(capacity=20, min_interval_s=0)
            for i in range(8):
                rec.record(snapshot(1000.0 + i, x=float(i)))
            return rec.frames()
        steps = [0.2] * 12
        assert self._run(make(), steps) == self._run(make(), steps)

    def test_a_frame_is_held_until_the_clock_passes_it(self):
        """Tie-breaking is exact, so a frame at t is on screen at t."""
        p = ReplayPlayer(record_run(4).frames())
        p.play()
        p.advance(1.0)          # clock is exactly 1.0
        assert p.current.offset_s == 1.0
        # A small step has not yet reached the 2.0 s frame, so 1.0 stays up.
        p.advance(0.01)
        assert p.current.offset_s == 1.0
        p.advance(1.0)          # clock now 2.01 -> past the 2.0 s frame
        assert p.current.offset_s == 2.0

    def test_playback_uses_no_wall_clock_or_thread(self):
        """A source guard: determinism dies the moment time.time() is used."""
        import inspect
        import amr.telemetry.replay as mod
        src = inspect.getsource(mod)
        assert "time.time" not in src
        assert "time.sleep" not in src
        assert "Thread" not in src

    def test_advance_does_not_sleep(self):
        """The engine must be instant; a sleep would make tests slow/flaky."""
        import time
        p = ReplayPlayer(record_run(20).frames())
        p.play()
        t0 = time.perf_counter()
        for _ in range(200):
            p.advance(0.1)
        assert time.perf_counter() - t0 < 1.0


# --------------------------------------------------------------------------- #
# Read-only / safety
# --------------------------------------------------------------------------- #
class TestReplayIsReadOnly:
    def test_recorder_references_no_robot_or_hardware(self):
        import inspect
        import amr.telemetry.recorder as mod
        for forbidden in ("serial", "RPi", "gpio", "socket", "threading",
                          "subprocess"):
            assert forbidden not in _imports_of(mod), forbidden
        src = inspect.getsource(mod)
        for forbidden in ("RobotManager", "MotorDriver", "dispatch(",
                          "forward(", "estop"):
            assert forbidden not in src, forbidden

    def test_player_references_no_robot_or_hardware(self):
        import amr.telemetry.replay as mod
        for forbidden in ("serial", "RPi", "gpio", "socket", "threading"):
            assert forbidden not in _imports_of(mod), forbidden

    def test_recording_a_real_run_touches_nothing(self, config_dir):
        """Record a real mock run: the transport must see no extra writes."""
        from conftest import NoActuation
        from amr.robot import RobotManager
        from amr.telemetry.collector import TelemetryCollector
        from amr.utils.config import load_config
        mgr, transport = RobotManager.create_mock(load_config(str(config_dir)))
        collector = TelemetryCollector(mgr, simulated=True)
        rec = TelemetryRecorder(capacity=20, min_interval_s=0)
        mgr.start()
        try:
            with NoActuation(transport):
                for _ in range(5):
                    rec.record(collector.snapshot())
                mgr.tick()
                rec.record(collector.snapshot())
            assert len(rec) >= 5
        finally:
            mgr.shutdown()

    def test_player_never_calls_the_robot(self):
        p = ReplayPlayer(record_run(5).frames())
        p.play()
        for _ in range(10):
            p.advance(0.5)
        p.restart()
        p.seek(3)
        assert p.status()["frames"] == 5

    def test_status_is_a_plain_dict_for_a_future_ui(self):
        p = ReplayPlayer(record_run(4).frames())
        p.speed = 2.0
        status = p.status()
        assert set(status) == {"state", "index", "frames", "progress",
                               "speed", "elapsed_s", "duration_s"}
        assert json.loads(json.dumps(status)) == status



