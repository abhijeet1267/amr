"""Integration tests for the safety-gated web control (Phase 10 + C2 hazard).

These run the *real* HTTP server (``ThreadingHTTPServer``) on an ephemeral
port against the full mock robot stack — the same code path as hardware
mode, with zero external services. The central property under test is the
safety gate: **no motion command is honoured unless the robot is
connected AND in a mode that is safe to move**.

The C2 hazard tests additionally prove the operator-facing contract:
``GET /hazard`` reports the real ``HazardManager`` state (including the
honest ``attached: false`` shape when no layer is wired), and
``POST /hazard/acknowledge`` releases *only* the latch — never an active
hazard, never the robot's ``SAFETY_STOP`` mode.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from amr.camera import CameraManager
from amr.hazard import HazardKind, HazardManager, HazardReading, HazardSeverity
from amr.mocks import MockCamera
from amr.robot import RobotManager, RobotMode
from amr.utils.config import CameraConfig, HazardConfig, load_config
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
    # The whole stack is mock-backed (MockSerialTransport + MockCamera), so the
    # dashboard must tag every value SIMULATION rather than present it as a
    # physical measurement. This is the same flag `run_web` passes for --mock.
    app = AMRWebApp(
        mgr, tick_hz=10.0, camera=camera, simulated=True
    )
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


class MutableHazardSource:
    """A hazard source whose readings a test can swap between requests."""

    def __init__(self, name: str = "scripted"):
        self.name = name
        self._readings = ()

    def set(self, *readings: HazardReading) -> None:
        self._readings = tuple(readings)

    def read(self):
        return self._readings


@pytest.fixture
def web_hazard(config_dir):
    """A running web app whose RobotManager has a hazard layer attached.

    The layer carries one :class:`MutableHazardSource` so tests can inject
    controlled hazards, and ``enabled=True`` so the snapshot reflects an
    opted-in deployment.
    """
    config = load_config(config_dir)
    mgr, _transport = RobotManager.create_mock(config)
    src = MutableHazardSource()
    mgr.attach_hazard(
        HazardManager(HazardConfig(enabled=True), sources=[src])
    )
    app = AMRWebApp(mgr, tick_hz=10.0)
    port = app.start(host="127.0.0.1", port=0)
    mgr.start()
    yield app, port, mgr, src
    app.stop()
    mgr.shutdown()


def _tick(port: int) -> None:
    """Force one locked control-loop tick through the public API.

    ``GET /sensor`` runs ``RobotManager.tick()`` under the app lock — the
    same serialisation the background loop uses — so hazard evaluation is
    deterministic without racing the loop from the test thread.
    """
    _get(port, "/sensor")


def _hazard(port: int) -> dict:
    """GET /hazard parsed as JSON."""
    _status, _ctype, body = _get(port, "/hazard")
    return json.loads(body.decode("utf-8"))


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


# --------------------------------------------------------------------------- #
# Hazard endpoint + acknowledgement (C2)
# --------------------------------------------------------------------------- #
def test_hazard_endpoint_normal_without_layer(web):
    """No hazard layer attached: an honest stable shape, not a fake NORMAL."""
    _app, port, _mgr = web
    status, ctype, body = _get(port, "/hazard")
    assert status == 200
    assert "application/json" in ctype
    j = json.loads(body.decode("utf-8"))
    assert j["attached"] is False
    assert j["state"] is None            # no assessment, per the camera convention
    assert j["severity"] == "NONE"
    assert j["latched"] is False
    assert j["active"] is False
    assert j["hazard"] is None
    assert j["active_events"] == []
    assert j["latest_event"] is None


def test_hazard_endpoint_normal_when_attached(web_hazard):
    """Attached layer with clean air: the real snapshot contract."""
    _app, port, _mgr, _src = web_hazard
    _tick(port)
    j = _hazard(port)
    assert j["attached"] is True
    assert j["enabled"] is True
    assert j["state"] == "NORMAL"
    assert j["severity"] == "NONE"
    assert j["latched"] is False
    assert j["active"] is False
    assert j["blocks_motion"] is False
    assert j["speed_scale"] == 1.0
    assert j["hazard"] is None
    assert j["events_recorded"] == 0
    assert j["latest_event"] is None


def test_hazard_endpoint_reports_active_hazard(web_hazard):
    """A controlled reading shows up with kind, confidence, source and events."""
    _app, port, _mgr, src = web_hazard
    src.set(
        HazardReading(
            kind=HazardKind.HUMAN,
            value=0.62,
            unit="confidence",
            severity=HazardSeverity.WARNING,
            source="cam",
            message="person detected (confidence 0.62)",
        )
    )
    _tick(port)

    j = _hazard(port)
    assert j["state"] == "SLOW"          # HUMAN is a configured slow kind
    assert j["severity"] == "WARNING"
    assert j["active"] is True
    assert j["latched"] is False
    assert j["speed_scale"] == 0.5
    assert j["hazard"] is not None
    assert j["hazard"]["kind"] == "HUMAN"
    assert j["hazard"]["source"] == "cam"
    assert j["hazard"]["unit"] == "confidence"
    assert j["hazard"]["confidence"] == pytest.approx(0.62)
    assert j["events_recorded"] == 1
    assert j["latest_event"]["kind"] == "HUMAN"
    assert j["latest_event"]["resolved"] is False
    assert j["counts_by_kind"]["HUMAN"] == 1


def test_hazard_endpoint_reports_latched_emergency(web_hazard):
    """CRITICAL fire latches EMERGENCY, vetoes motion, forces SAFETY_STOP."""
    _app, port, mgr, src = web_hazard
    src.set(
        HazardReading(
            kind=HazardKind.FIRE,
            value=0.95,
            unit="confidence",
            severity=HazardSeverity.CRITICAL,
            source="cam",
            message="flame detected (confidence 0.95)",
        )
    )
    _tick(port)

    j = _hazard(port)
    assert j["state"] == "EMERGENCY"
    assert j["latched"] is True
    assert j["severity"] == "CRITICAL"
    assert j["active"] is True
    assert j["blocks_motion"] is True
    assert j["speed_scale"] == 0.0
    assert j["hazard"]["kind"] == "FIRE"
    assert j["hazard"]["confidence"] == pytest.approx(0.95)

    # The robot reacted: emergency latching must have forced SAFETY_STOP.
    assert mgr.state.mode is RobotMode.SAFETY_STOP
    assert (mgr.state.left_speed, mgr.state.right_speed) == (0, 0)
    code, _j = _cmd(port, {"cmd": "forward", "speed": 100})
    assert code == 400

    # /status carries the same verdict (additive snapshot key).
    _s, _c, body = _get(port, "/status")
    assert json.loads(body.decode("utf-8"))["hazard"]["state"] == "EMERGENCY"


def test_hazard_ack_cannot_clear_an_active_hazard(web_hazard):
    """Ack with evidence still present: re-latched, motion still refused."""
    _app, port, mgr, src = web_hazard
    src.set(
        HazardReading(
            kind=HazardKind.FIRE,
            value=0.95,
            unit="confidence",
            severity=HazardSeverity.CRITICAL,
            source="cam",
            message="flame detected (confidence 0.95)",
        )
    )
    _tick(port)
    assert _hazard(port)["latched"] is True

    code, j = _post(port, "/hazard/acknowledge", "{}")
    assert code == 200
    assert j["ok"] is True
    assert j["acknowledged"] is True      # the operator's action was accepted...
    assert j["was_latched"] is True
    assert j["latched"] is True           # ...but the hazard re-latched itself
    assert j["state"] == "EMERGENCY"
    assert j["hazard"]["active"] is True

    after = _hazard(port)
    assert after["state"] == "EMERGENCY"
    assert after["latched"] is True
    assert after["active"] is True
    assert after["blocks_motion"] is True
    assert mgr.state.mode is RobotMode.SAFETY_STOP
    code, _j = _cmd(port, {"cmd": "forward", "speed": 100})
    assert code == 400


def test_hazard_ack_is_step_one_of_a_two_step_release(web_hazard):
    """Ack clears the latch only; SAFETY_STOP survives until a mode reset."""
    _app, port, mgr, src = web_hazard
    src.set(
        HazardReading(
            kind=HazardKind.FIRE,
            value=0.95,
            unit="confidence",
            severity=HazardSeverity.CRITICAL,
            source="cam",
            message="flame detected (confidence 0.95)",
        )
    )
    _tick(port)

    # Evidence disappears, but the latch must persist on its own.
    src.set()
    _tick(port)
    held = _hazard(port)
    assert held["state"] == "EMERGENCY"
    assert held["latched"] is True
    assert held["active"] is False        # cleared evidence, still latched
    assert held["severity"] == "CRITICAL"  # state floor keeps severity honest
    assert held["hazard"] is None

    # Step 1: acknowledge the hazard latch.
    code, j = _post(port, "/hazard/acknowledge", "{}")
    assert code == 200
    assert j["ok"] is True
    assert j["acknowledged"] is True
    assert j["was_latched"] is True
    assert j["latched"] is False
    assert j["state"] == "NORMAL"
    assert j["hazard"]["state"] == "NORMAL"

    # Ack did NOT restart anything: the robot is still in SAFETY_STOP.
    assert mgr.state.mode is RobotMode.SAFETY_STOP
    code, _j = _cmd(port, {"cmd": "forward", "speed": 100})
    assert code == 400

    # The resolved event remains in the audit trail.
    assert _hazard(port)["latest_event"]["kind"] == "FIRE"
    assert _hazard(port)["latest_event"]["resolved"] is True

    # Step 2: the existing mode path completes the release.
    code, _j = _cmd(port, {"cmd": "mode", "mode": "idle"})
    assert code == 200
    code, _j = _cmd(port, {"cmd": "mode", "mode": "manual"})
    assert code == 200
    code, j = _cmd(port, {"cmd": "forward", "speed": 100})
    assert code == 200
    assert j["ok"] is True


def test_hazard_ack_is_idempotent_when_not_latched(web_hazard):
    """Acknowledging a healthy layer is a safe no-op."""
    _app, port, _mgr, _src = web_hazard
    _tick(port)
    code, j = _post(port, "/hazard/acknowledge", "")
    assert code == 200
    assert j["ok"] is True
    assert j["acknowledged"] is True
    assert j["was_latched"] is False
    assert j["latched"] is False
    assert j["state"] == "NORMAL"


def test_hazard_ack_without_layer_is_400(web):
    """No layer attached: a clear rejection, not a silent success."""
    _app, port, _mgr = web
    code, j = _post(port, "/hazard/acknowledge", "{}")
    assert code == 400
    assert j["ok"] is False
    assert "not attached" in j["error"]


def test_hazard_ack_rejects_non_object_payload(web_hazard):
    _app, port, _mgr, _src = web_hazard
    code, j = _post(port, "/hazard/acknowledge", "[1, 2]")
    assert code == 400
    assert j["ok"] is False
    assert "JSON object" in j["error"]

    code, j = _post(port, "/hazard/acknowledge", "this is not json")
    assert code == 400
    assert j["ok"] is False
    assert "bad JSON" in j["error"]


def test_status_and_panel_expose_hazard(web_hazard):
    """Regression: /status still works with a layer attached; the panel links it."""
    _app, port, _mgr, src = web_hazard
    src.set(
        HazardReading(
            kind=HazardKind.TEMPERATURE,
            value=91.0,
            unit="degC",
            severity=HazardSeverity.WARNING,
            source="probe",
            message="over-temperature 91degC",
        )
    )
    _tick(port)

    status, _ctype, body = _get(port, "/status")
    assert status == 200
    j = json.loads(body.decode("utf-8"))
    assert j["connected"] is True
    assert j["hazard"]["state"] == "WARNING"   # TEMPERATURE is not a slow kind

    status, _ctype, body = _get(port, "/")
    html = body.decode("utf-8")
    assert status == 200
    assert "hazBadge" in html                  # panel header indicator
    assert "/hazard" in html                   # panel polls the endpoint
    assert "/hazard/acknowledge" in html       # panel offers the ack control


# --------------------------------------------------------------------------- #
# C7 — dashboard foundation: read-only telemetry + health + dashboard HTML
# --------------------------------------------------------------------------- #
class TestDashboardAPI:
    def test_health_is_public_and_reports_ok(self, web):
        _app, port, _mgr = web
        code, ctype, body = _get(port, "/health")
        assert code == 200
        assert "application/json" in ctype
        j = json.loads(body.decode("utf-8"))
        assert j["ok"] is True
        assert j["status"] in ("OK", "DEGRADED")
        assert j["simulated"] is True      # the fixture runtime is mock-backed
        assert j["connected"] is True
        assert j["schema_version"] == "1.0"

    def test_health_lists_every_subsystem_source(self, web):
        _app, port, _mgr = web
        _code, _ctype, body = _get(port, "/health")
        sources = json.loads(body.decode("utf-8"))["sources"]
        # Real vs simulated must be explicit for every dashboard subsystem.
        for section in ("camera", "hazards", "mission", "navigation",
                        "sensors", "safety", "battery", "system"):
            assert sources[section] in ("LIVE", "SIMULATION", "UNAVAILABLE")

    def test_telemetry_returns_the_full_contract(self, web):
        _app, port, _mgr = web
        code, ctype, body = _get(port, "/telemetry")
        assert code == 200
        assert "application/json" in ctype
        j = json.loads(body.decode("utf-8"))
        for key in ("schema_version", "timestamp", "simulated", "source",
                    "mode", "robot_id", "position", "orientation", "velocity",
                    "navigation", "safety", "hazards", "battery", "sensors",
                    "mission", "camera", "system"):
            assert key in j, key

    def test_telemetry_never_invents_hardware_measurements(self, web):
        """Battery is absent in this project: it must be null, not 0."""
        _app, port, _mgr = web
        _code, _ctype, body = _get(port, "/telemetry")
        battery = json.loads(body.decode("utf-8"))["battery"]
        assert battery["source"] == "UNAVAILABLE"
        assert battery["percentage"] is None
        assert battery["voltage"] is None

    def test_telemetry_contract_is_stable_across_polls(self, web):
        """The *shape* of the contract never changes between polls.

        Values legitimately move (the fixture's control loop is running), so
        this asserts structural stability — same keys, same per-section source
        tags — which is what a client can actually rely on.
        """
        _app, port, _mgr = web
        shapes = []
        for _ in range(3):
            _code, _ctype, body = _get(port, "/telemetry")
            j = json.loads(body.decode("utf-8"))
            shapes.append((sorted(j), {k: v.get("source")
                                      for k, v in j.items()
                                      if isinstance(v, dict)}))
        assert shapes[0] == shapes[1] == shapes[2]

    def test_dashboard_page_is_served(self, web):
        _app, port, _mgr = web
        code, ctype, body = _get(port, "/dashboard")
        assert code == 200
        assert "text/html" in ctype
        html = body.decode("utf-8")
        assert "AMR CONTROL CENTER" in html
        assert "/telemetry" in html          # the page polls the new endpoint

    def test_dashboard_is_read_only_over_http(self, web):
        """The dashboard must not expose a second motor-control path."""
        _app, port, _mgr = web
        code, _ctype, _body = _get(port, "/dashboard")
        assert code == 200
        # A dashboard page with no motion verbs in its own JS.
        for verb in ("command", "drive", "motor", "pwm"):
            assert f'"{verb}"' not in _get(port, "/dashboard")[2].decode()

    def test_existing_routes_still_work_alongside_dashboard(self, web):
        """C7 extends the C2 server; it does not replace any route."""
        _app, port, _mgr = web
        assert _get(port, "/")[0] == 200
        assert _get(port, "/status")[0] == 200
        assert _get(port, "/hazard")[0] == 200
        assert _get(port, "/health")[0] == 200
        assert _get(port, "/telemetry")[0] == 200

    def test_unknown_dashboard_path_still_404s(self, web):
        _app, port, _mgr = web
        with pytest.raises(urllib.error.HTTPError) as e:
            _get(port, "/telemetry/nope")
        assert e.value.code == 404

