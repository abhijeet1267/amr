"""Ultrasonic sensing (Pi side).

On the Pi there are no ultrasonic pins — the sensors are wired to the
Arduino (pins in ``config/robot.yaml`` are ``TODO_VERIFY``). The Pi-side
manager therefore talks to the controller over the ``SENSOR`` command and
validates/normalises the readings:

* ``-1`` (no echo) or anything outside
  ``[sensor_min_valid_cm, sensor_max_valid_cm]`` is treated as an
  *invalid* reading and stored as ``None``.
* An invalid reading for one direction does NOT stop the robot (a clear
  path is not an obstacle — see docs/safety.md Layer 1); the safety manager
  decides what a *complete loss* of valid data means.
"""

from .ultrasonic import UltrasonicManager, UltrasonicReading

__all__ = ["UltrasonicManager", "UltrasonicReading"]
