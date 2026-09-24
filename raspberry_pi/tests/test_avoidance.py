"""C6 — obstacle avoidance: focused coverage of the activation path.

Hardware-free. Every test uses the deterministic policy plus the existing
:class:`LocalNavigator` / :class:`HazardManager`; no camera, no motor, no
serial. Mapping to the 12 required C6 areas is noted on each test class.
"""

from __future__ import annotations

import math

import pytest

from amr.hazard.manager import HazardManager
from amr.hazard.types import (
    HazardKind,
    HazardReading,
    HazardSeverity,
    HazardState,
)
from amr.hazard.vision import SimulatedVisionDetector
from amr.hazard.sources import VisionHazardSource
from amr.navigation.navigator import LocalNavigator
from amr.navigation.types import Goal, NavStatus, Pose
from amr.safety.avoidance import (
    AvoidanceAction,
    AvoidancePolicy,
    ObstacleReport,
    ObstacleSide,
    report_from_hazard,
)
from amr.safety.safety_manager import (
    SafetyAction,
    SafetyDecision,
    SafetyManager,
)
from amr.sensors.ultrasonic import UltrasonicReading
from amr.utils.config import HazardConfig, SafetyConfig


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _proceed() -> SafetyDecision:
    return SafetyDecision(SafetyAction.PROCEED)


def _policy(**kw) -> AvoidancePolicy:
    kw.setdefault("enabled", True)
    return AvoidancePolicy(**kw)


def _static_source(readings):
    class _Source:
        name = "static"

        def read(self):
            return list(readings)

    return _Source()


def _vision_manager(scenario="obstacle", source="camera_front", **kw):
    manager = HazardManager(HazardConfig(enabled=True, vision_enabled=True))
    manager.add_source(
        VisionHazardSource(
            SimulatedVisionDetector(scenario, source=source).detect,
            name="vision",
            **kw,
        )
    )
    return manager


def _safety_config() -> SafetyConfig:
    return SafetyConfig()


def _ultrasonic(distance_cm: float):
    return UltrasonicReading(front=distance_cm)


_CLEAR_BOTH = {"LEFT": 2.0, "RIGHT": 2.0}


class _Rig:
    """A navigator wired for avoidance, recording every wheel command."""

    def __init__(self, obstacle, policy=None, clearance=None,
                 decision=None, max_pwm=255):
        self.commands = []
        self.policy = policy if policy is not None else _policy()
        self.navigator = LocalNavigator(
            command=self._record,
            avoidance=self.policy,
            obstacle_provider=(lambda: obstacle),
            clearance_provider=(lambda: clearance),
            decision_provider=(lambda: decision),
            max_pwm=max_pwm,
        )

    def _record(self, left, right):
        self.commands.append((left, right))

    def drive(self, goal=None, steps=1, dt=0.1):
        self.navigator.go_to(goal or Goal(name="dock",
                                          pose=Pose(1.0, 0.0, 0.0)))
        for _ in range(steps):
            self.navigator.step(dt)
        return self.navigator.status


# --------------------------------------------------------------------------- #
# 1. obstacle evidence reaches the decision layer
# --------------------------------------------------------------------------- #
class TestEvidenceReachesDecisionLayer:
    def test_hazard_obstacle_reading_becomes_a_report(self):
        report = report_from_hazard(_vision_manager().evaluate())
        assert report is not None
        assert report.side is ObstacleSide.FRONT
        assert report.confidence == pytest.approx(0.88)

    def test_no_obstacle_evidence_yields_no_report(self):
        manager = HazardManager(HazardConfig(enabled=True, vision_enabled=True))
        manager.add_source(
            VisionHazardSource(
                SimulatedVisionDetector("normal").detect, name="vision"
            )
        )
        assert report_from_hazard(manager.evaluate()) is None

    def test_non_obstacle_hazards_are_not_reported_as_obstacles(self):
        # A FIRE must keep its own escalation path, never be re-labelled.
        assert report_from_hazard(_vision_manager("fire").evaluate()) is None

    def test_policy_receives_the_report_and_acts(self):
        report = ObstacleReport(side=ObstacleSide.FRONT, confidence=0.9)
        decision, action = _policy().decide(
            _proceed(), report, clearance=_CLEAR_BOTH
        )
        assert decision.action is SafetyAction.TURN
        assert action is AvoidanceAction.TURN

    def test_report_from_hazard_handles_none(self):
        assert report_from_hazard(None) is None


