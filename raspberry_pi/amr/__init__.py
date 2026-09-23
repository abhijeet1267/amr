"""AMR (Autonomous Mobile Robot) smart-warehouse platform — Raspberry Pi side.

This package contains the high-level robot software stack. It is designed to run
in two modes:

* **Hardware mode** — talks to the Arduino UNO over USB serial to drive the
  motors and read the ultrasonic sensors.
* **Mock mode** — runs the entire high-level stack against in-process mocks
  (``amr.mocks``) so development and testing work with no robot attached.

Layers (bottom to top):
    communication -> control -> safety -> sensors -> robot -> camera/vision
    -> navigation -> warehouse

Nothing in this package should require pyserial, OpenCV or ROS to *import*;
those are optional and imported lazily where needed.
"""

__version__ = "0.1.0"
