"""Integration tests for the safety-gated web control (Phase 10).

These run the *real* HTTP server (``ThreadingHTTPServer``) on an ephemeral
port against the full mock robot stack — the same code path as hardware
mode, with zero external services. The central property under test is the
safety gate: **no motion command is honoured unless the robot is
connected AND in a mode that is safe to move**.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from amr.camera import CameraManager
from amr.mocks import MockCamera
from amr.robot import RobotManager, RobotMode
from amr.utils.config import CameraConfig, load_config
from amr.web import AMRWebApp


# --------------------------------------------------------------------------- #
# HTTP helpers (urllib only — no third-party test deps)
# --------------------------------------------------------------------------- #
def _get(port: int, path: str):
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}{path}", timeout=5
    ) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


def _post(port: int, path: str, body: str) -> tuple:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _cmd(port: int, payload: dict) -> tuple:
    return _post(port, "/command", json.dumps(payload))


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def web(config_dir):
    """A running web app + mock robot, with a mock camera attached."""
    config = load_config(config_dir)
    mgr, _transport = RobotManager.create_mock(config)
    camera = CameraManager(
        MockCamera(available=True), CameraConfig(enabled=True)
    )
    app = AMRWebApp(mgr, tick_hz=10.0, camera=camera)
    port = app.start(host="127.0.0.1", port=0)
    mgr.start()  # bring the (mock) link up so the control loop sees a robot
    yield app, port, mgr
    app.stop()
    mgr.shutdown()


@pytest.fixture
def web_no_camera(config_dir):
    """Same, but with no camera configured at all."""
    config = load_config(config_dir)
    mgr, _transport = RobotManager.create_mock(config)
    app = AMRWebApp(mgr, tick_hz=10.0)
    port = app.start(host="127.0.0.1", port=0)
    mgr.start()
    yield app, port, mgr
    app.stop()
    mgr.shutdown()


# --------------------------------------------------------------------------- #
# Panel + read endpoints
# --------------------------------------------------------------------------- #
def test_index_serves_panel(web):
    _app, port, _mgr = web
    status, ctype, body = _get(port, "/")
    assert status == 200
    assert "text/html" in ctype
    html = body.decode("utf-8")
    assert "AMR Control" in html
    assert "/command" in html  # the JS drives the same API the tests use


def test_status_endpoint_shape(web):
    _app, port, _mgr = web
    status, _ctype, body = _get(port, "/status")
    assert status == 200
    j = json.loads(body.decode("utf-8"))
    assert j["connected"] is True
    assert j["mode"] in ("IDLE", "MANUAL", "AUTONOMOUS", "SAFETY_STOP", "ERROR")
    for key in ("left_speed", "right_speed", "front_cm", "safety", "version"):
        assert key in j


def test_sensor_endpoint(web):
    _app, port, _mgr = web
    status, _ctype, body = _get(port, "/sensor")
    assert status == 200
    j = json.loads(body.decode("utf-8"))
    assert "safety" in j and "front_cm" in j


def test_unknown_route_404(web):
    _app, port, _mgr = web
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(port, "/nope")
    assert exc.value.code == 404


# --------------------------------------------------------------------------- #
# Safety gate: motion is refused outside manual/autonomous modes
# --------------------------------------------------------------------------- #
def test_motion_gated_in_idle(web):
    _app, port, _mgr = web
    _mgr.request_mode(RobotMode.IDLE)  # ensure a known starting point
    code, j = _cmd(port, {"cmd": "forward", "speed": 100})
    assert code == 400
    assert "motion not allowed" in j["error"]
    assert _mgr.state.left_speed == 0


def test_unknown_command_400(web):
    _app, port, _mgr = web
    code, j = _cmd(port, {"cmd": "spin", "speed": 50})
    assert code == 400
    assert "unknown command" in j["error"]


def test_bad_json_400(web):
    _app, port, _mgr = web
    code, j = _post(port, "/command", "this is not json")
    assert code == 400
    assert "bad JSON" in j["error"]


# --------------------------------------------------------------------------- #
# Normal operation once the operator selects MANUAL
# --------------------------------------------------------------------------- #
def test_manual_mode_allows_motion(web):
    _app, port, mgr = web
    code, _j = _cmd(port, {"cmd": "mode", "mode": "manual"})
    assert code == 200

    code, j = _cmd(port, {"cmd": "forward", "speed": 120})
    assert code == 200
    assert j["ok"] is True

    _status, _ctype, body = _get(port, "/status")
    s = json.loads(body.decode("utf-8"))
    assert s["left_speed"] == 120
    assert s["right_speed"] == 120
    assert s["is_moving"] is True

    code, _j = _cmd(port, {"cmd": "stop"})
    assert code == 200
    _status, _ctype, body = _get(port, "/status")
    s = json.loads(body.decode("utf-8"))
    assert s["left_speed"] == 0
    assert s["is_moving"] is False


def test_estop_forces_safety_stop(web):
    _app, port, mgr = web
    _cmd(port, {"cmd": "mode", "mode": "manual"})
    _cmd(port, {"cmd": "forward", "speed": 100})

    code, _j = _cmd(port, {"cmd": "estop"})
    assert code == 200
    assert mgr.state.mode.value == "SAFETY_STOP"
    assert mgr.state.left_speed == 0

    # Motion is refused again while in SAFETY_STOP.
    code, j = _cmd(port, {"cmd": "forward", "speed": 100})
    assert code == 400

    # Explicit reset returns to IDLE.
    code, _j = _cmd(port, {"cmd": "mode", "mode": "idle"})
    assert code == 200
    assert mgr.state.mode.value == "IDLE"


def test_illegal_mode_transition_400(web):
    _app, port, _mgr = web
    _mgr.request_mode(RobotMode.IDLE)
    # IDLE -> AUTONOMOUS is not allowed by the state machine.
    code, j = _cmd(port, {"cmd": "mode", "mode": "autonomous"})
    assert code == 400
    assert "illegal mode transition" in j["error"]


def test_speed_out_of_range_400(web):
    _app, port, _mgr = web
    _cmd(port, {"cmd": "mode", "mode": "manual"})
    code, j = _cmd(port, {"cmd": "forward", "speed": 9999})
    assert code == 400


# --------------------------------------------------------------------------- #
# Camera endpoints (Phase 11)
# --------------------------------------------------------------------------- #
def test_camera_status_with_camera(web):
    _app, port, _mgr = web
    status, _ctype, body = _get(port, "/camera")
    assert status == 200
    j = json.loads(body.decode("utf-8"))
    assert j["available"] is True
    assert j["enabled"] is True
    assert "device" in j and "resolution" in j


def test_image_endpoint_serves_jpeg(web):
    _app, port, _mgr = web
    status, ctype, body = _get(port, "/image")
    assert status == 200
    assert "image/jpeg" in ctype
    assert body[:2] == b"\xff\xd8"  # JPEG SOI
    assert body[-2:] == b"\xff\xd9"  # JPEG EOI


def test_image_endpoint_query_string(web):
    _app, port, _mgr = web
    status, _ctype, body = _get(port, "/image?ts=12345")
    assert status == 200
    assert body[:2] == b"\xff\xd8"


def test_camera_endpoints_without_camera(web_no_camera):
    _app, port, _mgr = web_no_camera
    status, _ctype, body = _get(port, "/camera")
    assert status == 200
    j = json.loads(body.decode("utf-8"))
    assert j["available"] is False
    assert j["status"] == "NOT_CONFIGURED"

    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(port, "/image")
    assert exc.value.code == 503
    assert json.loads(exc.value.read().decode("utf-8"))["error"] == (
        "camera unavailable"
    )
