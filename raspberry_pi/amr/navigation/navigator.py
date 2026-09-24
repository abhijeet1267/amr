"""Navigator interface + a deterministic local implementation (Phase 12).

The *interface* (:class:`Navigator`) is the contract the warehouse layer
(Phase 16) programs against. The concrete :class:`LocalNavigator` is a
self-contained, deterministic local planner/controller that:

* keeps its own unicycle odometry (start pose + integration of the commanded
  body velocities);
* drives the robot through a low-level ``command(left, right)`` callable — in
  the real stack that is :meth:`amr.robot.RobotManager.move`, so **every**
  command still passes the Layer-3 safety gate; the navigator never bypasses
  safety;
* reports arrival, failure (a mid-motion safety veto), and cancellation.

It is deliberately **not** a SLAM/Nav2 stack: global planning and
localisation live on the ROS side (see ``ros2/amr_navigation``). This module
provides the deterministic Python counterpart so the entire stack runs and is
unit-tested with no ROS and no hardware. The ROS bridge node implements the
same :class:`Navigator` contract backed by Nav2.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional

from ..logging import get_logger
from ..safety.avoidance import (
    AvoidanceAction,
    AvoidancePolicy,
    ObstacleReport,
)
from ..safety.safety_manager import SafetyAction, SafetyDecision
from .types import Goal, NavStatus, Pose, wrap_angle

#: Low-level wheel-speed command. ``command(left, right)`` with each value in
#: ``[-max_pwm, +max_pwm]`` (positive = forward).
CommandFn = Callable[[int, int], None]

#: C6 hooks. ``obstacle_provider`` returns the current obstacle evidence (or
#: ``None``); ``clearance_provider`` returns free distance per body-frame side
#: (``{"LEFT": m, "RIGHT": m}``); ``decision_provider`` lets a supervisor inject
#: an already-made :class:`SafetyDecision` so Layer 3 can veto the navigator.
ObstacleProvider = Callable[[], Optional[ObstacleReport]]
ClearanceProvider = Callable[[], Optional[Dict[str, float]]]
DecisionProvider = Callable[[], Optional[SafetyDecision]]


class Navigator:
    """Abstract navigation contract (the Phase 12 *interface*)."""

    def current_pose(self) -> Pose:
        """Current estimated pose (world frame)."""
        raise NotImplementedError

    def plan(self, goal: Goal) -> List[Pose]:
        """Return the planned path to ``goal`` as a list of poses."""
        raise NotImplementedError

    def go_to(self, goal: Goal) -> NavStatus:
        """Begin navigating to ``goal``. Non-blocking: drive with :meth:`step`."""
        raise NotImplementedError

    def step(self, dt: float) -> NavStatus:
        """Advance planning/control + odometry by ``dt`` seconds."""
        raise NotImplementedError

    def cancel(self) -> None:
        """Cancel the active goal and stop the robot."""
        raise NotImplementedError

    @property
    def status(self) -> NavStatus:
        raise NotImplementedError

    @property
    def is_moving(self) -> bool:
        return self.status is NavStatus.MOVING


class LocalNavigator(Navigator):
    """Deterministic unicycle goal controller with self-odometry.

    Parameters mirror the physical constants that :class:`RobotConfig` leaves
    as ``None`` until measured; pass the measured values once available.
    """

    def __init__(
        self,
        command: CommandFn,
        start_pose: Optional[Pose] = None,
        wheel_base_m: float = 0.30,
        max_linear_speed: float = 0.5,
        max_angular_speed: float = 1.0,
        max_pwm: int = 255,
        kp_linear: float = 1.0,
        kp_angular: float = 1.5,
        arrival_dist: float = 0.05,
        arrival_ang: float = 0.10,
        avoidance: Optional[AvoidancePolicy] = None,
        obstacle_provider: Optional[ObstacleProvider] = None,
        clearance_provider: Optional[ClearanceProvider] = None,
        decision_provider: Optional[DecisionProvider] = None,
    ):
        if wheel_base_m <= 0:
            raise ValueError("wheel_base_m must be > 0")
        if max_linear_speed <= 0:
            raise ValueError("max_linear_speed must be > 0")
        if max_pwm < 1:
            raise ValueError("max_pwm must be >= 1")

        self._command = command
        self._pose = start_pose if start_pose is not None else Pose(0.0, 0.0, 0.0)
        self._wheel_base = float(wheel_base_m)
        self._vmax = float(max_linear_speed)
        self._wmax = float(max_angular_speed)
        self._max_pwm = int(max_pwm)
        self._kpl = float(kp_linear)
        self._kpa = float(kp_angular)
        self._arr_dist = float(arrival_dist)
        self._arr_ang = float(arrival_ang)

        self._goal: Optional[Goal] = None
        self._status = NavStatus.IDLE
        self._error: Optional[str] = None
        self.log = get_logger("nav")

        # -- C6 obstacle avoidance (all inert unless explicitly injected) ----
        # ``_avoidance=None`` (the default) leaves behaviour byte-identical to
        # before C6: no provider is called, no decision is made.
        self._avoidance = avoidance
        self._obstacle_provider = obstacle_provider
        self._clearance_provider = clearance_provider
        self._decision_provider = decision_provider
        # Attempts already spent on the *current* obstacle episode. Reset when
        # the obstacle disappears, so a new obstacle gets a fresh budget while
        # one persistent obstacle cannot loop forever.
        self._replans_used = 0
        # Remaining seconds of an in-progress TURN arc.
        self._turn_left_s = 0.0
        self._turn_sign = 0.0
        #: Last avoidance verdict, exposed for the dashboard / tests.
        self.last_avoidance: Optional[AvoidanceAction] = None

    # -- Navigator interface ------------------------------------------------ #
    def current_pose(self) -> Pose:
        return self._pose

    def plan(self, goal: Goal) -> List[Pose]:
        """Straight-line (start -> goal) plan: the local default."""
        return [self._pose, goal.pose]

    def go_to(self, goal: Goal) -> NavStatus:
        self._goal = goal
        self._error = None
        self._status = NavStatus.MOVING
        self._reset_avoidance()
        self.log.debug("nav goal '%s' at %s", goal.name, goal.pose.to_dict())
        return self._status

    def step(self, dt: float) -> NavStatus:
        if self._status is not NavStatus.MOVING or self._goal is None:
            return self._status
        if dt <= 0:
            return self._status

        # ---- C6: Layer-3 / obstacle-avoidance gate (highest priority first) ----
        # Runs *before* any control law and can only ever reduce motion. The
        # resulting wheel commands still go through ``self._command`` — the
        # same gate to ``RobotManager.move`` used before C6 — so this adds no
        # new path to the motors.
        if self._apply_avoidance(dt):
            return self._status

        p = self._pose
        g = self._goal.pose
        dx = g.x - p.x
        dy = g.y - p.y
        dist = math.hypot(dx, dy)
        err = wrap_angle(math.atan2(dy, dx) - p.theta)

        # Arrival.
        if dist < self._arr_dist and abs(err) < self._arr_ang:
            self._command(0, 0)
            self._status = NavStatus.DONE
            return self._status

        # Proportional unicycle controller (reverses when facing away).
        sign = 1.0 if math.cos(err) >= 0.0 else -1.0
        v = sign * min(self._kpl * dist, self._vmax)
        w = max(-self._wmax, min(self._wmax, self._kpa * err))

        # Body (v, w) -> per-wheel speeds -> PWM duty.
        left_pwm = self._pwm(v - w * self._wheel_base / 2.0)
        right_pwm = self._pwm(v + w * self._wheel_base / 2.0)

        try:
            self._command(left_pwm, right_pwm)
        except Exception as exc:  # noqa: BLE001 - safety/mode veto mid-motion
            self._emergency_stop()
            self._status = NavStatus.FAILED
            self._error = str(exc)
            return self._status

        # Integrate odometry (ideal unicycle, driven by commanded v, w).
        x = p.x + math.cos(p.theta) * v * dt
        y = p.y + math.sin(p.theta) * v * dt
        theta = wrap_angle(p.theta + w * dt)
        self._pose = Pose(x, y, theta)
        return self._status

    def cancel(self) -> None:
        if self._status is NavStatus.MOVING:
            self._status = NavStatus.CANCELLED
        self._emergency_stop()

    @property
    def status(self) -> NavStatus:
        return self._status

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def goal(self) -> Optional[Goal]:
        return self._goal

    # -- C6 obstacle avoidance ---------------------------------------------- #
    def _reset_avoidance(self) -> None:
        """Clear the per-goal avoidance state (called on go_to / cancel)."""
        self._replans_used = 0
        self._turn_left_s = 0.0
        self._turn_sign = 0.0
        self.last_avoidance = None

    def _apply_avoidance(self, dt: float) -> bool:
        """Run the C6 gate. ``True`` means "handled; skip the control law".

        Order is strict and is the whole safety argument:

        1. A supervisor-injected Layer-3 ``STOP`` (dead comms / no data / E-STOP)
           wins outright — TURN and REPLAN are never even considered.
        2. An in-progress TURN arc is completed first, so a turn is never
           interrupted half-way and re-decided (which would oscillate).
        3. Otherwise the policy decides between TURN, REPLAN and proceed.
        """
        policy = self._avoidance
        if policy is None:
            return False

        # 1. Layer-3 veto has absolute priority over every manoeuvre.
        injected = self._safe_call(self._decision_provider)
        if injected is not None and injected.action is SafetyAction.STOP:
            self.last_avoidance = AvoidanceAction.STOP
            self._command_safe(0, 0)
            self._status = NavStatus.FAILED
            self._error = "; ".join(injected.reasons) or "safety stop"
            self.log.warning("nav aborted by safety: %s", self._error)
            return True

        # An obstacle that has vanished ends the episode and frees the budget.
        obstacle = self._safe_call(self._obstacle_provider)
        if obstacle is None:
            self._replans_used = 0
            self.last_avoidance = None
            return False

        # 2. Finish a committed turn before re-deciding.
        if self._turn_left_s > 0.0:
            self._command_turn(min(dt, self._turn_left_s))
            self._turn_left_s -= dt
            if self._turn_left_s <= 0.0:
                self._turn_left_s = 0.0
            return True

        # 3. Ask the policy (pure).
        clearance = self._safe_call(self._clearance_provider)
        report = ObstacleReport(
            side=obstacle.side,
            confidence=obstacle.confidence,
            source=obstacle.source,
            exhausted=(
                obstacle.exhausted
                or self._replans_used >= policy.max_replans
            ),
        )
        base = SafetyDecision(SafetyAction.PROCEED)
        decision, action = policy.decide(base, report, clearance=clearance)

        if action is AvoidanceAction.STOP:
            # Loop guard fired: the obstacle is still there after the whole
            # budget. Stop rather than oscillate. The operator clears this.
            self.last_avoidance = AvoidanceAction.STOP
            self._command_safe(0, 0)
            self._status = NavStatus.FAILED
            self._error = "; ".join(decision.reasons)
            self.log.warning("nav stopped: %s", self._error)
            return True

        if action is AvoidanceAction.TURN:
            side = policy.choose_turn_side(report, clearance=clearance)
            if side is not None:
                self.last_avoidance = AvoidanceAction.TURN
                self._replans_used += 1
                # LEFT obstacle -> steer RIGHT (and vice versa).
                self._turn_sign = -1.0 if side.value == "RIGHT" else 1.0
                self._turn_left_s = policy.turn_duration_s
                self._command_turn(min(dt, self._turn_left_s))
                self._turn_left_s -= dt
                if self._turn_left_s <= 0.0:
                    self._turn_left_s = 0.0
                self.log.info(
                    "nav avoiding obstacle: %s", "; ".join(decision.reasons)
                )
                return True

        if action is AvoidanceAction.REPLAN:
            self.last_avoidance = AvoidanceAction.REPLAN
            self._replans_used += 1
            # Re-plan in place: hold position this tick, then resume the
            # existing straight-line controller against the same goal.
            self._command_safe(0, 0)
            self.log.info("nav replanning: %s", "; ".join(decision.reasons))
            return True

        self.last_avoidance = None
        return False

    def _command_turn(self, duration: float) -> None:
        """Command a bounded avoidance arc for ``duration`` seconds.

        The wheels counter-rotate, so the robot pivots away from the obstacle.
        Speeds are scaled by ``turn_speed_scale`` and still clamped to
        ``max_pwm``; a veto from ``self._command`` is handled exactly as in the
        normal control path.
        """
        scale = self._avoidance.turn_speed_scale
        if duration <= 0.0 or scale <= 0.0:
            self._command_safe(0, 0)
            return
        w = self._turn_sign * self._wmax * scale
        half = w * self._wheel_base / 2.0
        try:
            self._command(self._pwm(-half), self._pwm(half))
        except Exception as exc:  # noqa: BLE001 - safety/mode veto mid-turn
            self._emergency_stop()
            self._status = NavStatus.FAILED
            self._error = str(exc)
        # Odometry still advances so the pose stays coherent with the manoeuvre.
        if self._status is NavStatus.MOVING:
            p = self._pose
            self._pose = Pose(p.x, p.y, wrap_angle(p.theta + w * duration))

    def _command_safe(self, left: int, right: int) -> None:
        """Command a halt, absorbing vetoes (a stop must always be delivered)."""
        try:
            self._command(left, right)
        except Exception:  # noqa: BLE001 - never let a stop raise
            pass

    @staticmethod
    def _safe_call(fn):
        """Call a provider, degrading to ``None`` if it is missing or raises.

        Perception or planning code must never be able to crash the control
        loop; a failed provider simply yields "no information", which the
        policy treats conservatively.
        """
        if fn is None:
            return None
        try:
            return fn()
        except Exception:  # noqa: BLE001 - provider failure is not fatal
            return None

    def _pwm(self, wheel_speed_mps: float) -> int:
        """Map a physical wheel speed (m/s) to a clamped integer PWM duty."""
        ratio = (wheel_speed_mps / self._vmax) * self._max_pwm
        val = int(round(ratio))
        return max(-self._max_pwm, min(self._max_pwm, val))

    def _emergency_stop(self) -> None:
        try:
            self._command(0, 0)
        except Exception:  # noqa: BLE001 - never let a stop raise
            pass
