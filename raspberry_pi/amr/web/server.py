"""Web remote control (Phase 10) — stdlib-only HTTP server.

Endpoints
---------
GET  /          — self-contained control panel (HTML/JS, no external assets)
GET  /status    — full robot snapshot (JSON)
GET  /sensor    — one sensor poll + safety decision (JSON)
GET  /camera    — camera status (JSON; ``{"available": false}`` when none)
GET  /image     — one JPEG frame (200 image/jpeg, or 503 when unavailable)
GET  /hazard    — hazard layer status (JSON; ``{"attached": false, ...}`` when
                  no hazard layer is wired into the RobotManager)
POST /command   — ``{"cmd": "...", ...}`` (JSON in, JSON out)
POST /hazard/acknowledge — release a *latched* hazard EMERGENCY (step 1 of the
                  two-step release; optional empty/``{}`` JSON body)

Commands accepted by ``/command``:

    estop                 {"cmd": "estop"}
    stop                  {"cmd": "stop"}
    mode                  {"cmd": "mode", "mode": "manual"}
    forward/backward      {"cmd": "forward", "speed": 100}
    rotate_left/rotate_right  {"cmd": "rotate_left", "speed": 100}
    turn_left/turn_right  {"cmd": "turn_left", "speed": 80}

HTTP status: 200 ok · 400 rejected (safety/mode/bad payload) · 500 internal.

``GET /hazard`` is a *pure read*: it never evaluates or clears anything. The
response is ``HazardManager.snapshot()`` (the established JSON contract) plus a
few derived operator keys: ``attached``, ``severity`` (NONE/WARNING/CRITICAL),
``active`` (evidence present right now), ``hazard`` (worst active hazard, with
``confidence`` when the reading carries one) and ``latest_event``.

Threading model
---------------
* One background **control-loop** thread calls ``mgr.tick()`` at ``tick_hz``.
* HTTP handlers run on ``ThreadingHTTPServer`` worker threads.
* A single lock serialises tick and command dispatch so state reads stay
  consistent for a single-operator console. (The warehouse task manager in a
  later phase will use the same lock discipline.)

Safety
------
The web layer adds **no** new capabilities: it only invokes the gated
RobotManager methods. A safety veto, an illegal mode transition, or a
disconnected link all surface as HTTP 400 with a reason — the robot never
moves when the gate says no.

The hazard endpoints are read/acknowledge only:

* ``GET /hazard`` evaluates nothing and clears nothing.
* ``POST /hazard/acknowledge`` performs **step 1** of the two-step release: it
  clears the hazard ``EMERGENCY`` *latch* only (``HazardManager.acknowledge``),
  which immediately re-evaluates the layer — evidence that is still present
  re-latches on the spot, so acknowledging can never bypass an active hazard.
  It deliberately does **not** reset the robot's ``SAFETY_STOP`` mode; that
  stays on the existing ``POST /command {"cmd": "mode", ...}`` path. The
  maintenance-grade ``HazardManager.reset()`` (which would drop the event audit
  trail) is intentionally **not** exposed over HTTP.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

from ..camera import CameraManager
from ..camera.frame import CameraFrame, CameraStatus
from ..hazard import HazardSeverity, HazardState
from ..logging import get_logger
from ..robot import RobotCommandError, RobotManager
from ..robot.robot_state import RobotMode
from ..telemetry import TelemetryCollector
from ..telemetry.types import DataSource

#: motion commands accepted by /command and their default speeds
_MOTION = {
    "forward": 100,
    "backward": 100,
    "rotate_left": 100,
    "rotate_right": 100,
    "turn_left": 80,
    "turn_right": 80,
}

#: Ranking for the derived top-level ``severity`` of GET /hazard. The web layer
#: only ever reports NONE/WARNING/CRITICAL — a superset-free projection of the
#: real ``HazardSeverity`` vocabulary onto "is there an active hazard?".
_SEVERITY_RANK = {"NONE": 0, "WARNING": 1, "CRITICAL": 2}

#: Floor: the worst severity the current hazard *state* implies. Active events
#: can only raise it further (they cannot lower it), which keeps a latched
#: EMERGENCY reporting CRITICAL even after its evidence has cleared.
_STATE_SEVERITY = {
    HazardState.NORMAL: "NONE",
    HazardState.WARNING: "WARNING",
    HazardState.SLOW: "WARNING",
    HazardState.STOP: "CRITICAL",
    HazardState.EMERGENCY: "CRITICAL",
}

#: C8 — where a camera source's most recent frame is cached. Only the *latest*
#: frame is retained, so polling the dashboard cannot grow memory over time.
_FRAME_CACHE_ATTR = "_amr_last_frame"

#: Content types for the encodings the camera sources can actually emit.
_IMAGE_CONTENT_TYPES = {
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "bmp": "image/bmp",
}


def _cached_frame(cam: Any) -> Optional[CameraFrame]:
    """Return the camera's cached latest frame, if it has one."""
    for attr in (_FRAME_CACHE_ATTR, "last_frame", "latest_frame"):
        frame = getattr(cam, attr, None)
        if isinstance(frame, CameraFrame):
            return frame
    return None


def _cache_frame(cam: Any, frame: CameraFrame) -> None:
    """Store ``frame`` as the camera's latest, replacing any previous one."""
    try:
        setattr(cam, _FRAME_CACHE_ATTR, frame)
    except Exception:  # noqa: BLE001 - a read-only camera object is not fatal
        pass


def _image_content_type(fmt: Optional[str]) -> str:
    """Content type for a frame format, defaulting to a safe image type."""
    return _IMAGE_CONTENT_TYPES.get((fmt or "").lower(), "image/png")


