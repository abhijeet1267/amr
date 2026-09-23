"""Web remote control (Phase 10).

Zero third-party dependencies (stdlib ``http.server``). All commands go
through the same safety-gated :class:`~amr.robot.robot_manager.RobotManager`
API used by the CLI — the web layer can be denied, never bypass.
"""

from .server import AMRWebApp

__all__ = ["AMRWebApp"]
