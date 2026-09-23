"""Motor / drive control layer.

* :mod:`amr.control.motor_controller` — the :class:`MotorDriver` abstraction and
  its :class:`ArduinoMotorDriver` implementation.
* :mod:`amr.control.differential_drive` — high-level differential-drive motion.

High-level code (navigation, warehouse, web) talks to
:class:`~amr.control.differential_drive.DifferentialDrive`, never to pins or
raw serial.
"""

from .motor_controller import (
    MotorDriver,
    ArduinoMotorDriver,
    clamp_speed,
)
from .differential_drive import DifferentialDrive

__all__ = [
    "MotorDriver",
    "ArduinoMotorDriver",
    "clamp_speed",
    "DifferentialDrive",
]