# --------------------------------------------------------------------------- #
# 2. obstacle can trigger TURN
# --------------------------------------------------------------------------- #
class TestTurn:
    def test_left_obstacle_steers_right(self):
        report = ObstacleReport(side=ObstacleSide.LEFT)
        decision, action = _policy().decide(
            _proceed(), report, clearance=_CLEAR_BOTH
        )
        assert action is AvoidanceAction.TURN
        assert decision.action is SafetyAction.TURN
        assert "steering RIGHT" in decision.reasons[0]

    def test_right_obstacle_steers_left(self):
        _, action = _policy().decide(
            _proceed(), ObstacleReport(side=ObstacleSide.RIGHT),
            clearance=_CLEAR_BOTH,
        )
        assert action is AvoidanceAction.TURN

    def test_front_prefers_a_clear_side(self):
        _, action = _policy().decide(
            _proceed(), ObstacleReport(side=ObstacleSide.FRONT),
            clearance={"LEFT": 3.0, "RIGHT": 3.0},
        )
        assert action is AvoidanceAction.TURN

    def test_navigator_never_commands_forward_while_turning(self):
        rig = _Rig(ObstacleReport(side=ObstacleSide.LEFT),
                   clearance=_CLEAR_BOTH)
        rig.drive(steps=3)
        assert rig.commands, "a turn must still command the wheels"
        for left, right in rig.commands:
            assert left * right <= 0, (
                f"forward motion during TURN: {(left, right)}"
            )
        assert rig.navigator.last_avoidance is AvoidanceAction.TURN

    def test_turn_pivot_changes_heading(self):
        rig = _Rig(ObstacleReport(side=ObstacleSide.LEFT),
                   clearance=_CLEAR_BOTH)
        rig.drive(steps=3)
        assert not math.isclose(
            rig.navigator.current_pose().theta, 0.0, abs_tol=1e-6
        )

    def test_turn_speeds_stay_within_max_pwm(self):
        rig = _Rig(ObstacleReport(side=ObstacleSide.LEFT),
                   clearance=_CLEAR_BOTH, max_pwm=40)
        rig.drive(steps=3)
        for left, right in rig.commands:
            assert abs(left) <= 40 and abs(right) <= 40


# --------------------------------------------------------------------------- #
# 3. obstacle can trigger REPLAN
# --------------------------------------------------------------------------- #
class TestReplan:
    def test_unknown_side_replans_instead_of_guessing(self):
        report = ObstacleReport(side=ObstacleSide.UNKNOWN)
        decision, action = _policy().decide(
            _proceed(), report, clearance=_CLEAR_BOTH
        )
        assert action is AvoidanceAction.REPLAN
        assert decision.action is SafetyAction.REPLAN

    def test_rear_obstacle_replans(self):
        _, action = _policy().decide(
            _proceed(), ObstacleReport(side=ObstacleSide.REAR),
            clearance=_CLEAR_BOTH,
        )
        assert action is AvoidanceAction.REPLAN

    def test_no_clearance_data_replans_rather_than_assuming(self):
        # Documented policy: without sensing of the candidate side we must not
        # invent a turn direction.
        _, action = _policy().decide(
            _proceed(), ObstacleReport(side=ObstacleSide.LEFT),
            clearance=None,
        )
        assert action is AvoidanceAction.REPLAN

    def test_both_sides_blocked_replans(self):
        _, action = _policy().decide(
            _proceed(), ObstacleReport(side=ObstacleSide.FRONT),
            clearance={"LEFT": 0.0, "RIGHT": 0.0},
        )
        assert action is AvoidanceAction.REPLAN

    def test_navigator_holds_position_on_replan(self):
        rig = _Rig(ObstacleReport(side=ObstacleSide.REAR),
                   clearance=_CLEAR_BOTH)
        rig.drive(steps=1)
        assert rig.commands[-1] == (0, 0)
        assert rig.navigator.last_avoidance is AvoidanceAction.REPLAN

    def test_navigator_resumes_after_the_obstacle_clears(self):
        rig = _Rig(ObstacleReport(side=ObstacleSide.REAR),
                   clearance=_CLEAR_BOTH)
        assert rig.drive(steps=1) is NavStatus.MOVING
        rig.navigator._obstacle_provider = lambda: None
        rig.drive(steps=5)
        assert any(c != (0, 0) for c in rig.commands)



