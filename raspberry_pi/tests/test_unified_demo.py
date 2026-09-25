"""C15 — the unified deterministic demo.

The flagship test here (:class:`TestUnifiedDemoEndToEnd`) drives the *real*
components — warehouse task manager, hazard layer, vision source, C6 avoidance
policy, telemetry collector, the runtime recorder, the replay player — and
asserts the scenario transitions. It does not stub the pipeline, does not
assert printed strings, and does not write a recording by hand: the runtime
records the run, and the test finds that recording through ``RecordingStore``.
"""

from __future__ import annotations

import os

import pytest

from amr.demo import (
    DEMO_CLEARANCE,
    OBSTACLE_BBOX,
    OBSTACLE_CONFIDENCE,
    ActuationAudit,
    ScriptedVisionDetector,
    SimulatedClearance,
    format_report,
    run_unified_demo,
)
from amr.telemetry import read_recording
from amr.telemetry.replay import ReplayPlayer
from amr.telemetry.replay_control import RecordingStore
from amr.utils.config import find_config_dir, load_config


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    """One real demo run, shared by the read-only assertions below."""
    recdir = str(tmp_path_factory.mktemp("recordings"))
    config = load_config(find_config_dir())
    return run_unified_demo(config, recdir), recdir


# --------------------------------------------------------------------------- #
# The flagship integration test
# --------------------------------------------------------------------------- #
class TestUnifiedDemoEndToEnd:
    def test_the_whole_chain_passes(self, demo):
        """mission -> vision -> hazard -> safety -> nav -> record -> replay."""
        result, _ = demo
        assert result.ok, f"demo reported failures: {result.failures}"
        assert result.failures == []

    def test_mission_starts_progresses_and_completes(self, demo):
        result, _ = demo
        assert result.mission_id == "c15-unified-demo"
        assert result.tasks_completed == 3
        assert result.mission_final_phase == "COMPLETED"
        assert result.mission_final_progress == pytest.approx(1.0)

    def test_vision_produced_a_detection_through_the_c5_contract(self, demo):
        result, _ = demo
        assert result.detection_class == "OBSTACLE"
        assert result.detections_emitted > 0
        assert result.detection_confidence == OBSTACLE_CONFIDENCE

    def test_bbox_stayed_in_image_space(self, demo):
        """C13 rule: a pixel box is never turned into a world coordinate."""
        result, _ = demo
        assert result.detection_bbox == [float(v) for v in OBSTACLE_BBOX]
        # It survived as metadata, and the event gained no world position.
        assert result.hazard_bbox_in_metadata is True
        assert result.hazard_placed_in_world is False

    def test_hazard_event_kept_its_metadata(self, demo):
        result, _ = demo
        assert result.hazard_kind == "OBSTACLE"
        assert result.hazard_severity == "WARNING"
        assert result.hazard_state == "WARNING"
        assert result.hazard_source == "camera_front"
        assert result.hazard_event_id

    def test_safety_layer_ran_and_stayed_authoritative(self, demo):
        result, _ = demo
        # A non-blocking WARNING must not become a stop: that is exactly the
        # case the C6 avoidance gate exists for.
        assert result.safety_actions
        assert "STOP" not in result.safety_actions

    def test_navigation_actually_changed(self, demo):
        result, _ = demo
        assert any(a in result.avoidance_actions for a in ("TURN", "REPLAN"))
        # A TURN must be visible in the pose, not just in a log line.
        assert abs(result.yaw_turn_deg) > 1.0

    def test_mission_continued_after_the_hazard_and_finished(self, demo):
        result, _ = demo
        hazard_at = result.timeline_index("hazard:WARNING")
        done_at = result.timeline_index("mission:COMPLETED")
        assert hazard_at >= 0
        assert done_at > hazard_at
        # The scenario really is ordered: hazard, then avoidance, then finish.
        assert result.timeline.index("avoidance:TURN") > hazard_at

    def test_runtime_recorded_automatically(self, demo):
        """C14c: the recorder ran because the runtime ticked — not by hand."""
        result, recdir = demo
        assert result.recording_id
        assert result.recording_frames > 0
        assert os.listdir(recdir) == [result.recording_id]

    def test_recording_is_discoverable_and_valid(self, demo):
        result, recdir = demo
        store = RecordingStore(recdir)
        assert [r.recording_id for r in store.list()] == [result.recording_id]
        frames = read_recording(os.path.join(recdir, result.recording_id))
        assert len(frames) == result.recording_frames
        for frame in frames:                 # every line is complete JSON
            assert isinstance(frame.data, dict)
            assert "timestamp" in frame.data

    def test_replay_loads_the_recording_and_shows_the_scenario(self, demo):
        result, recdir = demo
        frames = read_recording(os.path.join(recdir, result.recording_id))
        player = ReplayPlayer.from_recording(frames)
        assert len(player) == result.recording_frames
        assert result.replay_frames > 0
        assert result.replay_has_mission is True
        assert result.replay_has_hazard is True
        assert result.replay_has_completion is True

    def test_replay_actually_advances(self, demo):
        result, recdir = demo
        frames = read_recording(os.path.join(recdir, result.recording_id))
        player = ReplayPlayer.from_recording(frames)
        player.play()
        player.advance(1.0)
        assert player.elapsed_s > 0.0
        assert player.current is not None


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #
class TestDeterminism:
    def _run(self, tmp_path, name):
        """Run the demo into a directory that actually exists.

        The recorder allocates a name inside the directory but does not create
        the directory itself, so a not-yet-created path silently yields no
        recording. Creating it here keeps the test honest about that contract.
        """
        recdir = tmp_path / name
        recdir.mkdir()
        return run_unified_demo(load_config(find_config_dir()), str(recdir))

    def test_two_runs_produce_the_same_scenario(self, tmp_path):
        a = self._run(tmp_path, "a")
        b = self._run(tmp_path, "b")
        assert a.timeline == b.timeline
        assert a.steps == b.steps
        assert a.tasks_completed == b.tasks_completed
        assert a.mission_final_phase == b.mission_final_phase
        assert a.hazard_kind == b.hazard_kind
        assert a.hazard_event_id == b.hazard_event_id
        assert a.avoidance_actions == b.avoidance_actions
        assert a.safety_actions == b.safety_actions
        assert a.recording_frames == b.recording_frames
        assert a.yaw_turn_deg == b.yaw_turn_deg
        assert a.ok and b.ok

    def test_the_cli_report_is_byte_identical(self, tmp_path):
        first = format_report(self._run(tmp_path, "a"))
        second = format_report(self._run(tmp_path, "b"))
        assert first == second

    def test_recording_ids_may_differ_but_content_matches(self, tmp_path):
        """Filenames are wall-clock derived; the scenario must not be.

        Two things are deliberately excluded from the comparison, both because
        they are run-unique by design rather than part of the scenario:

        * the recording filename (derived from the wall clock), and
        * ``mission.current_task``, whose id comes from ``Task``'s
          **process-global** counter, so a second run in the same process gets
          ``task-0019`` rather than ``task-0016``.

        The task *type*, status and completion — i.e. the actual mission
        behaviour — must still match exactly.
        """
        a = self._run(tmp_path, "a")
        b = self._run(tmp_path, "b")
        fa = read_recording(os.path.join(str(tmp_path / "a"), a.recording_id))
        fb = read_recording(os.path.join(str(tmp_path / "b"), b.recording_id))

        def scenario(frames):
            return [(f.data["mission"]["current_task_type"],
                     f.data["mission"]["current_task_status"],
                     f.data["mission"]["completed_tasks"],
                     f.data["hazard_state"])
                    for f in frames]

        assert scenario(fa) == scenario(fb)
        assert [f.data["hazard_state"] for f in fa] == \
            [f.data["hazard_state"] for f in fb]


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #
class TestDemoSafety:
    def test_nothing_reached_physical_hardware(self, demo):
        result, _ = demo
        assert result.audit.physical_writes == 0

    def test_the_demo_issued_no_direct_actuator_command(self, demo):
        result, _ = demo
        assert result.audit.demo_command_calls == 0

    def test_every_wheel_command_went_through_the_manager_gate(self, demo):
        """The mission moved the *mock* robot only through RobotManager.move."""
        result, _ = demo
        assert result.audit.wheel_commands > 0
        assert result.audit.via_manager_gate == result.audit.wheel_commands

    def _demo_source(self) -> str:
        import pathlib

        import amr.demo as demo_mod
        return pathlib.Path(demo_mod.__file__).read_text(encoding="utf-8")

    def test_the_demo_module_has_no_http_command_path(self):
        # The demo must never reach the actuator endpoint or a GPIO/serial API.
        for banned in ("/command", "gpio", "serial.Serial", "RPi.GPIO"):
            assert banned not in self._demo_source()

    def test_no_extra_thread_or_timer_was_introduced(self):
        for banned in ("import threading", "Thread(", "time.sleep",
                       "setInterval", "while True"):
            assert banned not in self._demo_source()

    def test_the_demo_drives_the_single_existing_tick(self):
        """C15 added ``_tick_once``; there is still exactly one loop.

        The demo has to be able to step the *real* runtime work without adding a
        second loop, so the loop body became a method the demo can call. This
        pins that the refactor did not quietly create a second control path.
        """
        import inspect

        from amr.web.server import AMRWebApp
        src = inspect.getsource(AMRWebApp)
        assert src.count("def _control_loop") == 1
        assert src.count("self._stop_evt.wait(interval)") == 1
        # The per-iteration method is called by the loop, and by the demo.
        assert "self._tick_once(interval)" in inspect.getsource(
            AMRWebApp._control_loop)
        assert "_tick_once" in self._demo_source()