class AMRWebApp:
    """Binds a :class:`RobotManager` to an HTTP server + control loop."""

    def __init__(
        self,
        mgr: RobotManager,
        tick_hz: float = 5.0,
        camera: Optional[CameraManager] = None,
        telemetry: Optional[TelemetryCollector] = None,
        navigator: Any = None,
        warehouse: Any = None,
        simulated: bool = False,
        software_version: Optional[str] = None,
    ):
        self._mgr = mgr
        self._tick_hz = max(0.5, float(tick_hz))
        self._camera = camera
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._server: Optional[ThreadingHTTPServer] = None
        self._threads: list = []
        self.log = get_logger("web")
        # Read-only projection of this same manager for the C7 dashboard. It is
        # built here (rather than required from the caller) so the web app can
        # never be wired to a different runtime than the one it controls, and
        # so it can only ever read.
        self.telemetry = telemetry or TelemetryCollector(
            mgr,
            navigator=navigator,
            warehouse=warehouse,
            camera=camera,
            simulated=simulated,
            software_version=software_version,
        )

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self, host: str = "0.0.0.0", port: int = 8080) -> int:
        """Start control loop + HTTP server. Returns the bound port."""
        # socketserver always calls the handler with exactly
        # (request, client_address, server) — bind the app via a subclass.
        app = self

        class _BoundHandler(_Handler):
            def __init__(self, request, client_address, server):
                # Must be set *before* super().__init__: BaseRequestHandler
                # handles the request synchronously inside its __init__.
                self.app = app
                super().__init__(request, client_address, server)

        self._server = ThreadingHTTPServer((host, port), _BoundHandler)
        self._threads = [
            threading.Thread(target=self._server.serve_forever, daemon=True),
            threading.Thread(target=self._control_loop, daemon=True),
        ]
        for t in self._threads:
            t.start()
        bound_port = self._server.server_address[1]
        self.log.info("web control on http://%s:%d", host, bound_port)
        return bound_port

    def stop(self) -> None:
        self._stop_evt.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        for t in self._threads:
            t.join(timeout=2)
        self._threads = []

    def _control_loop(self) -> None:
        interval = 1.0 / self._tick_hz
        while not self._stop_evt.is_set():
            with self._lock:
                try:
                    self._mgr.tick()
                except Exception as exc:  # noqa: BLE001 - loop must survive
                    self.log.error("tick failed: %s", exc)
            self._stop_evt.wait(interval)

    # ------------------------------------------------------------------ #
    # Handler-facing API (all serialised by the lock)
    # ------------------------------------------------------------------ #
    def snapshot(self) -> dict:
        with self._lock:
            return self._mgr.snapshot()

    def poll_sensor(self) -> dict:
        with self._lock:
            d = self._mgr.tick()
            s = self._mgr.state
            return {
                "safety": str(d),
                "front_cm": s.front_cm,
                "left_cm": s.left_cm,
                "right_cm": s.right_cm,
                "rear_cm": s.rear_cm,
            }

    def camera_status(self) -> dict:
        with self._lock:
            if self._camera is None:
                return {"enabled": False, "available": False,
                        "status": "NOT_CONFIGURED"}
            return self._camera.describe()

    def image(self) -> Optional[bytes]:
        """One JPEG frame, or ``None`` when the camera is unusable."""
        with self._lock:
            if self._camera is None:
                return None
            return self._camera.capture_jpeg()

    # ------------------------------------------------------------------ #
    # C8 — camera monitoring (read-only; no browser → hardware path)
    # ------------------------------------------------------------------ #
    def camera_info(self) -> dict:
        """Camera status for ``GET /camera/status`` — metadata only, no pixels.

        Returns the C8 :class:`~amr.camera.frame.CameraFrame` view when the
        attached camera follows the C8 source protocol, and falls back to the
        legacy ``describe()`` shape otherwise. Never raises: a broken camera
        reports ``ERROR`` so the rest of the dashboard keeps working.
        """
        with self._lock:
            cam = self._camera
            if cam is None:
                return {
                    "status": CameraStatus.UNAVAILABLE.value,
                    "source": DataSource.UNAVAILABLE.value,
                    "source_name": None, "width": None, "height": None,
                    "format": None, "frame_id": 0, "timestamp": None,
                    "has_frame": False, "error": "no camera configured",
                }
            frame = _cached_frame(cam)
            describe = getattr(cam, "describe", None)
            info: Dict[str, Any] = {}
            if callable(describe):
                try:
                    got = describe()
                    if isinstance(got, dict):
                        info = dict(got)
                except Exception as exc:  # noqa: BLE001
                    self.log.warning("camera.describe() failed: %s", exc)
                    return {
                        "status": CameraStatus.ERROR.value,
                        "source": DataSource.UNAVAILABLE.value,
                        "source_name": None, "width": None, "height": None,
                        "format": None, "frame_id": 0, "timestamp": None,
                        "has_frame": False, "error": str(exc),
                    }
            if frame is not None:
                return frame.to_dict()
            status = CameraStatus.parse(info.get("status", "UNAVAILABLE"))
            return {
                "status": status.value,
                "source": (DataSource.SIMULATION if status is CameraStatus.SIMULATION
                           else DataSource.LIVE if status is CameraStatus.LIVE
                           else DataSource.UNAVAILABLE).value,
                "source_name": info.get("name") or info.get("source"),
                "width": info.get("width"), "height": info.get("height"),
                "format": info.get("format"),
                "frame_id": int(info.get("frame_id") or 0),
                "timestamp": None, "has_frame": False,
                "error": info.get("reason"),
                "available": info.get("available", status.available),
                "running": info.get("running"),
                "device": info.get("device"),
            }

    def camera_frame(self) -> Tuple[Optional[bytes], Optional[str], int]:
        """Latest encoded frame for ``GET /camera/frame``.

        Returns ``(data, content_type, http_status)``. Only the *latest* frame
        is served — no history is buffered, so repeated polling cannot grow
        memory. A camera that cannot produce a frame yields ``503`` with a
        machine-readable reason rather than a fabricated placeholder.
        """
        with self._lock:
            cam = self._camera
            if cam is None:
                return None, None, 503
            frame = _cached_frame(cam)
            if frame is not None and frame.data is not None:
                return frame.data, _image_content_type(frame.format), 200
            # A C8 source can capture on demand; fall back to that only when no
            # cached frame exists, so a polling dashboard does not re-capture
            # on every request.
            reader = getattr(cam, "read", None)
            if callable(reader):
                try:
                    got = reader()
                except Exception as exc:  # noqa: BLE001
                    self.log.warning("camera.read() failed: %s", exc)
                    return None, None, 503
                if isinstance(got, CameraFrame) and got.data is not None:
                    _cache_frame(cam, got)
                    return got.data, _image_content_type(got.format), 200
                return None, None, 503
            # Legacy CameraManager exposes capture_jpeg().
            capture = getattr(cam, "capture_jpeg", None)
            if callable(capture):
                try:
                    jpeg = capture()
                except Exception as exc:  # noqa: BLE001
                    self.log.warning("camera.capture_jpeg() failed: %s", exc)
                    return None, None, 503
                if jpeg:
                    return jpeg, "image/jpeg", 200
            return None, None, 503

    # ------------------------------------------------------------------ #
    # C7 — read-only telemetry projection (no motor path whatsoever)
    # ------------------------------------------------------------------ #
    def telemetry_snapshot(self) -> dict:
        """Full read-only telemetry snapshot for ``GET /telemetry``.

        The collector only *reads* the runtime (it never calls ``tick()``,
        never dispatches a command and never touches an actuator), so this
        handler cannot move the robot no matter what it returns.
        """
        with self._lock:
            return self.telemetry.snapshot()

    def health(self) -> Tuple[dict, int]:
        """Liveness/readiness probe for ``GET /health``.

        Composes two independent facts: the collector's subsystem/reachability
        summary, and whether this HTTP server is actually serving. The HTTP
        status reflects only the latter — a *degraded robot* is still a
        reachable dashboard, so it answers 200 and reports ``DEGRADED`` in the
        body rather than masquerading as a server outage.
        """
        with self._lock:
            running = self._server is not None
            body = dict(self.telemetry.health())
        body["read_only"] = True
        body["server"] = "amr-dashboard"
        body["serving"] = running
        if not running:
            body["status"] = "STOPPED"
        return body, (200 if running else 503)

    # ------------------------------------------------------------------ #
    # Hazard layer (Layer 3.5) — read + acknowledge only
    # ------------------------------------------------------------------ #
    def hazard_status(self) -> dict:
        """Current hazard view for ``GET /hazard`` (pure read, no evaluate)."""
        with self._lock:
            return self._hazard_payload()

    def acknowledge_hazard(self) -> Tuple[dict, int]:
        """Operator acknowledgement of a latched hazard EMERGENCY.

        Performs **step 1** of the two-step release only: it clears the hazard
        latch via :meth:`HazardManager.acknowledge`, which immediately
        re-evaluates the layer, so evidence that is still present re-latches on
        the spot. The robot's ``SAFETY_STOP`` mode is deliberately untouched —
        releasing it remains an explicit ``POST /command {"cmd": "mode"}``.
        """
        with self._lock:
            hazard = self._mgr.hazard
            if hazard is None:
                return {"ok": False, "error": "hazard layer not attached"}, 400
            was_latched = hazard.latched
            status = hazard.acknowledge()
            if was_latched:
                self.log.info(
                    "hazard latch acknowledged via panel (latched now: %s)",
                    status.latched,
                )
            return {
                "ok": True,
                "acknowledged": True,
                "was_latched": was_latched,
                "latched": status.latched,
                "state": status.state.value,
                "hazard": self._hazard_payload(),
            }, 200

    def _hazard_payload(self) -> dict:
        """Build the ``GET /hazard`` body (caller must hold the lock).

        The base is always :meth:`HazardManager.snapshot()` — the established
        JSON contract — extended with derived, operator-facing keys:

        ``attached``     whether a hazard layer is wired into the manager
        ``severity``     NONE/WARNING/CRITICAL: the worst of the state floor
                         and the active events (so a latched EMERGENCY reports
                         CRITICAL even after its evidence has cleared)
        ``active``       ``True`` while unresolved hazard evidence exists
        ``hazard``       the worst active hazard (kind/source/message/location
                         plus ``value``/``unit``/``confidence`` from the
                         matching current reading), or ``None``
        ``latest_event`` most recently recorded event, or ``None``

        The unattached case returns the same stable key set with honest
        null/false defaults (mirrors the ``/camera`` ``available: false``
        convention): no hazard layer means *no assessment*, not ``NORMAL``.
        """
        snapshot = self._mgr.hazard_snapshot()
        if snapshot is None:
            return {
                "attached": False,
                "enabled": False,
                "status": None,
                "state": None,
                "severity": "NONE",
                "active": False,
                "latched": False,
                "blocks_motion": False,
                "speed_scale": 1.0,
                "reasons": [],
                "location": None,
                "hazard": None,
                "latest_event": None,
                "active_events": [],
                "recent_events": [],
                "events_recorded": 0,
                "counts_by_kind": {},
                "sources": [],
                "updated_at": None,
            }

        state = HazardState.parse(snapshot.get("state"))
        severity = _STATE_SEVERITY[state]
        active_events = list(snapshot.get("active_events") or [])

        worst = None
        for event in active_events:
            event_severity = HazardSeverity.parse(event.get("severity"))
            if event_severity is HazardSeverity.INFO:
                continue  # INFO never raises state, so it cannot raise severity
            if worst is None or (
                HazardSeverity.parse(worst.get("severity")).rank
                < event_severity.rank
            ):
                worst = event
            if _SEVERITY_RANK[severity] < _SEVERITY_RANK.get(
                event_severity.value, 0
            ):
                severity = event_severity.value

        descriptor = None
        if worst is not None:
            match = None
            worst_key = f"{worst.get('kind')}:{worst.get('source')}"
            hazard = self._mgr.hazard
            readings = hazard.status.readings if hazard is not None else ()
            for reading in readings:
                if reading.key == worst_key:
                    match = reading
                    break
            descriptor = {
                "kind": worst.get("kind"),
                "severity": worst.get("severity"),
                "source": worst.get("source"),
                "message": worst.get("message"),
                "location": worst.get("location"),
                "raised_at": worst.get("raised_at"),
                "value": match.value if match is not None else None,
                "unit": match.unit if match is not None else "",
                "confidence": (
                    match.value
                    if match is not None and match.unit == "confidence"
                    else None
                ),
            }

        recent = list(snapshot.get("recent_events") or [])
        payload = dict(snapshot)
        payload.update(
            {
                "attached": True,
                "severity": severity,
                "active": bool(active_events),
                "hazard": descriptor,
                "latest_event": recent[-1] if recent else None,
            }
        )
        return payload

    def dispatch(self, payload: dict) -> Tuple[dict, int]:
        """Execute one command through the gated manager API."""
        cmd = str(payload.get("cmd", "")).lower()
        with self._lock:
            try:
                if cmd == "estop":
                    self._mgr.estop()
                    return {"ok": True, "mode": self._mgr.state.mode.value}, 200

                if cmd == "stop":
                    self._mgr.stop()
                    return {"ok": True}, 200

                if cmd == "mode":
                    # Accept case-insensitively ("manual" and "MANUAL").
                    target = RobotMode(str(payload.get("mode", "")).upper())
                    mode = self._mgr.request_mode(target)
                    return {"ok": True, "mode": mode.value}, 200

                if cmd in _MOTION:
                    speed = int(payload.get("speed", _MOTION[cmd]))
                    max_speed = self._mgr.drive.max_speed
                    if not (1 <= speed <= max_speed):
                        return {
                            "ok": False,
                            "error": (
                                f"speed {speed} out of range [1, {max_speed}]"
                            ),
                        }, 400
                    getattr(self._mgr, cmd)(speed)
                    return {"ok": True, "cmd": cmd}, 200

                return {"ok": False, "error": f"unknown command: {cmd}"}, 400

            except RobotCommandError as exc:
                return {"ok": False, "error": str(exc)}, 400
            except (KeyError, ValueError, TypeError) as exc:
                return {"ok": False, "error": f"bad payload: {exc}"}, 400
            except Exception as exc:  # noqa: BLE001
                self.log.error("command %s failed: %s", cmd, exc)
                return {"ok": False, "error": str(exc)}, 500