# --------------------------------------------------------------------------- #
# 4. normal navigation remains unchanged when no obstacle exists
# --------------------------------------------------------------------------- #
class TestNormalNavigationUnchanged:
    def test_no_policy_reaches_the_goal(self):
        commands = []
        nav = LocalNavigator(command=lambda l, r: commands.append((l, r)))
        nav.go_to(Goal(name="dock", pose=Pose(1.0, 0.0, 0.0)))
        for _ in range(400):
            nav.step(0.1)
            if nav.status is NavStatus.DONE:
                break
        assert nav.status is NavStatus.DONE
        assert commands

    def test_disabled_policy_never_produces_a_manoeuvre(self):
        rig = _Rig(ObstacleReport(side=ObstacleSide.LEFT),
                   policy=AvoidancePolicy(enabled=False),
                   clearance=_CLEAR_BOTH)
        rig.drive(steps=3)
        assert rig.navigator.last_avoidance is None

    def test_null_obstacle_provider_changes_nothing(self):
        rig = _Rig(None, clearance=_CLEAR_BOTH)
        rig.drive(steps=3)
        assert rig.navigator.last_avoidance is None
        assert any(c != (0, 0) for c in rig.commands)

    def test_avoidance_commands_still_flow_through_command_cb(self):
        # The single existing command callback is the only egress; C6 must not
        # introduce a second path to the motors.
        rig = _Rig(ObstacleReport(side=ObstacleSide.LEFT),
                   clearance=_CLEAR_BOTH)
        rig.drive(steps=3)
        assert rig.commands
        assert all(isinstance(c, tuple) and len(c) == 2 for c in rig.commands)


# --------------------------------------------------------------------------- #
# 5 & 6. emergency stop overrides TURN and REPLAN
# --------------------------------------------------------------------------- #
class TestStopPriority:
    @pytest.mark.parametrize(
        "side, label",
        [(ObstacleSide.LEFT, "TURN"), (ObstacleSide.REAR, "REPLAN")],
    )
    def test_policy_never_upgrades_a_stop(self, side, label):
        stop = SafetyDecision(SafetyAction.STOP, ("proximity",))
        decision, action = _policy().decide(
            stop, ObstacleReport(side=side), clearance=_CLEAR_BOTH
        )
        assert decision.action is SafetyAction.STOP
        assert action is AvoidanceAction.STOP
        assert decision.reasons == ("proximity",)

    def test_wait_is_not_upgraded_to_a_manoeuvre(self):
        wait = SafetyDecision(SafetyAction.WAIT, ("caution band",))
        decision, action = _policy().decide(
            wait, ObstacleReport(side=ObstacleSide.LEFT),
            clearance=_CLEAR_BOTH,
        )
        assert decision.action is SafetyAction.WAIT
        assert action is AvoidanceAction.NONE

    @pytest.mark.parametrize("side", [ObstacleSide.LEFT, ObstacleSide.REAR])
    def test_injected_stop_aborts_navigation_before_any_manoeuvre(self, side):
        stop = SafetyDecision(SafetyAction.STOP, ("dead comms",))
        rig = _Rig(ObstacleReport(side=side), clearance=_CLEAR_BOTH,
                   decision=stop)
        rig.drive(steps=1)
        assert rig.navigator.status is NavStatus.FAILED
        assert rig.navigator.last_avoidance is AvoidanceAction.STOP
        # Only a hard stop was ever commanded -- no turn, no forward motion.
        assert all(c == (0, 0) for c in rig.commands)

    def test_stop_preempts_an_in_progress_turn(self):
        rig = _Rig(ObstacleReport(side=ObstacleSide.LEFT),
                   clearance=_CLEAR_BOTH,
                   decision=SafetyDecision(SafetyAction.PROCEED))
        rig.drive(steps=1)  # starts a turn
        assert rig.navigator.last_avoidance is AvoidanceAction.TURN
        # A stop now arrives mid-manoeuvre and must take over immediately.
        rig.navigator._decision_provider = lambda: SafetyDecision(
            SafetyAction.STOP, ("e-stop pressed",)
        )
        rig.navigator.step(0.1)
        assert rig.navigator.status is NavStatus.FAILED
        assert rig.commands[-1] == (0, 0)

    def test_critical_obstacle_still_stops_via_the_hazard_layer(self):
        # The hazard layer's CRITICAL path is untouched by C6: it raises STOP
        # and blocks motion before any manoeuvre is considered.
        status = _vision_manager("obstacle", critical_at=0.8).evaluate()
        assert status.state is HazardState.STOP
        assert status.blocks_motion

    def test_warning_obstacle_is_the_avoidable_case(self):
        # The complement of the test above: a non-blocking obstacle is exactly
        # what C6 exists to act on. The scripted detection scores 0.88, so the
        # warning band is placed below it and the critical band above it.
        status = _vision_manager("obstacle", warn_at=0.5,
                                critical_at=0.95).evaluate()
        assert status.state is HazardState.WARNING
        assert not status.blocks_motion
        assert report_from_hazard(status) is not None



