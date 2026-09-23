"""Tests for the navigation layer (Phase 12).

Covers the pure-Python geometry / goal types and the deterministic
:class:`~amr.navigation.LocalNavigator`:

* :mod:`amr.navigation.types` — ``wrap_angle`` / ``distance`` / ``Pose`` /
  ``Goal`` / ``NavStatus`` / ``NavResult``.
* :class:`~amr.navigation.Navigator` — the abstract contract the warehouse
  layer (Phase 16) programs against.
* :class:`~amr.navigation.LocalNavigator` — straight-line plan, unicycle
  control + self-odometry, arrival, cancellation, mid-motion safety veto,
  PWM clamping, and (crucially) *determinism*.

Every navigator is driven through a **mock** ``command(left, right)``
callable (a recorder), so the whole suite runs with no ROS and no hardware —
which is the point of the "mock-testable" deliverable.
"""

from __future__ import annotations

import math

import pytest

from amr.navigation import (
    Goal,
    LocalNavigator,
    NavResult,
    NavStatus,
    Navigator,
    Pose,
    distance,
    wrap_angle,
)


# =========================================================================== #
# types.py
# =========================================================================== #
class TestWrapAngle:
    def test_zero_is_zero(self):
        assert wrap_angle(0.0) == 0.0

    def test_full_turn_is_zero(self):
        assert math.isclose(wrap_angle(2 * math.pi), 0.0, abs_tol=1e-9)

    def test_in_range_is_identity(self):
        for a in (-1.0, -0.5, 0.0, 0.5, 1.0):
            assert wrap_angle(a) == pytest.approx(a)

    def test_result_stays_within_bounds(self):
        for a in (-4.0, -3.1, -1.0, 0.3, 2.0, 5.5, 9.0):
            w = wrap_angle(a)
            assert -math.pi <= w <= math.pi

    def test_collapses_multiple_turns(self):
        # 3*pi is one turn past pi -> both must agree after wrapping.
        assert math.isclose(
            wrap_angle(3 * math.pi), wrap_angle(math.pi), abs_tol=1e-9
        )

    def test_invariant_under_full_turn(self):
        # Adding a full revolution must not change the wrapped value.
        for a in (-1.0, 0.7, 2.4):
            assert wrap_angle(a) == pytest.approx(
                wrap_angle(a + 2 * math.pi), abs=1e-6
            )


class TestDistance:
    def test_three_four_five(self):
        assert distance(Pose(0, 0, 0), Pose(3, 4, 0)) == pytest.approx(5.0)

    def test_identical_poses_zero(self):
        p = Pose(1.0, 2.0, 0.5)
        assert distance(p, p) == 0.0

    def test_symmetric(self):
        a, b = Pose(0, 0, 0), Pose(1.5, -2.5, 1.0)
        assert distance(a, b) == pytest.approx(distance(b, a))

    def test_ignores_orientation(self):
        assert distance(Pose(0, 0, 0.0), Pose(0, 0, 1.57)) == 0.0


class TestPose:
    def test_defaults_to_origin(self):
        p = Pose()
        assert (p.x, p.y, p.theta) == (0.0, 0.0, 0.0)

    def test_frozen(self):
        p = Pose(1, 2, 3)
        with pytest.raises(AttributeError):
            p.x = 9  # type: ignore[misc]

    def test_to_from_dict_roundtrip(self):
        p = Pose(1.0, 2.0, 0.5)
        assert Pose.from_dict(p.to_dict()) == p

    def test_from_dict_defaults_missing_keys_to_zero(self):
        assert Pose.from_dict({}) == Pose(0.0, 0.0, 0.0)

    def test_from_dict_coerces_strings_to_float(self):
        p = Pose.from_dict({"x": "1.5", "y": "2", "theta": "0.25"})
        assert (p.x, p.y, p.theta) == (1.5, 2.0, 0.25)