class _Handler(BaseHTTPRequestHandler):
    """Minimal JSON/HTML router.

    ``self.app`` (:class:`AMRWebApp`) is injected by the subclass created in
    :meth:`AMRWebApp.start` — socketserver always constructs the handler with
    exactly ``(request, client_address, server)``.
    """

    app: "AMRWebApp"  # bound per-app in AMRWebApp.start

    def log_message(self, fmt: str, *args) -> None:  # noqa: N802
        pass  # keep the console quiet; use the amr logger instead

    # -- helpers --------------------------------------------------------- #
    def _send_json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_image(self, jpeg: bytes) -> None:
        self._send_bytes(jpeg, "image/jpeg")

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        """Send a binary body with an explicit content type and no caching."""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # -- routes ------------------------------------------------------------ #
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send_html(INDEX_HTML)
        elif path == "/status":
            self._send_json(self.app.snapshot())
        elif path == "/sensor":
            self._send_json(self.app.poll_sensor())
        elif path == "/camera":
            self._send_json(self.app.camera_status())
        elif path == "/camera/status":
            self._send_json(self.app.camera_info())
        elif path == "/camera/frame":
            data, ctype, code = self.app.camera_frame()
            if data is None:
                self._send_json(
                    {"error": "camera frame unavailable", "status": code}, code
                )
            else:
                self._send_bytes(data, ctype)
        elif path == "/hazard":
            self._send_json(self.app.hazard_status())
        elif path == "/telemetry":
            self._send_json(self.app.telemetry_snapshot())
        elif path == "/health":
            body, code = self.app.health()
            self._send_json(body, code)
        elif path == "/dashboard":
            self._send_html(DASHBOARD_HTML)
        elif path == "/image":
            jpeg = self.app.image()
            if jpeg is None:
                self._send_json({"error": "camera unavailable"}, 503)
            else:
                self._send_image(jpeg)
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/hazard/acknowledge":
            # Body is optional (an empty POST must be allowed for a button);
            # when present it must still be a JSON object, like /command.
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length:
                    raw = self.rfile.read(length)
                    parsed = json.loads(raw.decode("utf-8"))
                    if parsed is not None and not isinstance(parsed, dict):
                        raise ValueError("payload must be a JSON object")
            except (ValueError, UnicodeDecodeError) as exc:
                self._send_json({"ok": False, "error": f"bad JSON: {exc}"}, 400)
                return
            result, code = self.app.acknowledge_hazard()
            self._send_json(result, code)
            return
        if self.path != "/command":
            self._send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
        except (ValueError, UnicodeDecodeError) as exc:
            self._send_json({"ok": False, "error": f"bad JSON: {exc}"}, 400)
            return
        result, code = self.app.dispatch(payload)
        self._send_json(result, code)