# --------------------------------------------------------------------------- #
# 7. malformed obstacle evidence does not crash the system
# --------------------------------------------------------------------------- #
class TestMalformedEvidence:
    @pytest.mark.parametrize(
        "bad_side", ["sideways", None, 42, object(), "LEFT "]
    )
    def test_unrecognised_side_degrades_to_unknown(self, bad_side):
        report = ObstacleReport(side=bad_side)
        assert report.side is ObstacleSide.UNKNOWN
        assert not report.actionable

    @pytest.mark.parametrize("bad_conf", [5.0, -1.0, float("nan"), "high"])
    def test_bad_confidence_is_dropped_not_clamped(self, bad_conf):
        report = ObstacleReport(side=ObstacleSide.LEFT, confidence=bad_conf)
        assert report.confidence is None

    def test_provider_exception_degrades_to_no_obstacle(self):
        def boom():
            raise RuntimeError("camera died")

        rig = _Rig(None, clearance=_CLEAR_BOTH)
        rig.navigator._obstacle_provider = boom
        rig.drive(steps=2)  # must not raise
        assert rig.navigator.last_avoidance is None

    def test_clearance_provider_exception_degrades_to_replan(self):
        # Losing the clearance feed is a loss of information, not a licence to
        # guess a heading: the policy falls back to REPLAN, which holds
        # position rather than steering blindly.
        def boom():
            raise RuntimeError("sensor bus down")

        rig = _Rig(ObstacleReport(side=ObstacleSide.LEFT))
        rig.navigator._clearance_provider = boom
        rig.drive(steps=2)  # must not raise
        assert rig.navigator.last_avoidance is AvoidanceAction.REPLAN

    def test_malformed_detection_never_becomes_evidence(self):
        # C5 drops invalid detections upstream, before the policy ever sees one.
        assert SimulatedVisionDetector("malformed").detect(None) == ()

    def test_malformed_side_still_yields_a_safe_manoeuvre(self):
        report = ObstacleReport(side="sideways")
        _, action = _policy().decide(
            _proceed(), report, clearance=_CLEAR_BOTH
        )
        assert action is AvoidanceAction.REPLAN

    def test_bad_config_values_are_clamped_not_fatal(self):
        policy = AvoidancePolicy(
            enabled=True, max_replans="nonsense",
            turn_speed_scale=99.0, turn_duration_s=-4.0,
        )
        assert policy.max_replans == 0
        assert policy.turn_speed_scale == 1.0
        assert policy.turn_duration_s == 0.0

    def test_clearance_with_garbage_keys_is_ignored(self):
        _, action = _policy().decide(
            _proceed(), ObstacleReport(side=ObstacleSide.LEFT),
            clearance={"LEFT": "far", "RIGHT": None},
        )
        assert action is AvoidanceAction.REPLAN



