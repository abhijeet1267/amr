"""Pytest configuration and shared fixtures.

Ensures the ``amr`` package is importable no matter where pytest is launched
from, and exposes the repo root / config dir to tests.
"""

from __future__ import annotations

import pathlib
import sys

# .../IDP/raspberry_pi/tests/conftest.py
_RASPBERRY_PI = pathlib.Path(__file__).resolve().parents[1]
_REPO_ROOT = _RASPBERRY_PI.parent

if str(_RASPBERRY_PI) not in sys.path:
    sys.path.insert(0, str(_RASPBERRY_PI))

import pytest  # noqa: E402


@pytest.fixture
def repo_root() -> pathlib.Path:
    return _REPO_ROOT


@pytest.fixture
def config_dir() -> pathlib.Path:
    return _REPO_ROOT / "config"


# --------------------------------------------------------------------------- #
# Read-only (no-actuation) assertions
# --------------------------------------------------------------------------- #
#: Protocol verbs that actually command an actuator. The mock transport records
#: every line written to the controller, including the control loop's own
#: periodic ``PING`` / ``VERSION`` / ``SENSOR`` polls, which run on a background
#: thread. Asserting that the *total* line count is unchanged is therefore
#: inherently racy: it fails whenever a background poll happens to land inside
#: the measurement window, regardless of what the code under test did.
#:
#: The property the tests actually care about is "this read path cannot command
#: the robot". So we assert on the actuator verbs specifically, which is both
#: deterministic and a *stronger* guarantee: it would still catch a read path
#: that somehow issued ``MOVE``, even if background traffic doubled.
ACTUATION_VERBS = ("MOVE", "STOP")


def actuation_lines(transport) -> list:
    """Every actuator-commanding line recorded by a mock transport so far."""
    return [ln for ln in transport.written
            if str(ln).split(" ", 1)[0] in ACTUATION_VERBS]


class NoActuation:
    """Context manager asserting a block of code cannot command the robot.

    Usage::

        with NoActuation(mgr.test_transport):
            _get(port, "/map")

    It records how many lines the transport has seen on entry and checks that
    nothing appended during the block is an actuator command. Background
    ``PING`` / ``VERSION`` / ``SENSOR`` polls from the control loop are ignored
    on purpose — they are the runtime's own periodic traffic, not the effect of
    the code under test, and counting them makes the assertion racy under load.
    """

    def __init__(self, transport):
        self._transport = transport
        self._mark = 0
        self.new_lines: list = []

    def __enter__(self) -> "NoActuation":
        self._mark = len(self._transport.written)
        return self

    def __exit__(self, *exc) -> None:
        self.new_lines = list(self._transport.written[self._mark:])
        offenders = [ln for ln in self.new_lines
                     if str(ln).split(" ", 1)[0] in ACTUATION_VERBS]
        assert not offenders, (
            "read path issued actuator command(s) to the controller: "
            f"{offenders}")


# --------------------------------------------------------------------------- #
# Shared web-app fixtures
#
# C15c moved these here from test_web_server.py so the Command Center tests can
# exercise the *same* running app rather than building a second one. A single
# fixture means both suites assert against identical wiring.
# --------------------------------------------------------------------------- #
@pytest.fixture
def web(config_dir):
    """A running web app + mock robot, with a mock camera attached."""
    from amr.camera import CameraManager
    from amr.mocks import MockCamera
    from amr.robot import RobotManager
    from amr.utils.config import CameraConfig, load_config
    from amr.web import AMRWebApp

    config = load_config(config_dir)
    mgr, transport = RobotManager.create_mock(config)
    camera = CameraManager(MockCamera(available=True), CameraConfig(enabled=True))
    # The mock transport records every line written to the controller, so the
    # read-only tests can prove a GET never reaches an actuator.
    mgr.test_transport = transport
    # Mock-backed throughout, so the console must tag everything SIMULATION
    # rather than present it as a physical measurement.
    app = AMRWebApp(mgr, tick_hz=10.0, camera=camera, simulated=True)
    port = app.start(host="127.0.0.1", port=0)
    mgr.start()  # bring the (mock) link up so the control loop sees a robot
    try:
        yield app, port, mgr
    finally:
        app.stop()
        mgr.shutdown()


@pytest.fixture
def web_no_camera(config_dir):
    """Same, but with no camera configured at all."""
    from amr.robot import RobotManager
    from amr.utils.config import load_config
    from amr.web import AMRWebApp

    config = load_config(config_dir)
    mgr, _transport = RobotManager.create_mock(config)
    app = AMRWebApp(mgr, tick_hz=10.0)
    port = app.start(host="127.0.0.1", port=0)
    mgr.start()
    try:
        yield app, port, mgr
    finally:
        app.stop()
        mgr.shutdown()
