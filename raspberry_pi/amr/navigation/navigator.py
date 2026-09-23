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
from typing import Callable, List, Optional

from ..logging import get_logger
from .types import Goal, NavStatus, Pose, wrap_angle

#: Low-level wheel-speed command. ``command(left, right)`` with each value in
#: ``[-max_pwm, +max_pwm]`` (positive = forward).
CommandFn = Callable[[int, int], None]


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
        self.log.debug("nav goal '%s' at %s", goal.name, goal.pose.to_dict())
        return self._status

    def step(self, dt: float) -> NavStatus:
        if self._status is not NavStatus.MOVING or self._goal is None:
            return self._status
        if dt <= 0:
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

    # -- internals ----------------------------------------------------------- #
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