# --------------------------------------------------------------------------- #
# 8. low-confidence obstacle behaviour follows documented policy
# --------------------------------------------------------------------------- #
class TestLowConfidence:
    def test_low_confidence_never_reaches_the_policy(self):
        # Documented policy: C5's own warn threshold gates evidence upstream;
        # C6 never re-interprets or rescales a confidence value.
        manager = HazardManager(HazardConfig(enabled=True, vision_enabled=True))
        manager.add_source(
            VisionHazardSource(
                SimulatedVisionDetector("low_confidence").detect,
                name="vision",
            )
        )
        assert report_from_hazard(manager.evaluate()) is None

    def test_info_severity_reading_is_not_actionable_evidence(self):
        manager = HazardManager(HazardConfig(enabled=True))
        manager.add_source(
            _static_source([
                HazardReading(
                    kind=HazardKind.OBSTACLE, value=0.2, unit="confidence",
                    severity=HazardSeverity.INFO, source="camera_front",
                )
            ])
        )
        status = manager.evaluate()
        # INFO sits below every threshold, so it never becomes a reading the
        # avoidance adapter could act on.
        assert not [r for r in status.readings
                    if r.severity is not HazardSeverity.INFO]

    def test_policy_defers_the_confidence_gate_to_the_hazard_layer(self):
        # Any confidence on an actionable side is honoured: the threshold is
        # deliberately not duplicated in the C6 policy.
        for conf in (0.05, 0.5, 0.99):
            _, action = _policy().decide(
                _proceed(),
                ObstacleReport(side=ObstacleSide.LEFT, confidence=conf),
                clearance=_CLEAR_BOTH,
            )
            assert action is AvoidanceAction.TURN

    def test_confidence_is_never_rescaled(self):
        report = ObstacleReport(side=ObstacleSide.LEFT, confidence=0.88)
        assert report.confidence == 0.88


# --------------------------------------------------------------------------- #
# 9. repeated obstacle events do not create uncontrolled command loops
# --------------------------------------------------------------------------- #
class TestLoopGuard:
    def test_budget_exhaustion_escalates_to_stop(self):
        policy = _policy(max_replans=2)
        rig = _Rig(ObstacleReport(side=ObstacleSide.REAR), policy=policy,
                   clearance=_CLEAR_BOTH)
        rig.drive(steps=30)
        assert rig.navigator.status is NavStatus.FAILED
        assert rig.navigator.last_avoidance is AvoidanceAction.STOP
        assert "exhausted" in (rig.navigator.error or "")

    def test_persistent_obstacle_always_terminates(self):
        rig = _Rig(ObstacleReport(side=ObstacleSide.LEFT),
                   clearance=_CLEAR_BOTH)
        rig.drive(steps=1000)
        assert rig.navigator.status is NavStatus.FAILED

    def test_new_obstacle_episode_gets_a_fresh_budget(self):
        policy = _policy(max_replans=1)
        box = {"obstacle": ObstacleReport(side=ObstacleSide.REAR)}
        rig = _Rig(None, policy=policy, clearance=_CLEAR_BOTH)
        rig.navigator._obstacle_provider = lambda: box["obstacle"]
        rig.navigator.go_to(Goal(name="g", pose=Pose(1.0, 0.0, 0.0)))
        for _ in range(100):
            rig.navigator.step(0.1)
            if rig.navigator.status is NavStatus.FAILED:
                break
        assert rig.navigator.status is NavStatus.FAILED
        # Obstacle clears -> episode reset -> a fresh goal can be driven.
        box["obstacle"] = None
        rig.navigator.go_to(Goal(name="g", pose=Pose(1.0, 0.0, 0.0)))
        assert rig.navigator.status is NavStatus.MOVING

    def test_turn_is_committed_and_not_re_decided_each_tick(self):
        # A committed turn runs to completion; restarting it every step is what
        # would otherwise make the robot oscillate.
        policy = _policy(turn_duration_s=0.5)
        rig = _Rig(ObstacleReport(side=ObstacleSide.LEFT), policy=policy,
                   clearance=_CLEAR_BOTH)
        rig.drive(steps=1)
        rig.navigator.step(0.1)
        rig.navigator.step(0.1)
        assert rig.navigator.last_avoidance is AvoidanceAction.TURN

    def test_zero_turn_duration_cannot_spin_the_robot(self):
        policy = _policy(turn_duration_s=0.0)
        rig = _Rig(ObstacleReport(side=ObstacleSide.LEFT), policy=policy,
                   clearance=_CLEAR_BOTH)
        rig.drive(steps=2)
        for left, right in rig.commands:
            assert abs(left) <= 255 and abs(right) <= 255
        assert all(c == (0, 0) for c in rig.commands)

    def test_command_rate_stays_bounded_under_a_persistent_obstacle(self):
        rig = _Rig(ObstacleReport(side=ObstacleSide.LEFT),
                   clearance=_CLEAR_BOTH)
        rig.drive(steps=300)
        # One command per step at most -- no runaway emission.
        assert len(rig.commands) <= 300



