"""Mock motor driver for tests and mock mode.

Records the commanded speeds and never touches hardware. It satisfies the same
interface as a real :class:`~amr.control.motor_controller.MotorDriver` so the
differential-drive layer is testable offline.
"""

from __future__ import annotations

from typing import List, Tuple


class MockMotorDriver:
    """A no-op motor driver that records commands."""

    def __init__(self, max_speed: int = 255):
        self.max_speed = max_speed
        self.left = 0
        self.right = 0
        self.history: List[Tuple[int, int]] = []

    def set_speed(self, left: int, right: int) -> None:
        left = max(-self.max_speed, min(self.max_speed, int(left)))
        right = max(-self.max_speed, min(self.max_speed, int(right)))
        self.left = left
        self.right = right
        self.history.append((left, right))

    def stop(self) -> None:
        self.set_speed(0, 0)

    def is_enabled(self) -> bool:
        return True