# --------------------------------------------------------------------------- #
# Control panel (self-contained; no external assets)
# --------------------------------------------------------------------------- #
INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AMR Control</title>
<style>
  :root { --bg:#0f1420; --panel:#1a2233; --line:#2a3550; --text:#e6ecf7;
          --dim:#8b98b8; --ok:#2ecc71; --warn:#f1c40f; --err:#e74c3c; --acc:#4da3ff; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  .wrap { max-width:860px; margin:0 auto; padding:16px; }
  header { display:flex; align-items:center; gap:12px; padding:12px 16px;
           background:var(--panel); border:1px solid var(--line); border-radius:10px; }
  header h1 { font-size:18px; margin:0; letter-spacing:.5px; }
  .badge { padding:3px 10px; border-radius:999px; font-size:12px; font-weight:600;
           background:var(--line); }
  .badge.ok { background:rgba(46,204,113,.18); color:var(--ok); }
  .badge.warn { background:rgba(241,196,15,.18); color:var(--warn); }
  .badge.err { background:rgba(231,76,60,.18); color:var(--err); }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:14px; }
  @media (max-width:680px){ .grid { grid-template-columns:1fr; } }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:10px;
          padding:14px 16px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:1px;
             color:var(--dim); margin:0 0 10px; }
  .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  button { background:#243050; color:var(--text); border:1px solid var(--line);
           border-radius:8px; padding:10px 14px; font-size:14px; cursor:pointer; }
  button:hover { background:#2d3b63; }
  button:active { transform:translateY(1px); }
  button.moving { background:var(--acc); border-color:var(--acc); color:#08101d; font-weight:700; }
  button.estop { background:var(--err); border-color:var(--err); color:#fff;
                 font-weight:800; font-size:16px; padding:12px 22px; }
  button.active-mode { background:var(--ok); border-color:var(--ok);
                       color:#08101d; font-weight:700; }
  input[type=range] { flex:1; min-width:120px; accent-color:var(--acc); }
  .speed-val { min-width:38px; text-align:right; font-variant-numeric:tabular-nums; }
  .sensors { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }
  .sensors div { background:#141b2b; border:1px solid var(--line); border-radius:8px;
                 padding:8px; text-align:center; }
  .sensors .v { font-size:20px; font-weight:700; font-variant-numeric:tabular-nums; }
  .sensors .k { font-size:11px; color:var(--dim); text-transform:uppercase; }
  .kv { display:flex; justify-content:space-between; padding:4px 0;
        border-bottom:1px dashed var(--line); font-size:14px; }
  .kv:last-child { border-bottom:none; }
  .kv span:last-child { font-variant-numeric:tabular-nums; }
  #toast { position:fixed; bottom:14px; left:50%; transform:translateX(-50%);
           background:#2d3b63; border:1px solid var(--line); border-radius:8px;
           padding:8px 16px; opacity:0; transition:opacity .2s; pointer-events:none; }
  #toast.show { opacity:1; }
  #toast.err { background:rgba(231,76,60,.25); border-color:var(--err); }
  .badge.crit { background:var(--err); color:#fff; animation:critblink 1s step-end infinite; }
  @keyframes critblink { 50% { background:#7a1e16; } }
  @media (prefers-reduced-motion:reduce){ .badge.crit { animation:none; } }
  button.ack { background:#5a3a12; border-color:var(--warn); color:var(--warn);
               font-weight:700; }
  button.ack:hover { background:#7a4e18; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>AMR Control</h1>
    <span id="mode" class="badge">--</span>
    <span id="safety" class="badge">--</span>
    <span id="link" class="badge">--</span>
    <span id="hazBadge" class="badge">HAZARD --</span>
  </header>

  <div class="grid">
    <div class="card">
      <h2>Drive</h2>
      <div class="row" style="margin-bottom:10px">
        <span>Speed</span>
        <input type="range" id="speed" min="10" max="255" value="100">
        <span class="speed-val" id="speedVal">100</span>
      </div>
      <div class="row" style="margin-bottom:8px">
        <button data-cmd="forward" style="flex:1">&#9650; Forward</button>
      </div>
      <div class="row" style="margin-bottom:8px">
        <button data-cmd="turn_left" style="flex:1">&#9664; Left</button>
        <button data-cmd="backward" style="flex:1">&#9660; Back</button>
        <button data-cmd="turn_right" style="flex:1">Right &#9654;</button>
      </div>
      <div class="row" style="margin-bottom:10px">
        <button data-cmd="stop" style="flex:1; font-weight:700">&#9632; Stop</button>
      </div>
      <div class="row">
        <button class="estop" data-cmd="estop" style="flex:1">E-STOP</button>
      </div>
    </div>

    <div class="card">
      <h2>Mode</h2>
      <div class="row" style="margin-bottom:10px">
        <button data-mode="idle" style="flex:1">Idle</button>
        <button data-mode="manual" style="flex:1">Manual</button>
        <button data-mode="autonomous" style="flex:1">Autonomous</button>
      </div>
      <h2>Telemetry</h2>
      <div class="kv"><span>Version</span><span id="version">--</span></div>
      <div class="kv"><span>Motors (L / R)</span><span id="motors">--</span></div>
      <div class="kv"><span>Moving</span><span id="moving">--</span></div>
      <div class="kv"><span>Last error</span><span id="lastErr" style="max-width:60%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">--</span></div>
      <h2 style="margin-top:12px">Ultrasonic (cm)</h2>
      <div class="sensors">
        <div><div class="v" id="s-front">--</div><div class="k">front</div></div>
        <div><div class="v" id="s-left">--</div><div class="k">left</div></div>
        <div><div class="v" id="s-right">--</div><div class="k">right</div></div>
        <div><div class="v" id="s-rear">--</div><div class="k">rear</div></div>
      </div>
    </div>

    <div class="card" style="grid-column:1/-1">
      <h2>Hazard (Layer 3.5)</h2>
      <div class="row" style="margin-bottom:8px">
        <span id="hazState" class="badge">--</span>
        <span id="hazSeverity" class="badge">--</span>
        <span id="hazActive" class="badge">--</span>
        <button id="hazAck" class="ack" style="display:none;margin-left:auto">
          Acknowledge hazard
        </button>
      </div>
      <div class="kv"><span>Current hazard</span><span id="hazKind">--</span></div>
      <div class="kv"><span>Confidence</span><span id="hazConf">--</span></div>
      <div class="kv"><span>Source</span><span id="hazSrc">--</span></div>
      <div class="kv"><span>Location</span><span id="hazLoc">--</span></div>
      <div class="kv"><span>Reason</span><span id="hazReason" style="max-width:65%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="">--</span></div>
      <div class="kv"><span>Updated</span><span id="hazTs">--</span></div>
    </div>

    <div class="card" style="grid-column:1/-1">
      <h2>Camera</h2>
      <div class="row">
        <img id="cam" alt="camera view" style="max-width:100%;max-height:260px;
             border-radius:8px;border:1px solid var(--line);display:none">
        <div id="camPlaceholder" style="flex:1;display:flex;align-items:center;
             justify-content:center;min-height:120px;background:#141b2b;
             border:1px dashed var(--line);border-radius:8px;color:var(--dim);
             font-size:13px">camera unavailable</div>
        <span id="camStatus" class="badge">--</span>
      </div>
      <div class="kv" style="margin-top:8px"><span>Device</span><span id="camDevice">--</span></div>
      <div class="kv"><span>Resolution</span><span id="camRes">--</span></div>
    </div>
  </div>
</div>
<div id="toast"></div>

<script>
const $ = (id) => document.getElementById(id);
const speed = () => parseInt($("speed").value, 10);
$("speed").addEventListener("input", () => $("speedVal").textContent = $("speed").value);

function toast(msg, isErr) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "show" + (isErr ? " err" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = ""), 2500);
}

async function send(payload) {
  try {
    const r = await fetch("/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const j = await r.json();
    if (!r.ok || j.ok === false) toast(j.error || ("HTTP " + r.status), true);
    return j;
  } catch (e) {
    toast("network error: " + e, true);
  }
}

document.querySelectorAll("button[data-cmd]").forEach((b) => {
  b.addEventListener("click", () => {
    const cmd = b.dataset.cmd;
    if (cmd === "estop" || cmd === "stop") send({ cmd });
    else send({ cmd, speed: speed() });
  });
});
document.querySelectorAll("button[data-mode]").forEach((b) => {
  b.addEventListener("click", () => send({ cmd: "mode", mode: b.dataset.mode }));
});

async function refresh() {
  try {
    const s = await (await fetch("/status")).json();
    $("mode").textContent = s.mode;
    const saf = (s.safety || "").toUpperCase();
    const sb = $("safety");
    sb.textContent = saf || "--";
    sb.className = "badge " + (saf.startsWith("STOP") ? "err" : saf.startsWith("WAIT") ? "warn" : "ok");
    const lb = $("link");
    lb.textContent = s.connected ? "LINK OK" : "LINK DOWN";
    lb.className = "badge " + (s.connected ? "ok" : "err");
    $("version").textContent = s.version || "--";
    $("motors").textContent = s.left_speed + " / " + s.right_speed;
    $("moving").textContent = s.is_moving ? "yes" : "no";
    $("lastErr").textContent = s.last_error || "--";
    $("lastErr").title = s.last_error || "";
    for (const k of ["front", "left", "right", "rear"]) {
      const v = s[k + "_cm"];
      $("s-" + k).textContent = v === null || v === undefined ? "--" : v;
    }
    document.querySelectorAll("button[data-mode]").forEach((b) =>
      b.classList.toggle("active-mode", b.dataset.mode === s.mode.toLowerCase()));
  } catch (e) { /* server restarting */ }
}
setInterval(refresh, 500);
refresh();

async function refreshCam() {
  try {
    const c = await (await fetch("/camera")).json();
    $("camDevice").textContent = c.device || "--";
    $("camRes").textContent = c.resolution || "--";
    const on = !!(c.available);
    const sb = $("camStatus");
    sb.textContent = c.status || (on ? "ONLINE" : "OFFLINE");
    sb.className = "badge " + (on ? "ok" : "warn");
    const img = $("cam");
    if (on) {
      img.style.display = "";
      $("camPlaceholder").style.display = "none";
      img.src = "/image?ts=" + Date.now();
    } else {
      img.style.display = "none";
      $("camPlaceholder").style.display = "";
    }
  } catch (e) { /* server restarting */ }
}
setInterval(refreshCam, 2000);
refreshCam();

async function refreshHazard() {
  try {
    const h = await (await fetch("/hazard")).json();
    const hb = $("hazBadge");
    if (!h.attached) {
      hb.textContent = "HAZARD OFF";
      hb.className = "badge";
      $("hazState").textContent = "not attached";
      $("hazState").className = "badge";
      $("hazSeverity").textContent = "--";
      $("hazSeverity").className = "badge";
      $("hazActive").textContent = "--";
      $("hazActive").className = "badge";
      $("hazKind").textContent = "--";
      $("hazConf").textContent = "--";
      $("hazSrc").textContent = "--";
      $("hazLoc").textContent = "--";
      $("hazReason").textContent = "--";
      $("hazReason").title = "";
      $("hazTs").textContent = "--";
      $("hazAck").style.display = "none";
      return;
    }
    const st = (h.state || "").toUpperCase();
    const sev = (h.severity || "").toUpperCase();
    const stateCls = st === "NORMAL" ? "ok"
                   : (st === "WARNING" || st === "SLOW") ? "warn" : "crit";
    const sevCls = sev === "CRITICAL" ? "crit"
                 : sev === "WARNING" ? "warn" : "ok";
    hb.textContent = "HAZARD " + st + (h.latched ? " (LATCHED)" : "");
    hb.className = "badge " + stateCls;
    $("hazState").textContent = st + (h.latched ? " (LATCHED)" : "");
    $("hazState").className = "badge " + stateCls;
    $("hazSeverity").textContent = sev;
    $("hazSeverity").className = "badge " + sevCls;
    const act = !!h.active;
    $("hazActive").textContent = act ? "ACTIVE" : "clear";
    $("hazActive").className = "badge " + (act ? "warn" : "ok");
    const d = h.hazard;
    $("hazKind").textContent = d ? (d.kind || "--") : (h.reasons.length ? "latched" : "none");
    $("hazConf").textContent = (d && d.confidence !== null && d.confidence !== undefined)
      ? d.confidence.toFixed(2) : "--";
    $("hazSrc").textContent = d && d.source ? d.source : "--";
    const loc = d && d.location ? d.location : h.location;
    $("hazLoc").textContent = loc
      ? (loc.x.toFixed(2) + ", " + loc.y.toFixed(2) + (loc.zone ? " [" + loc.zone + "]" : ""))
      : "--";
    const reason = (h.reasons || []).join("; ");
    $("hazReason").textContent = reason || "--";
    $("hazReason").title = reason;
    $("hazTs").textContent = h.updated_at ? new Date(h.updated_at * 1000).toLocaleTimeString() : "--";
    $("hazAck").style.display = h.latched ? "" : "none";
  } catch (e) { /* server restarting */ }
}
setInterval(refreshHazard, 1000);
refreshHazard();

$("hazAck").addEventListener("click", async () => {
  try {
    const r = await fetch("/hazard/acknowledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const j = await r.json();
    if (!r.ok || j.ok === false) { toast(j.error || ("HTTP " + r.status), true); return; }
    if (j.latched) {
      toast("acknowledged, but the hazard is STILL ACTIVE — emergency remains latched", true);
    } else {
      toast("hazard latch acknowledged — use Mode → Idle to leave SAFETY_STOP");
    }
    refreshHazard();
  } catch (e) { toast("network error: " + e, true); }
});
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# C7 monitoring dashboard (read-only; self-contained; no external assets)
# --------------------------------------------------------------------------- #
# A deliberately minimal control center: it *reads* GET /telemetry and GET /health
# and renders what it receives. It has no form, no button and no fetch() with a
# method other than GET, so the page contains no motor-control path at all.
DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AMR Control Center</title>
<style>
:root {
  --bg: #0e1420; --card: #161f2e; --line: #263247; --ink: #e6edf6;
  --dim: #8b9bb4; --ok: #3fb950; --warn: #d29922; --crit: #f85149;
  --sim: #a371f7;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
header { padding: 14px 20px; border-bottom: 1px solid var(--line);
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
h1 { font-size: 17px; margin: 0; letter-spacing: .06em; }
.badge { padding: 3px 10px; border-radius: 999px; font-size: 11px;
  font-weight: 700; letter-spacing: .08em; border: 1px solid currentColor; }
.b-ok { color: var(--ok); } .b-warn { color: var(--warn); }
.b-crit { color: var(--crit); } .b-sim { color: var(--sim); }
.b-dim { color: var(--dim); }
main { padding: 20px; display: grid; gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
.card { background: var(--card); border: 1px solid var(--line);
  border-radius: 10px; padding: 14px 16px; }
.card h2 { font-size: 11px; margin: 0 0 10px; color: var(--dim);
  text-transform: uppercase; letter-spacing: .12em; }
.kv { display: grid; grid-template-columns: auto 1fr; gap: 4px 14px; }
.kv dt { color: var(--dim); } .kv dd { margin: 0; text-align: right;
  font-variant-numeric: tabular-nums; }
ul { margin: 0; padding-left: 18px; } li { margin: 2px 0; }
.empty { color: var(--dim); font-style: italic; }
/* C8 camera panel. The preview is capped by max-width/height so a 1280x720
   frame cannot blow out the grid, and the aspect ratio is fixed so the card
   does not jump while frames arrive. */
.cam-card { display: flex; flex-direction: column; }
.cam-view { background: #0b101a; border: 1px solid var(--line); border-radius: 8px;
  aspect-ratio: 4 / 3; display: flex; align-items: center; justify-content: center;
  overflow: hidden; margin-bottom: 10px; }
.cam-view img { max-width: 100%; max-height: 100%; width: auto; height: auto;
  display: block; object-fit: contain; }
.cam-none { color: var(--dim); font-style: italic; font-size: 12px; }
footer { padding: 10px 20px 24px; color: var(--dim); font-size: 12px; }
a { color: var(--sim); }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; } }
</style>
</head>
<body>
<header>
  <h1>AMR CONTROL CENTER</h1>
  <span id="mode" class="badge b-dim">MODE &mdash;</span>
  <span id="sim" class="badge b-dim">SOURCE &mdash;</span>
  <span id="conn" class="badge b-dim">CONNECTING</span>
</header>

<main>
  <section class="card">
    <h2>Robot</h2>
    <dl class="kv">
      <dt>Connection</dt><dd id="r-conn">&mdash;</dd>
      <dt>Mode</dt><dd id="r-mode">&mdash;</dd>
      <dt>Position (m)</dt><dd id="r-pos">&mdash;</dd>
      <dt>Yaw</dt><dd id="r-yaw">&mdash;</dd>
      <dt>Velocity</dt><dd id="r-vel">&mdash;</dd>
    </dl>
  </section>

  <section class="card">
    <h2>Navigation</h2>
    <dl class="kv">
      <dt>State</dt><dd id="n-state">&mdash;</dd>
      <dt>Goal</dt><dd id="n-goal">&mdash;</dd>
      <dt>Progress</dt><dd id="n-prog">&mdash;</dd>
    </dl>
  </section>

  <section class="card">
    <h2>Safety</h2>
    <dl class="kv">
      <dt>State</dt><dd id="s-state">&mdash;</dd>
      <dt>Action</dt><dd id="s-action">&mdash;</dd>
      <dt>E-STOP</dt><dd id="s-estop">&mdash;</dd>
    </dl>
  </section>

  <section class="card">
    <h2>Battery</h2>
    <dl class="kv">
      <dt>Status</dt><dd id="b-state">&mdash;</dd>
      <dt>Percentage</dt><dd id="b-pct">&mdash;</dd>
      <dt>Voltage</dt><dd id="b-volt">&mdash;</dd>
    </dl>
  </section>

  <section class="card">
    <h2>Sensors</h2>
    <ul id="sensors"><li class="empty">none reported</li></ul>
  </section>

  <section class="card">
    <h2>Hazards</h2>
    <ul id="hazards"><li class="empty">none active</li></ul>
  </section>

  <section class="card">
    <h2>Mission</h2>
    <dl class="kv">
      <dt>Mission</dt><dd id="m-id">&mdash;</dd>
      <dt>Task</dt><dd id="m-task">&mdash;</dd>
      <dt>Completed</dt><dd id="m-done">&mdash;</dd>
    </dl>
  </section>

  <section class="card cam-card">
    <h2>Camera</h2>
    <div class="cam-view">
      <img id="c-img" alt="Latest camera frame" hidden>
      <div id="c-none" class="cam-none">no frame available</div>
    </div>
    <dl class="kv">
      <dt>Status</dt><dd id="c-state">&mdash;</dd>
      <dt>Source</dt><dd id="c-src">&mdash;</dd>
      <dt>Resolution</dt><dd id="c-res">&mdash;</dd>
      <dt>Frame</dt><dd id="c-frame">&mdash;</dd>
    </dl>
  </section>

  <section class="card">
    <h2>System</h2>
    <dl class="kv">
      <dt>Uptime</dt><dd id="y-up">&mdash;</dd>
      <dt>Software</dt><dd id="y-ver">&mdash;</dd>
      <dt>Schema</dt><dd id="y-schema">&mdash;</dd>
    </dl>
  </section>
</main>

<footer>
  Read-only monitoring. This page issues GET requests only and has no motor
  control path. Legacy control panel: <a href="/">/</a>.
</footer>
__DASHBOARD_JS__
</body>
</html>
"""

DASHBOARD_JS = """<script>
"use strict";
// Read-only: this file only ever calls GET. No POST, no command endpoint.
var POLL_MS = 1000;

function txt(id, v) { document.getElementById(id).textContent = v; }
function num(v, d) { return (typeof v === "number") ? v.toFixed(d) + " m" : "not available"; }
function src(v) { return '<span class="badge b-dim">' + v + "</span>"; }

function renderSensors(s) {
  var ul = document.getElementById("sensors");
  var out = [];
  for (var i = 0; i < s.ultrasonic.length; i++) {
    var u = s.ultrasonic[i];
    var d = (u.distance_cm === null || u.distance_cm === undefined)
      ? "no reading" : u.distance_cm + " cm";
    out.push("<li>" + u.position + " &middot; " + d + " " + src(u.source) + "</li>");
  }
  ul.innerHTML = out.length ? out.join("") : '<li class="empty">none reported</li>';
}

function renderHazards(h) {
  var ul = document.getElementById("hazards");
  var out = [];
  for (var i = 0; i < h.active.length; i++) {
    var a = h.active[i];
    var cls = a.severity === "CRITICAL" ? "b-crit" : "b-warn";
    var loc = a.location
      ? " @ (" + a.location.x + ", " + a.location.y + ")"
      : " @ location not supplied";
    out.push('<li><span class="badge ' + cls + '">' + a.kind + "</span> "
      + " " + a.severity + " &middot; " + a.source + loc + "</li>");
  }
  ul.innerHTML = out.length ? out.join("") : '<li class="empty">none active</li>';
}

// C8: single-frame retrieval, not a continuous media stream. The image is
// fetched as a blob and swapped via object URL so the page never re-downloads
// identical bytes every tick; the previous URL is revoked to avoid leaking.
var FRAME_MS = 1000;
var lastFrameUrl = null;
var lastFrameId = null;

function showNoFrame() {
  var img = document.getElementById("c-img");
  var none = document.getElementById("c-none");
  if (img) { img.hidden = true; img.removeAttribute("src"); }
  if (none) { none.hidden = false; }
  if (lastFrameUrl) { URL.revokeObjectURL(lastFrameUrl); lastFrameUrl = null; }
  lastFrameId = null;
}

function pollFrame() {
  fetch("/camera/frame", { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) { throw new Error("HTTP " + r.status); }
      return r.blob();
    })
    .then(function (blob) {
      if (!blob || blob.size === 0) { throw new Error("empty frame"); }
      if (lastFrameUrl) { URL.revokeObjectURL(lastFrameUrl); }
      lastFrameUrl = URL.createObjectURL(blob);
      var img = document.getElementById("c-img");
      img.src = lastFrameUrl;
      img.hidden = false;
      var none = document.getElementById("c-none");
      if (none) { none.hidden = true; }
    })
    .catch(function () { showNoFrame(); });
}

function apply(t) {
  var sim = !!t.simulated;
  var simB = document.getElementById("sim");
  simB.textContent = sim ? "SIMULATION" : "LIVE HARDWARE";
  simB.className = "badge " + (sim ? "b-sim" : "b-ok");

  var mode = t.system.mode;
  txt("mode", mode);
  txt("r-mode", mode);
  var modeCls = "b-dim";
  if (mode === "SAFETY_STOP" || mode === "ERROR") { modeCls = "b-crit"; }
  else if (mode === "AUTONOMOUS" || mode === "MANUAL") { modeCls = "b-ok"; }
  document.getElementById("mode").className = "badge " + modeCls;

  txt("r-conn", t.system.connected ? "connected" : "not connected");
  txt("r-pos", num(t.position.x, 2) + ", " + num(t.position.y, 2));
  txt("r-yaw", typeof t.orientation.yaw === "number"
    ? t.orientation.yaw.toFixed(2) + " rad" : "not available");
  txt("r-vel", num(t.velocity.linear, 2) + " / " + num(t.velocity.angular, 2));

  txt("n-state", t.navigation.state);
  txt("n-goal", t.navigation.current_goal || "none");
  txt("n-prog", typeof t.navigation.progress === "number"
    ? t.navigation.progress.toFixed(2) : "not available");

  txt("s-state", t.safety.state);
  txt("s-action", t.safety.action);
  txt("s-estop", t.safety.emergency_stop ? "ACTIVE" : "clear");

  // Battery is UNAVAILABLE until real hardware reports it: render the source
  // tag rather than inventing a "state" the contract does not define.
  var batAvail = t.battery.source !== "UNAVAILABLE";
  txt("b-state", batAvail ? t.battery.source : "not connected");
  txt("b-pct", t.battery.percentage === null
    ? "not available" : t.battery.percentage + " %");
  txt("b-volt", t.battery.voltage === null
    ? "not available" : t.battery.voltage + " V");

  renderSensors(t.sensors);
  renderHazards(t.hazards);

  txt("m-id", t.mission.mission_id || "none");
  txt("m-task", t.mission.current_task || "none");
  txt("m-done", t.mission.completed_tasks);

  // C8 camera panel. The status badge is driven by telemetry (the contract
  // that knows what is really behind the lens) and the image is fetched
  // separately from /camera/frame, so a failed capture cannot break the rest
  // of the page.
  txt("c-state", t.camera.status || "UNAVAILABLE");
  txt("c-src", (t.camera.source_name || "none")
    + (t.camera.source ? " (" + t.camera.source + ")" : ""));
  txt("c-res", (t.camera.width && t.camera.height)
    ? t.camera.width + " × " + t.camera.height
    : "not available");
  txt("c-frame", typeof t.camera.frame_id === "number" && t.camera.frame_id > 0
    ? "#" + t.camera.frame_id : "no frame yet");

  // Only LIVE and SIMULATION can produce an image. UNAVAILABLE / ERROR show the
  // placeholder, so the panel never implies a picture it does not have.
  var camOk = (t.camera.status === "LIVE" || t.camera.status === "SIMULATION");
  if (camOk) { pollFrame(); } else { showNoFrame(); }

  txt("y-up", typeof t.system.uptime === "number"
    ? Math.round(t.system.uptime) + " s" : "not available");
  txt("y-ver", t.system.software_version);
  txt("y-schema", t.schema_version);
}

function poll() {
  fetch("/telemetry", { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) { throw new Error("HTTP " + r.status); }
      return r.json();
    })
    .then(function (t) {
      apply(t);
      var c = document.getElementById("conn");
      c.textContent = "LIVE FEED";
      c.className = "badge b-ok";
    })
    .catch(function (e) {
      var c = document.getElementById("conn");
      c.textContent = "NO DATA";
      c.className = "badge b-crit";
    });
}

poll();
setInterval(poll, POLL_MS);
</script>"""

# Substitute the JS token once, at import time, so the served document is a
# single self-contained HTML string with no templating left on the wire.
DASHBOARD_HTML = DASHBOARD_HTML.replace("__DASHBOARD_JS__", DASHBOARD_JS)