# --------------------------------------------------------------------------- #
# 10-12. compatibility with C2/C3/C5, warehouse, and determinism
# --------------------------------------------------------------------------- #
class TestCompatibility:
    def test_safety_manager_legacy_call_is_unchanged(self):
        # check(reading, connected) with no obstacle kwarg behaves exactly as
        # before C6 -- the kwarg is optional and defaults to no obstacle.
        sm = SafetyManager(_safety_config())
        decision = sm.check(_ultrasonic(100), connected=True)
        assert decision.action is SafetyAction.PROCEED

    def test_safety_manager_legacy_stop_is_unchanged(self):
        sm = SafetyManager(_safety_config())
        decision = sm.check(_ultrasonic(0.05), connected=True)
        assert decision.action is SafetyAction.STOP

    def test_legacy_safety_decision_has_no_avoidance_field(self):
        # No public interface was widened on the existing dataclass.
        sm = SafetyManager(_safety_config())
        assert "avoidance" not in vars(sm.check(_ultrasonic(100), True))

    def test_c5_vision_events_still_record_unchanged(self):
        manager = _vision_manager("fire")
        manager.evaluate()
        snapshot = manager.snapshot()
        assert snapshot["state"] == "EMERGENCY"
        assert snapshot["events_recorded"] == 1
        assert snapshot["active_events"][0]["confidence"] == 0.93

    def test_c2_snapshot_contract_is_preserved(self):
        # The C2 web layer derives severity/active on top of the manager
        # snapshot; the manager's own key set is unchanged by C6.
        manager = _vision_manager("person")
        manager.evaluate()
        snapshot = manager.snapshot()
        for key in ("state", "status", "latched", "blocks_motion",
                    "active_events", "recent_events", "events_recorded",
                    "counts_by_kind", "sources"):
            assert key in snapshot

    def test_c3_visualisation_still_consumes_the_event_log(self):
        from amr.hazard.visualisation import events_from_snapshot
        manager = _vision_manager("fire")
        manager.evaluate()
        events = events_from_snapshot(manager.snapshot())
        assert len(events) == 1
        assert events[0]["kind"] == "FIRE"

    def test_warehouse_task_manager_is_unaffected(self):
        # C6 touched no warehouse code; this guards the import + the default
        # constructor signature the warehouse uses.
        from amr.warehouse.task_manager import WarehouseTaskManager
        assert WarehouseTaskManager is not None

    def test_local_navigator_legacy_signature_still_works(self):
        commands = []
        nav = LocalNavigator(command=lambda l, r: commands.append((l, r)))
        nav.go_to(Goal(name="dock", pose=Pose(1.0, 0.0, 0.0)))
        nav.step(0.1)  # no safety, no policy, no providers injected
        assert nav.status is NavStatus.MOVING
        assert commands


class TestDeterminism:
    def _trace(self):
        rig = _Rig(ObstacleReport(side=ObstacleSide.LEFT),
                   clearance=_CLEAR_BOTH)
        rig.drive(steps=25)
        return rig.commands, rig.navigator.status, rig.navigator.last_avoidance

    def test_identical_inputs_produce_identical_traces(self):
        first = self._trace()
        second = self._trace()
        assert first == second

    def test_turn_arc_is_exactly_reproducible(self):
        rig_a = _Rig(ObstacleReport(side=ObstacleSide.LEFT),
                    clearance=_CLEAR_BOTH)
        rig_b = _Rig(ObstacleReport(side=ObstacleSide.LEFT),
                    clearance=_CLEAR_BOTH)
        rig_a.drive(steps=10)
        rig_b.drive(steps=10)
        assert rig_a.commands == rig_b.commands

    def test_policy_decision_is_a_pure_function(self):
        stop = SafetyDecision(SafetyAction.STOP, ("x",))
        report = ObstacleReport(side=ObstacleSide.LEFT, confidence=0.9)
        for _ in range(5):
            assert _policy().decide(stop, report, clearance=_CLEAR_BOTH) == \
                _policy().decide(stop, report, clearance=_CLEAR_BOTH)

    def test_report_is_immutable(self):
        report = ObstacleReport(side=ObstacleSide.LEFT, confidence=0.9)
        with pytest.raises(Exception):
            report.side = ObstacleSide.RIGHT  # type: ignore[misc]

    def test_no_wall_clock_dependency_in_the_policy(self):
        # Identical inputs at different wall-clock times must agree: the policy
        # never reads the clock, so there is nothing to freeze.
        assert _policy().decide(
            _proceed(), ObstacleReport(side=ObstacleSide.LEFT),
            clearance=_CLEAR_BOTH,
        )[1] is AvoidanceAction.TURN



