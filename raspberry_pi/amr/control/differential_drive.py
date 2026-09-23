"""High-level differential-drive motion.

A small, safety-aware motion vocabulary on top of any
:class:`~amr.control.motor_controller.MotorDriver`:

    drive = DifferentialDrive(driver, max_speed=150)
    drive.forward(100)
    drive.rotate_left(80)
    drive.stop()

Conventions
-----------
* positive = forward, negative = reverse (matches the serial protocol).
* Named-direction methods (``forward``/``backward``/``rotate_*``/``turn_*``)
  take a *magnitude* — the sign is implied by the name, so ``backward(-50)``
  still drives backwards.
* ``rotate_*`` = in-place rotation (differential drive).
* ``turn_*``   = arc turn (inner wheel stopped).
* Every speed is clamped to the instance ``max_speed`` (set it from a
  validated config value) **in addition to** any clamping in the driver.
* This layer does NOT read sensors — collision avoidance belongs to the
  safety manager (see docs/safety.md).
"""

from __future__ import annotations

from ..communication import protocol as P
from .motor_controller import MotorDriver


class DifferentialDrive:
    """Differential-drive motion API over a :class:`MotorDriver`."""

    def __init__(self, driver: MotorDriver, max_speed: int = 255):
        if not (1 <= max_speed <= P.MAX_SPEED):
            raise ValueError(f"max_speed {max_speed} out of range [1, {P.MAX_SPEED}]")
        self._driver = driver
        self._max_speed = int(max_speed)
        self._last = (0, 0)

    # --- accessors --------------------------------------------------------- #
    @property
    def driver(self) -> MotorDriver:
        return self._driver

    @property
    def max_speed(self) -> int:
        return self._max_speed

    @property
    def last_commanded(self) -> tuple:
        """The most recently commanded (left, right) wheel speeds."""
        return self._last

    # --- motion ------------------------------------------------------------ #
    def _mag(self, speed: int) -> int:
        """Positive magnitude clamped to ``max_speed``."""
        return min(abs(int(speed)), self._max_speed)

    def move(self, left: int, right: int) -> None:
        """Command raw left/right wheel speeds (clamped to ``±max_speed``)."""
        cl = max(-self._max_speed, min(self._max_speed, int(left)))
        cr = max(-self._max_speed, min(self._max_speed, int(right)))
        self._driver.set_speed(cl, cr)
        self._last = (cl, cr)

    def forward(self, speed: int = 100) -> None:
        s = self._mag(speed)
        self.move(s, s)

    def backward(self, speed: int = 100) -> None:
        s = self._mag(speed)
        self.move(-s, -s)

    def rotate_left(self, speed: int = 100) -> None:
        """In-place rotation to the left (right wheel forward, left reverse)."""
        s = self._mag(speed)
        self.move(-s, s)

    def rotate_right(self, speed: int = 100) -> None:
        """In-place rotation to the right (left wheel forward, right reverse)."""
        s = self._mag(speed)
        self.move(s, -s)

    def turn_left(self, speed: int = 80) -> None:
        """Arc turn left: left wheel stopped, right wheel forward."""
        s = self._mag(speed)
        self.move(0, s)

    def turn_right(self, speed: int = 80) -> None:
        """Arc turn right: right wheel stopped, left wheel forward."""
        s = self._mag(speed)
        self.move(s, 0)

    def stop(self) -> None:
        self._driver.stop()
        self._last = (0, 0)