class TestGoal:
    def test_fields(self):
        g = Goal(pose=Pose(1, 0, 0), name="dock")
        assert g.name == "dock"
        assert g.pose == Pose(1, 0, 0)

    def test_default_name(self):
        assert Goal(pose=Pose(0, 0, 0)).name == "goal"

    def test_named_classmethod(self):
        p = Pose(1, 1, 0.0)
        assert Goal.named("a", p) == Goal(pose=p, name="a")

    def test_frozen(self):
        g = Goal(pose=Pose(0, 0, 0), name="x")
        with pytest.raises(AttributeError):
            g.name = "y"  # type: ignore[misc]


class TestNavStatus:
    def test_members(self):
        assert {s.name for s in NavStatus} == {
            "IDLE", "MOVING", "DONE", "FAILED", "CANCELLED",
        }

    def test_is_str_enum(self):
        assert NavStatus.DONE == "DONE"
        assert NavStatus.DONE.value == "DONE"


class TestNavResult:
    def test_to_dict(self):
        r = NavResult(status=NavStatus.DONE, pose=Pose(1, 2, 3))
        assert r.to_dict() == {
            "status": "DONE",
            "pose": {"x": 1.0, "y": 2.0, "theta": 3.0},
            "error": None,
        }

    def test_error_preserved(self):
        r = NavResult(status=NavStatus.FAILED, pose=Pose(0, 0, 0), error="boom")
        assert r.to_dict()["error"] == "boom"