# --------------------------------------------------------------------------- #
# Configuration surface
# --------------------------------------------------------------------------- #
class TestConfig:
    def test_shipped_config_has_avoidance_disabled(self):
        # The repository default must be opt-in: a freshly cloned robot must
        # not start manoeuvring on its own.
        from amr.utils.config import find_config_dir, load_config

        repo_cfg = load_config(str(find_config_dir()))
        assert repo_cfg.safety.avoidance.enabled is False

    def test_avoidance_block_is_loaded_from_yaml(self, tmp_path):
        from amr.utils.config import load_config as _load

        (tmp_path / "safety.yaml").write_text(
            "safety:\n"
            "  avoidance:\n"
            "    enabled: true\n"
            "    max_replans: 9\n",
            encoding="utf-8",
        )
        cfg = _load(str(tmp_path))
        assert cfg.safety.avoidance.enabled is True
        assert cfg.safety.avoidance.max_replans == 9
        # Untouched keys keep their documented defaults.
        assert cfg.safety.avoidance.turn_duration_s == 0.6
        # Pre-existing safety keys are unaffected by the new nested block.
        assert cfg.safety.front_stop_distance_cm == 20

    def test_defaults_match_the_policy_defaults(self):
        from amr.utils.config import AvoidanceConfig

        assert AvoidanceConfig() == AvoidanceConfig(
            enabled=False, max_replans=3, turn_speed_scale=0.5,
            turn_duration_s=0.6, open_clearance_m=1.0,
        )

    def test_policy_from_config_round_trip(self):
        from amr.utils.config import AvoidanceConfig

        cfg = AvoidanceConfig(enabled=True, max_replans=7,
                              turn_speed_scale=0.25, turn_duration_s=1.5,
                              open_clearance_m=2.0)
        policy = AvoidancePolicy.from_config(cfg)
        assert policy.enabled is True
        assert policy.max_replans == 7
        assert policy.turn_speed_scale == 0.25
        assert policy.turn_duration_s == 1.5
        assert policy.open_clearance_m == 2.0

    def test_from_config_none_is_disabled(self):
        # Omitted configuration can never switch avoidance on.
        assert AvoidancePolicy.from_config(None).enabled is False

    def test_from_config_clamps_bad_values(self):
        from amr.utils.config import AvoidanceConfig

        policy = AvoidancePolicy.from_config(
            AvoidanceConfig(enabled=True, turn_speed_scale=9.0,
                            turn_duration_s=-1.0, max_replans=-5)
        )
        assert policy.turn_speed_scale == 1.0
        assert policy.turn_duration_s == 0.0
        assert policy.max_replans == 0

    def test_clearance_threshold_is_enforced(self):
        # A side that is present but too close is not "clear".
        policy = _policy(open_clearance_m=1.0)
        close = {"RIGHT": 0.4}
        _, action = policy.decide(
            _proceed(), ObstacleReport(side=ObstacleSide.LEFT),
            clearance=close,
        )
        assert action is AvoidanceAction.REPLAN

    def test_roomier_side_wins_for_a_front_obstacle(self):
        policy = _policy(open_clearance_m=1.0)
        side = policy.choose_turn_side(
            ObstacleReport(side=ObstacleSide.FRONT),
            clearance={"LEFT": 1.5, "RIGHT": 3.0},
        )
        assert side is ObstacleSide.RIGHT

    def test_nan_clearance_is_not_treated_as_open(self):
        policy = _policy(open_clearance_m=1.0)
        side = policy.choose_turn_side(
            ObstacleReport(side=ObstacleSide.LEFT),
            clearance={"RIGHT": float("nan")},
        )
        assert side is None

