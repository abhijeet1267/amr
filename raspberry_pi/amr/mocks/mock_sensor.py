"""Mock ultrasonic sensor for tests and mock mode.

Returns a programmable distance; can be set to ``None`` to simulate a
timeout / invalid reading (the safety layer must treat this as unsafe).
"""

from __future__ import annotations

from typing import Optional


class MockUltrasonicSensor:
    """A single virtual ultrasonic range reading (cm)."""

    def __init__(self, distance_cm: int = 100):
        self._distance = distance_cm

    def set_distance(self, distance_cm: Optional[int]) -> None:
        self._distance = distance_cm

    def read(self) -> Optional[int]:
        """Return the distance in cm, or ``None`` if the reading is invalid."""
        if self._distance is None:
            return None
        return int(self._distance)