# =========================================================================== #
# navigator.py — helpers
# =========================================================================== #
class Recorder:
    """A mock ``command(left, right)`` that records every call it receives."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def __call__(self, left: int, right: int) -> None:
        self.calls.append((int(left), int(right)))

    def last(self) -> tuple[int, int]:
        return self.calls[-1] if self.calls else (0, 0)


def _nav(command, **kwargs) -> LocalNavigator:
    return LocalNavigator(command=command, **kwargs)


def _drive_to_done(nav: LocalNavigator, dt: float = 0.05, max_steps: int = 5000) -> None:
    """Step the navigator until it stops moving (DONE / FAILED / CANCELLED)."""
    for _ in range(max_steps):
        nav.step(dt)
        if nav.status is not NavStatus.MOVING:
            return


# =========================================================================== #
# Navigator (the Phase 12 interface)
# =========================================================================== #
class TestNavigatorInterface:
    def test_abstract_methods_raise(self):
        n = Navigator()
        with pytest.raises(NotImplementedError):
            n.current_pose()
        with pytest.raises(NotImplementedError):
            n.plan(Goal(pose=Pose(0, 0, 0)))
        with pytest.raises(NotImplementedError):
            n.go_to(Goal(pose=Pose(0, 0, 0)))
        with pytest.raises(NotImplementedError):
            n.step(0.05)
        with pytest.raises(NotImplementedError):
            n.cancel()

    def test_abstract_status_raises(self):
        with pytest.raises(NotImplementedError):
            _ = Navigator().status

    def test_local_navigator_is_a_navigator(self):
        assert isinstance(_nav(lambda l, r: None), Navigator)


# =========================================================================== #
# LocalNavigator — construction / initial state
# =========================================================================== #
class TestLocalNavigatorSetup:
    def test_default_pose_is_origin(self):
        assert _nav(lambda l, r: None).current_pose() == Pose(0.0, 0.0, 0.0)

    def test_custom_start_pose(self):
        nav = _nav(lambda l, r: None, start_pose=Pose(2.0, 3.0, 0.5))
        assert nav.current_pose() == Pose(2.0, 3.0, 0.5)

    def test_rejects_nonpositive_wheel_base(self):
        with pytest.raises(ValueError):
            _nav(lambda l, r: None, wheel_base_m=0.0)

    def test_rejects_nonpositive_linear_speed(self):
        with pytest.raises(ValueError):
            _nav(lambda l, r: None, max_linear_speed=0.0)

    def test_rejects_nonpositive_max_pwm(self):
        with pytest.raises(ValueError):
            _nav(lambda l, r: None, max_pwm=0)

    def test_initially_idle(self):
        nav = _nav(lambda l, r: None)
        assert nav.status is NavStatus.IDLE
        assert nav.is_moving is False
        assert nav.goal is None
        assert nav.error is None


# =========================================================================== #
# LocalNavigator — planning
# =========================================================================== #
class TestPlan:
    def test_straight_line(self):
        nav = _nav(lambda l, r: None, start_pose=Pose(0, 0, 0))
        path = nav.plan(Goal(pose=Pose(1.0, 0.0, 0.0), name="g"))
        assert path == [Pose(0, 0, 0), Pose(1.0, 0.0, 0.0)]

    def test_plan_starts_at_current_pose(self):
        nav = _nav(lambda l, r: None, start_pose=Pose(0.5, 0.5, 0.0))
        assert nav.plan(Goal(pose=Pose(0, 0, 0)))[0] == Pose(0.5, 0.5, 0.0)


# =========================================================================== #
# LocalNavigator — driving to a goal
# =========================================================================== #
class TestDriveToGoal:
    def test_reaches_goal_and_stops(self):
        rec = Recorder()
        nav = _nav(rec, start_pose=Pose(0, 0, 0))
        nav.go_to(Goal(pose=Pose(1.0, 0.0, 0.0), name="g"))
        assert nav.status is NavStatus.MOVING
        assert nav.is_moving is True
        _drive_to_done(nav)
        assert nav.status is NavStatus.DONE
        assert nav.is_moving is False
        assert distance(nav.current_pose(), Pose(1.0, 0.0, 0.0)) <= 0.05 + 1e-6
        assert rec.last() == (0, 0)

    def test_facing_away_reverses_and_arrives(self):
        # Starts at +x pointing +x, but the goal is behind it (at the origin).
        rec = Recorder()
        nav = _nav(rec, start_pose=Pose(1.0, 0.0, 0.0))
        nav.go_to(Goal(pose=Pose(0.0, 0.0, 0.0), name="back"))
        _drive_to_done(nav)
        assert nav.status is NavStatus.DONE
        assert distance(nav.current_pose(), Pose(0, 0, 0)) <= 0.05 + 1e-6

    def test_diagonal_goal(self):
        nav = _nav(lambda l, r: None, start_pose=Pose(0, 0, 0))
        nav.go_to(Goal(pose=Pose(1.0, 1.0, math.pi / 4), name="diag"))
        _drive_to_done(nav)
        assert nav.status is NavStatus.DONE
        p = nav.current_pose()
        assert math.isclose(p.x, 1.0, abs_tol=0.06)
        assert math.isclose(p.y, 1.0, abs_tol=0.06)

    def test_already_at_goal_done_on_first_step(self):
        rec = Recorder()
        nav = _nav(rec, start_pose=Pose(1.0, 0.0, 0.0))
        nav.go_to(Goal(pose=Pose(1.0, 0.0, 0.0), name="here"))
        nav.step(0.05)
        assert nav.status is NavStatus.DONE
        assert rec.last() == (0, 0)

    def test_goal_property_reflects_active_goal(self):
        nav = _nav(lambda l, r: None)
        g = Goal(pose=Pose(1, 1, 0.0), name="shelf_a")
        nav.go_to(g)
        assert nav.goal is g


# =========================================================================== #
# LocalNavigator — odometry & determinism
# =========================================================================== #
class TestOdometryAndDeterminism:
    def test_pose_advances_forward(self):
        nav = _nav(lambda l, r: None, start_pose=Pose(0, 0, 0))
        nav.go_to(Goal(pose=Pose(1.0, 0.0, 0.0)))
        nav.step(0.1)
        assert nav.current_pose().x > 0.0

    def test_deterministic_command_sequence(self):
        # Identical initial conditions must yield identical command streams.
        r1, r2 = Recorder(), Recorder()
        for rec in (r1, r2):
            n = _nav(rec, start_pose=Pose(0, 0, 0))
            n.go_to(Goal(pose=Pose(1.2, 0.3, 0.3), name="g"))
            _drive_to_done(n)
        assert r1.calls == r2.calls
        assert len(r1.calls) > 0


# =========================================================================== #
# LocalNavigator — PWM clamping
# =========================================================================== #
class TestPwmClamping:
    def test_commands_stay_within_max_pwm(self):
        rec = Recorder()
        nav = _nav(
            rec,
            start_pose=Pose(0, 0, 0),
            max_linear_speed=0.5,
            max_angular_speed=1.0,
            max_pwm=100,
        )
        nav.go_to(Goal(pose=Pose(2.0, 0.0, 0.0), name="far"))
        _drive_to_done(nav)
        assert len(rec.calls) > 0
        for left, right in rec.calls:
            assert -100 <= left <= 100
            assert -100 <= right <= 100

    def test_some_nonzero_command_was_issued(self):
        rec = Recorder()
        nav = _nav(rec, start_pose=Pose(0, 0, 0))
        nav.go_to(Goal(pose=Pose(2.0, 0.0, 0.0), name="far"))
        _drive_to_done(nav)
        assert any(l != 0 or r != 0 for l, r in rec.calls)


# =========================================================================== #
# LocalNavigator — cancellation
# =========================================================================== #
class TestCancel:
    def test_cancel_while_moving_stops_the_robot(self):
        rec = Recorder()
        nav = _nav(rec, start_pose=Pose(0, 0, 0))
        nav.go_to(Goal(pose=Pose(5.0, 0.0, 0.0)))
        nav.step(0.05)
        nav.cancel()
        assert nav.status is NavStatus.CANCELLED
        assert nav.is_moving is False
        assert rec.last() == (0, 0)  # emergency stop

    def test_cancel_when_idle_stays_idle_but_stops(self):
        # cancel() is a defensive "ensure the robot is stopped" even when it
        # is not currently moving.
        rec = Recorder()
        nav = _nav(rec)
        nav.cancel()
        assert nav.status is NavStatus.IDLE
        assert rec.last() == (0, 0)

    def test_step_after_cancel_does_not_move(self):
        nav = _nav(lambda l, r: None, start_pose=Pose(0, 0, 0))
        nav.go_to(Goal(pose=Pose(5.0, 0.0, 0.0)))
        nav.cancel()
        before = nav.current_pose()
        assert nav.step(0.1) is NavStatus.CANCELLED
        assert nav.current_pose() == before


# =========================================================================== #
# LocalNavigator — mid-motion safety veto
# =========================================================================== #
class TestSafetyVeto:
    def test_command_veto_fails_navigation(self):
        stops: list[tuple[int, int]] = []

        def veto(left: int, right: int) -> None:
            stops.append((left, right))
            if left != 0 or right != 0:
                raise RuntimeError("SAFETY STOP")

        nav = _nav(veto, start_pose=Pose(0, 0, 0))
        nav.go_to(Goal(pose=Pose(1.0, 0.0, 0.0)))
        nav.step(0.05)
        assert nav.status is NavStatus.FAILED
        assert nav.is_moving is False
        assert "SAFETY STOP" in nav.error
        # an emergency stop was issued as the last command
        assert stops[-1] == (0, 0)

    def test_step_after_failed_is_a_noop(self):
        def veto(left: int, right: int) -> None:
            raise RuntimeError("stop")

        nav = _nav(veto, start_pose=Pose(0, 0, 0))
        nav.go_to(Goal(pose=Pose(1.0, 0.0, 0.0)))
        nav.step(0.05)
        before = nav.current_pose()
        assert nav.step(0.05) is NavStatus.FAILED
        assert nav.current_pose() == before


# =========================================================================== #
# LocalNavigator — step guards
# =========================================================================== #
class TestStepGuards:
    def test_step_while_idle_returns_idle(self):
        nav = _nav(lambda l, r: None)
        assert nav.step(0.05) is NavStatus.IDLE

    def test_nonpositive_dt_does_not_move_or_command(self):
        rec = Recorder()
        nav = _nav(rec, start_pose=Pose(0, 0, 0))
        nav.go_to(Goal(pose=Pose(1.0, 0.0, 0.0)))
        nav.step(0.0)
        nav.step(-1.0)
        assert nav.current_pose() == Pose(0, 0, 0)
        assert rec.calls == []
        assert nav.status is NavStatus.MOVING
