"""Web remote control (Phase 10).

Zero third-party dependencies (stdlib ``http.server``). All commands go
through the same safety-gated :class:`~amr.robot.robot_manager.RobotManager`
API used by the CLI — the web layer can be denied, never bypass.

Hazard surface (C2): ``GET /hazard`` reads ``HazardManager.snapshot()`` and
``POST /hazard/acknowledge`` performs only step 1 of the two-step emergency
release (the robot-mode reset stays on ``POST /command``).
"""

from .server import AMRWebApp

__all__ = ["AMRWebApp"]