# --------------------------------------------------------------------------- #
# The two demo adapters
# --------------------------------------------------------------------------- #
class TestScriptedVisionDetector:
    def _detector(self, **kw):
        t = [1000.0]
        return ScriptedVisionDetector(lambda: t[0], **kw)

    def test_silent_outside_the_scripted_window(self):
        # The window is half-open: [from_step, to_step). At step 1 the
        # obstacle has not appeared yet.
        d = self._detector(from_step=2, to_step=4)
        d.advance()
        assert d.detect() == ()

    def test_emits_inside_the_window_and_stops_after(self):
        d = self._detector(from_step=2, to_step=4)
        for _ in range(2):
            d.advance()
        got = d.detect()
        assert len(got) == 1
        assert got[0].vision_class.value == "OBSTACLE"
        assert got[0].source == "camera_front"
        for _ in range(2):                 # now at step 4: past the window
            d.advance()
        assert d.detect() == ()

    def test_detection_has_a_bbox_and_no_world_location(self):
        """The adapter must not smuggle in a world coordinate."""
        d = self._detector(from_step=0, to_step=5)
        det = d.detect()[0]
        assert det.bbox is not None
        assert det.bbox.to_list() == tuple(float(v) for v in OBSTACLE_BBOX)
        assert det.location is None

    def test_is_deterministic(self):
        a = self._detector(from_step=0, to_step=3)
        b = self._detector(from_step=0, to_step=3)
        for _ in range(2):
            a.advance()
            b.advance()
        assert a.detect()[0] == b.detect()[0]


class TestSimulatedClearance:
    def test_returns_both_sides_open(self):
        assert SimulatedClearance()() == DEMO_CLEARANCE

    def test_returns_a_copy_not_the_shared_dict(self):
        c = SimulatedClearance()
        first = c()
        first["LEFT"] = 99.0
        assert c()["LEFT"] == DEMO_CLEARANCE["LEFT"]


class TestActuationAudit:
    def test_serialises_its_own_fields(self):
        audit = ActuationAudit(transport_writes=3, wheel_commands=2)
        d = audit.to_dict()
        assert d["transport_writes"] == 3 and d["wheel_commands"] == 2
        assert d["physical_writes"] == 0


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
class TestReport:
    def test_report_states_hardware_is_not_tested(self, demo):
        result, _ = demo
        text = format_report(result)
        assert "Hardware / firmware: NOT TESTED" in text
        assert "Result: PASS" in text

    def test_report_contains_no_placeholder_or_invented_values(self, demo):
        result, _ = demo
        text = format_report(result)
        assert "TODO" not in text and "FIXME" not in text
        assert "0.99" not in text          # no invented accuracy claim


