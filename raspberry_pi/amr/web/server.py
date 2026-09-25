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
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

from ..camera import CameraManager
from ..camera.frame import CameraFrame, CameraStatus
from ..hazard import HazardSeverity, HazardState
from ..logging import get_logger
from ..map import MapService, build_twin_state
from ..robot import RobotCommandError, RobotManager
from ..robot.robot_state import RobotMode
from ..telemetry import TelemetryCollector, build_console_state
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


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    """Parse a bounded int query parameter, ignoring anything malformed.

    A browser (or a curious operator) sending ``?width=abc`` must not 500 the
    dashboard, so bad input falls back to the default and is then clamped.
    """
    try:
        return max(low, min(high, int(float(value))))
    except (TypeError, ValueError):
        return default


def _clamp_float(value: Any, default: float, low: float, high: float) -> float:
    """Parse a bounded float query parameter; see :func:`_clamp_int`."""
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# C9 helpers — read geometry from the EXISTING runtime, never a second source
# --------------------------------------------------------------------------- #
def _warehouse_locations(warehouse: Any) -> Dict[str, Any]:
    """Warehouse waypoints from the existing warehouse object/config.

    Accepts a ``WarehouseTaskManager`` (which owns a ``WarehouseMap``), a
    ``WarehouseMap``, or the raw ``locations`` mapping. Returns ``{}`` when no
    warehouse is attached, which the map reports as UNAVAILABLE rather than
    inventing a floor plan.
    """
    if warehouse is None:
        return {}
    for attr in ("map", "warehouse_map", "_map"):
        mapping = getattr(warehouse, attr, None)
        if mapping is not None and hasattr(mapping, "names"):
            return {name: mapping.pose(name) for name in mapping.names()}
    locations = getattr(warehouse, "locations", None)
    return dict(locations) if isinstance(locations, dict) else {}


def _hazard_zones(mgr: RobotManager) -> Tuple[Any, ...]:
    """Hazard-zone rectangles from the attached hazard layer (C5).

    The zones are the only *rectangular* world geometry the project actually
    models, so they are the only static shapes the map can honestly draw.
    """
    layer = getattr(mgr, "hazard", None)
    if layer is None:
        return ()
    try:
        # `HazardManager.sources` is a property, but other managers expose a
        # method; accept both shapes like the telemetry collector does.
        sources = getattr(layer, "sources", None)
        sources = sources() if callable(sources) else (sources or ())
        for source in sources:
            getter = getattr(source, "zones", None)
            zones = getter() if callable(getter) else getter
            if zones:
                return tuple(zones)
    except Exception:  # noqa: BLE001 - a zone lookup failure just means no zones
        return ()
    return ()


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
        # C9 map: a read-only projection of the SAME runtime. It is built from
        # this app's own collaborators so the map can never be wired to a
        # different robot than the one the panel is describing. Static geometry
        # is taken from the existing warehouse config; hazard zones from the
        # attached hazard layer. Both are optional and degrade to UNAVAILABLE.
        self.map = MapService(
            locations=_warehouse_locations(warehouse),
            zones=_hazard_zones(mgr),
            navigator=navigator,
            hazard_layer=getattr(mgr, "hazard", None),
            telemetry=self.telemetry,
            simulated=simulated,
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
    # C9 — 2D warehouse map (read-only)
    # ------------------------------------------------------------------ #
    def map_snapshot(self) -> dict:
        """Current map state for ``GET /map``.

        A pure projection of the existing warehouse/navigator/hazard/telemetry
        state. The browser is never asked to derive map semantics: it receives
        world coordinates and renders them. The bounded path history lives in the
        :class:`MapService`, so repeated polling cannot grow memory.
        """
        with self._lock:
            return self.map.as_dict()

    def map_svg(self, width: int = 720, height: int = 460,
                zoom: float = 1.0) -> Tuple[Optional[str], int]:
        """Server-rendered SVG for ``GET /map.svg``.

        Returns ``(svg, http_status)``. A runtime with no placeable geometry
        still yields a valid SVG carrying an explicit "no map data" message
        rather than an error.
        """
        with self._lock:
            try:
                return self.map.svg(int(width), int(height), zoom=zoom), 200
            except Exception as exc:  # noqa: BLE001 - map must not kill the panel
                self.log.warning("map render failed: %s", exc)
                return None, 503

    def digital_twin(self) -> dict:
        """3D twin scene state for ``GET /digital-twin``.

        Derived from the very same :class:`MapSnapshot` the 2D map renders, so
        the two views cannot disagree: if ``MapSnapshot.robot`` moves, both the
        2D marker and the 3D AMR move. Read-only — this builds a *description*
        of the scene and never touches an actuator.
        """
        with self._lock:
            snap = self.map.snapshot()
            return build_twin_state(
                snap, telemetry=self.telemetry, camera=self._camera).to_dict()

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

    def console_state(self) -> dict:
        """Consolidated read-only operations payload for ``GET /dashboard/state``.

        One request instead of four: the C7 telemetry snapshot, the C7 health
        summary, and the C9 map + C10 twin projections, assembled by
        :func:`amr.telemetry.console.build_console_state`.

        Like every other handler here it only *reads* — it never calls
        ``tick()``, dispatches a command, or touches an actuator. The map and
        twin payloads are included unmodified, so the 2D and 3D views keep
        consuming exactly what they consumed before C11.
        """
        with self._lock:
            return build_console_state(
                self.telemetry.snapshot(),
                health=self.telemetry.health(),
                map_snapshot=self.map.snapshot().to_dict(),
                twin=build_twin_state(
                    self.map.snapshot(),
                    telemetry=self.telemetry,
                    camera=self._camera).to_dict(),
            )

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
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
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
        elif path == "/map":
            # C9: the read-only map projection. World coordinates only; the
            # browser renders, it does not compute map semantics.
            self._send_json(self.app.map_snapshot())
        elif path == "/digital-twin":
            # C10: the 3D twin, derived from that same MapSnapshot.
            self._send_json(self.app.digital_twin())
        elif path == "/dashboard/state":
            # C11: one read-only fetch carrying telemetry + health + the C9 map
            # and C10 twin payloads, so the 1 Hz page load drops from four
            # requests to one. No new state model: every section is the existing
            # projection, and `map` / `twin` are the untouched C9/C10 payloads.
            self._send_json(self.app.console_state())
        elif path == "/map.svg":
            params = dict(urllib.parse.parse_qsl(query))
            width = _clamp_int(params.get("width"), 720, 240, 2000)
            height = _clamp_int(params.get("height"), 460, 200, 1600)
            zoom = _clamp_float(params.get("zoom"), 1.0, 0.1, 10.0)
            svg, code = self.app.map_svg(width, height, zoom)
            if svg is None:
                self._send_json({"error": "map unavailable"}, code)
            else:
                self._send_bytes(svg.encode("utf-8"), "image/svg+xml")
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
/* C9 map panel. The SVG scales with preserveAspectRatio, so the viewBox stays
   authoritative and the card never hard-codes pixel geometry. */
.map-card { display: flex; flex-direction: column; }
.map-toolbar { display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
  margin-bottom: 8px; }
.map-btn { background: #16202f; color: var(--text); border: 1px solid var(--line);
  border-radius: 6px; font-size: 11px; padding: 4px 8px; cursor: pointer; }
.map-btn[aria-pressed="true"] { border-color: var(--ok); color: var(--ok); }
.map-view { position: relative; background: #0b101a; border: 1px solid var(--line);
  border-radius: 8px; overflow: hidden; aspect-ratio: 720 / 460; }
.map-view svg { display: block; width: 100%; height: 100%; }
.map-empty { position: absolute; inset: 0; display: flex; align-items: center;
  justify-content: center; color: var(--dim); font-style: italic; font-size: 12px; }
.map-note { color: var(--dim); font-size: 11px; margin: 8px 0 0; }
/* C11 operations console. A dense, scannable status strip plus panel groups;
   deliberately no framework and no animation beyond the existing hazard blink. */
.opsbar { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 14px; }
.ops-item { flex: 1 1 130px; display: flex; flex-direction: column;
  gap: 2px; background: var(--card, #11161f); border: 1px solid var(--line);
  border-radius: 8px; padding: 7px 10px; min-width: 0; }
.ops-k { font-size: 10px; letter-spacing: .08em; color: var(--dim); }
.ops-v { font-size: 14px; font-weight: 600; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.ops-v.b-crit { color: #f87171; } .ops-v.b-warn { color: #fbbf24; }
.ops-v.b-ok { color: #4ade80; } .ops-v.b-sim { color: #38bdf8; }
.ops-v.b-dim { color: var(--dim); }
.group-title { grid-column: 1 / -1; font-size: 11px; letter-spacing: .08em;
  color: var(--dim); margin: 6px 0 -4px; }
.bar { display: flex; gap: 2px; margin-top: 4px; }
.bar i { flex: 1; height: 6px; border-radius: 2px; background: #223; }
.bar i.on { background: #38bdf8; }
.bar i.crit { background: #f87171; }
.mini { font-size: 11px; color: var(--dim); margin-top: 4px; }
.health-row { display: flex; justify-content: space-between; gap: 8px;
  font-size: 12px; padding: 2px 0; }
.health-row .h-name { color: var(--dim); }
/* C10 twin panel. The canvas is sized by CSS so the WebGL viewport follows the
   card; the drawing buffer is resized in JS whenever the CSS size changes. */
.twin-card { display: flex; flex-direction: column; }
.twin-view { position: relative; background: #070b12; border: 1px solid var(--line);
  border-radius: 8px; overflow: hidden; aspect-ratio: 4 / 3; }
.twin-view canvas { display: block; width: 100%; height: 100%; touch-action: none; }
.twin-legend { position: absolute; left: 8px; bottom: 8px; font-size: 10px;
  color: #94a3b8; background: rgba(7, 11, 18, .72); padding: 6px 8px;
  border-radius: 6px; line-height: 1.5; pointer-events: none; }
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

<!-- C11: global operations status bar. One glance: source, robot, navigation,
     safety, mission. Every value is bound to a span and refreshed from the
     console payload; nothing here is hard-coded. -->
<div class="opsbar" role="group" aria-label="Operations status">
  <div class="ops-item"><span class="ops-k">SOURCE</span>
    <span class="ops-v" id="o-source">&mdash;</span></div>
  <div class="ops-item"><span class="ops-k">ROBOT</span>
    <span class="ops-v" id="o-robot">&mdash;</span></div>
  <div class="ops-item"><span class="ops-k">NAVIGATION</span>
    <span class="ops-v" id="o-nav">&mdash;</span></div>
  <div class="ops-item"><span class="ops-k">SAFETY</span>
    <span class="ops-v" id="o-safety">&mdash;</span></div>
  <div class="ops-item"><span class="ops-k">MISSION</span>
    <span class="ops-v" id="o-mission">&mdash;</span></div>
  <div class="ops-item"><span class="ops-k">HAZARDS</span>
    <span class="ops-v" id="o-hazards">&mdash;</span></div>
</div>

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
    <div id="s-extra"></div>
  </section>

  <section class="card">
    <h2>Battery</h2>
    <dl class="kv">
      <dt>Status</dt><dd id="b-state">&mdash;</dd>
      <dt>Percentage</dt><dd id="b-pct">&mdash;</dd>
      <dt>Voltage</dt><dd id="b-volt">&mdash;</dd>
      <dt>Charging</dt><dd id="b-chg">&mdash;</dd>
    </dl>
    <p class="mini" id="b-note">&mdash;</p>
  </section>

  <section class="card">
    <h2>Sensors</h2>
    <ul id="sensors"><li class="empty">none reported</li></ul>
  </section>

  <section class="card">
    <h2>System health</h2>
    <div id="health"><p class="empty">not reported</p></div>
    <p class="mini" id="y-note">&mdash;</p>
  </section>

  <section class="card">
    <h2>Hazards</h2>
    <ul id="hazards"><li class="empty">none active</li></ul>
  </section>

  <section class="card">
    <h2>Mission</h2>
    <dl class="kv">
      <dt>State</dt><dd id="m-state">&mdash;</dd>
      <dt>Mission</dt><dd id="m-id">&mdash;</dd>
      <dt>Task</dt><dd id="m-task">&mdash;</dd>
      <dt>Task status</dt><dd id="m-status">&mdash;</dd>
      <dt>Queued</dt><dd id="m-queued">&mdash;</dd>
      <dt>Completed</dt><dd id="m-done">&mdash;</dd>
      <dt>Failed</dt><dd id="m-fail">&mdash;</dd>
    </dl>
    <!-- Progress is drawn only when the runtime can supply a real value.
         The bar stays empty (and the caption says so) otherwise. -->
    <div class="bar" id="m-bar" aria-hidden="true"></div>
    <p class="mini" id="m-note">&mdash;</p>
  </section>

  <section class="card">
    <h2>Goal &amp; route</h2>
    <dl class="kv">
      <dt>Goal</dt><dd id="g-name">&mdash;</dd>
      <dt>State</dt><dd id="g-state">&mdash;</dd>
      <dt>Route points</dt><dd id="g-points">&mdash;</dd>
      <dt>Progress</dt><dd id="g-prog">&mdash;</dd>
    </dl>
    <p class="mini" id="g-note">&mdash;</p>
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

  <section class="card map-card">
    <h2>Live 2D Warehouse Map</h2>
    <div class="map-toolbar">
      <span id="m-src" class="badge b-dim">SOURCE &mdash;</span>
      <span id="m-safety" class="badge b-dim">SAFETY &mdash;</span>
      <button type="button" id="m-follow" class="map-btn" aria-pressed="false">Follow</button>
      <button type="button" id="m-fit" class="map-btn">Reset view</button>
      <button type="button" id="m-toggle" class="map-btn" aria-pressed="true">Labels</button>
    </div>
    <div class="map-view">
      <svg id="m-svg" viewBox="0 0 720 460" preserveAspectRatio="xMidYMid meet"
           role="img" aria-label="Warehouse map"></svg>
      <div id="m-empty" class="map-empty" hidden>no map data available</div>
    </div>
    <dl class="kv">
      <dt>Robot</dt><dd id="m-robot">&mdash;</dd>
      <dt>Goal</dt><dd id="m-goal">&mdash;</dd>
      <dt>Route</dt><dd id="m-route">&mdash;</dd>
      <dt>Hazards</dt><dd id="m-hazards">&mdash;</dd>
      <dt>Unplaced</dt><dd id="m-unplaced">&mdash;</dd>
    </dl>
    <p class="map-note" id="m-note"></p>
  </section>

  <section class="card twin-card">
    <h2>3D Digital Twin</h2>
    <div class="map-toolbar">
      <span id="t-src" class="badge b-dim">SOURCE &mdash;</span>
      <span id="t-safety" class="badge b-dim">SAFETY &mdash;</span>
      <span id="t-mission" class="badge b-dim">MISSION &mdash;</span>
      <button type="button" id="t-iso" class="map-btn">Isometric</button>
      <button type="button" id="t-top" class="map-btn">Top</button>
      <button type="button" id="t-front" class="map-btn">Front</button>
      <button type="button" id="t-reset" class="map-btn">Reset view</button>
      <button type="button" id="t-follow" class="map-btn" aria-pressed="false">Follow</button>
      <button type="button" id="t-route" class="map-btn" aria-pressed="true">Route</button>
      <button type="button" id="t-path" class="map-btn" aria-pressed="true">Path</button>
      <button type="button" id="t-haz" class="map-btn" aria-pressed="true">Hazards</button>
      <button type="button" id="t-labels" class="map-btn" aria-pressed="true">Labels</button>
    </div>
    <div class="twin-view">
      <canvas id="t-canvas" aria-label="3D digital twin of the AMR"></canvas>
      <div id="t-fallback" class="map-empty" hidden>
        3D rendering is unavailable in this browser (WebGL not supported).
        The 2D map and all telemetry above remain fully functional.
      </div>
      <div id="t-legend" class="twin-legend" hidden></div>
    </div>
    <dl class="kv">
      <dt>Robot</dt><dd id="t-robot">&mdash;</dd>
      <dt>Goal</dt><dd id="t-goal">&mdash;</dd>
      <dt>Hazards</dt><dd id="t-hazards">&mdash;</dd>
      <dt>Unplaced</dt><dd id="t-unplaced">&mdash;</dd>
      <dt>Geometry</dt><dd id="t-geo">&mdash;</dd>
    </dl>
    <p class="map-note" id="t-note"></p>
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
// ------------------------------------------------------------------------ //
// C10 — 3D DIGITAL TWIN. READ-ONLY: this only ever issues GET /digital-twin.
//
// Raw WebGL, no Three.js and no build step. That is a deliberate choice: the
// project ships zero frontend dependencies and must run from one self-contained
// Python process on a Raspberry Pi with no npm, no CDN and no network. WebGL is
// built into every browser, so a small hand-written renderer is both lighter
// and more portable here.
//
// The scene arrives already in renderer coordinates. The world -> 3D mapping
// (three.x = world.x, three.y = -world.y, rotation_z = -yaw) is done ONCE on the
// server in amr/map/twin.py and unit tested there; this file only consumes it,
// so the 2D and 3D views can never disagree about where the robot is.
// ------------------------------------------------------------------------ //
var TWIN = {
  state: null, gl: null, canvas: null,
  yaw: 0.9, pitch: 0.62, dist: 9.0,
  target: [0, 0, 0],
  showRoute: true, showPath: true, showHazards: true, showLabels: true,
  follow: false, dragging: false, lx: 0, ly: 0,
  ready: false, labelAt: []
};

// NOTE: the join below uses an escaped backslash-n. This document is a Python
// string, so a bare one would become a real newline inside the JS string
// literal and break the entire dashboard script.
var T_VS = [
  "attribute vec3 aPos;",
  "attribute vec3 aCol;",
  "uniform mat4 uMVP;",
  "varying vec3 vCol;",
  "void main(){ vCol = aCol; gl_Position = uMVP * vec4(aPos, 1.0); }"
].join("\\n");

var T_FS = [
  "precision mediump float;",
  "varying vec3 vCol;",
  "uniform float uAlpha;",
  "void main(){ gl_FragColor = vec4(vCol, uAlpha); }"
].join("\\n");

function tCompile(gl, type, src) {
  var s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    // Surface the real reason rather than rendering a blank canvas silently.
    console.error("twin shader:", gl.getShaderInfoLog(s));
    return null;
  }
  return s;
}

// -- tiny matrix helpers (column-major, WebGL order) --------------------- //
function tMul(a, b) {
  var o = new Float32Array(16);
  for (var c = 0; c < 4; c++) {
    for (var r = 0; r < 4; r++) {
      o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] +
                     a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
    }
  }
  return o;
}
function tPersp(fovy, aspect, near, far) {
  var f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
  return new Float32Array([f / aspect,0,0,0, 0,f,0,0,
                           0,0,(far + near) * nf,-1, 0,0,2 * far * near * nf,0]);
}
function tLookAt(eye, at, up) {
  var z = tNorm(tSub(eye, at));
  var x = tNorm(tCross(up, z));
  var y = tCross(z, x);
  return new Float32Array([
    x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0,
    -tDot(x, eye), -tDot(y, eye), -tDot(z, eye), 1]);
}
function tSub(a, b) { return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]; }
function tCross(a, b) {
  return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
}
function tDot(a, b) { return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; }
function tNorm(v) {
  var l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0]/l, v[1]/l, v[2]/l];
}
function tRotZ(deg) {
  var a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
  // 2D rotation embedded in the z plane, then translated by the caller.
  return [c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
}
function tTrans(x, y, z) {
  return new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, x,y,z,1]);
}
function tScale(x, y, z) {
  return new Float32Array([x,0,0,0, 0,y,0,0, 0,0,z,0, 0,0,0,1]);
}

// -- primitive geometry (position + colour, triangle soup) --------------- //
function tBox(sx, sy, sz, col, m) {
  var hx = sx / 2, hy = sy / 2, hz = sz / 2;
  var v = [[-hx,-hy,-hz],[hx,-hy,-hz],[hx,hy,-hz],[-hx,hy,-hz],
           [-hx,-hy, hz],[hx,-hy, hz],[hx,hy, hz],[-hx,hy, hz]];
  var f = [[0,1,2,3],[4,7,6,5],[0,4,5,1],[3,2,6,7],[0,3,7,4],[1,5,6,2]];
  // A touch of face shading so the chassis reads as a solid, not a silhouette.
  var shade = [0.78, 0.92, 0.66, 1.0, 0.86, 0.72];
  var tris = [];
  for (var i = 0; i < f.length; i++) {
    var c = f[i], k = shade[i];
    for (var j = 1; j < 3; j++) {
      tris.push([tXform(m, v[c[0]]), tXform(m, v[c[j]]), tXform(m, v[c[j + 1]])]);
    }
    void k;
  }
  return tEmit(tris, col);
}
function tCyl(r, h, seg, col, m) {
  var tris = [];
  for (var i = 0; i < seg; i++) {
    var a0 = (i / seg) * Math.PI * 2, a1 = ((i + 1) / seg) * Math.PI * 2;
    var p0 = [Math.cos(a0) * r, Math.sin(a0) * r], p1 = [Math.cos(a1) * r, Math.sin(a1) * r];
    tris.push([tXform(m, [p0[0], p0[1], 0]), tXform(m, [p0[0], p0[1], h]),
               tXform(m, [p1[0], p1[1], 0])]);
    tris.push([tXform(m, [p1[0], p1[1], 0]), tXform(m, [p0[0], p0[1], h]),
               tXform(m, [p1[0], p1[1], h])]);
  }
  return tEmit(tris, col);
}
function tQuad(lo, hi, col, m) {
  var z0 = 0, z1 = (hi && hi[2] !== undefined) ? hi[2] : 0.05;
  var p = [[lo[0], lo[1], z0], [hi[0], lo[1], z0], [hi[0], hi[1], z0], [lo[0], hi[1], z0],
           [lo[0], lo[1], z1], [hi[0], lo[1], z1], [hi[0], hi[1], z1], [lo[0], hi[1], z1]];
  var f = [[0,1,2,3],[4,7,6,5],[0,4,5,1],[3,2,6,7],[0,3,7,4],[1,5,6,2]];
  var tris = [];
  for (var i = 0; i < f.length; i++) {
    var c = f[i];
    tris.push([tXform(m, p[c[0]]), tXform(m, p[c[j = 1]]), tXform(m, p[c[2]])]);
    tris.push([tXform(m, p[c[0]]), tXform(m, p[c[2]]), tXform(m, p[c[3]])]);
  }
  return tEmit(tris, col);
}
function tLine(pts, col, m, w) {
  // A polyline drawn as a thin ground ribbon: no line-width extension needed.
  var tris = [], w2 = (w || 0.04) / 2;
  for (var i = 0; i + 1 < pts.length; i++) {
    var a = pts[i], b = pts[i + 1];
    var dx = b[0] - a[0], dy = b[1] - a[1];
    var len = Math.hypot(dx, dy) || 1;
    var nx = -dy / len * w2, ny = dx / len * w2;
    var z = 0.012;
    var q = [[a[0]+nx,a[1]+ny,z],[a[0]-nx,a[1]-ny,z],[b[0]-nx,b[1]-ny,z],[b[0]+nx,b[1]+ny,z]];
    tris.push([tXform(m,q[0]), tXform(m,q[1]), tXform(m,q[2])]);
    tris.push([tXform(m,q[0]), tXform(m,q[2]), tXform(m,q[3])]);
  }
  return tEmit(tris, col);
}
function tXform(m, v) {
  if (!m) return [v[0], v[1], v[2] || 0];
  return [m[0]*v[0] + m[4]*v[1] + m[8]*(v[2]||0) + m[12],
          m[1]*v[0] + m[5]*v[1] + m[9]*(v[2]||0) + m[13],
          m[2]*v[0] + m[6]*v[1] + m[10]*(v[2]||0) + m[14]];
}
function tEmit(tris, col) {
  var pos = [], colr = [];
  for (var i = 0; i < tris.length; i++) {
    for (var j = 0; j < 3; j++) {
      pos.push(tris[i][j][0], tris[i][j][1], tris[i][j][2]);
      colr.push(col[0], col[1], col[2]);
    }
  }
  return { pos: new Float32Array(pos), col: new Float32Array(colr),
           n: tris.length * 3 };
}
function tMesh(parts) {
  var pos = [], colr = [], n = 0;
  for (var i = 0; i < parts.length; i++) {
    var p = parts[i];
    if (!p || !p.n) continue;
    pos = pos.concat(Array.from(p.pos));
    colr = colr.concat(Array.from(p.col));
    n += p.n;
  }
  return { pos: new Float32Array(pos), col: new Float32Array(colr), n: n };
}

var T_COL = {
  floor: [0.09, 0.12, 0.17], grid: [0.16, 0.21, 0.29],
  chassis: [0.13, 0.77, 0.37], deck: [0.10, 0.55, 0.28],
  wheel: [0.08, 0.09, 0.12], camera: [0.22, 0.56, 0.98],
  sensor: [0.85, 0.62, 0.11], mount: [0.45, 0.50, 0.58],
  waypoint: [0.22, 0.74, 0.97], dock: [0.34, 0.85, 0.55],
  pickup: [0.56, 0.40, 0.96], drop: [0.96, 0.65, 0.20],
  route: [0.22, 0.74, 0.97], path: [0.35, 0.40, 0.48],
  goal: [0.66, 0.33, 0.97], hazard: [0.96, 0.65, 0.15],
  hazardCrit: [0.94, 0.27, 0.27], zone: [0.96, 0.62, 0.11]
};

// -- scene assembly from the server's twin state -------------------------- //
function tBuildScene(s) {
  var parts = [], labels = [];
  if (!s) return { mesh: null, labels: labels };

  // Floor: the real data extent, plus a metric grid for scale.
  if (s.floor && s.floor.available && s.floor.corners.length === 4) {
    var c = s.floor.corners;
    parts.push(tQuad(c[0], c[2], T_COL.floor, null));
    var step = 1.0;
    for (var x = Math.ceil(Math.min(c[0][0], c[2][0]));
         x <= Math.max(c[0][0], c[2][0]); x += step) {
      parts.push(tLine([[x, Math.min(c[0][1], c[2][1])],
                        [x, Math.max(c[0][1], c[2][1])]], T_COL.grid, null, 0.01));
    }
    for (var y = Math.ceil(Math.min(c[0][1], c[2][1]));
         y <= Math.max(c[0][1], c[2][1]); y += step) {
      parts.push(tLine([[Math.min(c[0][0], c[2][0]), y],
                        [Math.max(c[0][0], c[2][0]), y]], T_COL.grid, null, 0.01));
    }
  }

  // Restricted / hazard zones as low slabs.
  for (var z = 0; z < (s.zones || []).length; z++) {
    var zn = s.zones[z];
    parts.push(tQuad(zn.min, zn.max, T_COL.zone, null));
    if (TWIN.showLabels) {
      labels.push({ p: [zn.min[0], zn.min[1], zn.height_m + 0.10],
                   text: zn.name + (zn.severity ? " (" + zn.severity + ")" : ""),
                   col: T_COL.zone });
    }
  }

  // Waypoints, coloured by the role the server derived from the name.
  var roleCol = { dock: T_COL.dock, pickup: T_COL.pickup, drop: T_COL.drop };
  for (var w = 0; w < (s.waypoints || []).length; w++) {
    var wp = s.waypoints[w];
    var col = roleCol[wp.role] || T_COL.waypoint;
    var m = tTrans(wp.position[0], wp.position[1], 0);
    parts.push(tCyl(wp.radius, 0.02, 14, col, m));
    if (TWIN.showLabels) {
      labels.push({ p: [wp.position[0], wp.position[1], 0.30],
                   text: wp.name, col: col });
    }
  }

  // Route and travelled path (the bounded C9 trail).
  if (TWIN.showRoute && (s.route || []).length > 1) {
    parts.push(tLine(s.route, T_COL.route, null, 0.07));
  }
  if (TWIN.showPath && (s.path || []).length > 1) {
    parts.push(tLine(s.path, T_COL.path, null, 0.05));
  }

  // Goal.
  if (s.goal) {
    var gm = tMul(tTrans(s.goal.position[0], s.goal.position[1], 0.0),
                  tRotZ(s.goal.rotation_z_deg || 0));
    parts.push(tCyl(s.goal.radius, 0.03, 16, T_COL.goal, gm));
    if (TWIN.showLabels) {
      labels.push({ p: [s.goal.position[0], s.goal.position[1], 0.42],
                   text: "GOAL " + s.goal.name, col: T_COL.goal });
    }
  }

  // Hazards -- only those the server placed (real world location).
  if (TWIN.showHazards) {
    for (var h = 0; h < (s.hazards || []).length; h++) {
      var hz = s.hazards[h];
      var hc = hz.critical ? T_COL.hazardCrit : T_COL.hazard;
      parts.push(tCyl(hz.radius_m, hz.height_m, 14, hc,
                      tTrans(hz.position[0], hz.position[1], 0.0)));
      parts.push(tCyl(hz.radius_m * 0.6, hz.height_m * 0.6, 10,
                      [1, 1, 1],
                      tTrans(hz.position[0], hz.position[1], hz.height_m * 0.4)));
      if (TWIN.showLabels) {
        var txt = hz.kind + (isNum(hz.confidence)
          ? " " + hz.confidence.toFixed(2) : "");
        labels.push({ p: [hz.position[0], hz.position[1], hz.height_m + 0.12],
                     text: txt, col: hc });
      }
    }
  }

  // The AMR: chassis, deck, four wheels, camera, sensor, mount -- all rotated
  // by the runtime's real yaw (already converted server-side).
  if (s.robot) {
    var rm = tMul(tTrans(s.robot.position[0], s.robot.position[1], 0.0),
                  tRotZ(s.robot.rotation_z_deg || 0));
    var mo = s.robot.model || {};
    var ch = mo.chassis || { size: [0.6, 0.4, 0.28], center_z: 0.22 };
    var dm = tMul(rm, tTrans(0, 0, ch.center_z));
    parts.push(tBox(ch.size[0], ch.size[1], ch.size[2], T_COL.chassis, dm));
    if (mo.deck) {
      parts.push(tBox(mo.deck.size[0], mo.deck.size[1], mo.deck.size[2],
                      T_COL.deck, tMul(rm, tTrans(0, 0, mo.deck.center_z))));
    }
    var wheels = mo.wheels || [];
    for (var i = 0; i < wheels.length; i++) {
      var wpw = wheels[i];
      parts.push(tCyl(wpw.radius, wpw.width, 12, T_COL.wheel,
                      tMul(rm, tTrans(wpw.position[0], wpw.position[1],
                                      wpw.position[2]))));
    }
    if (mo.camera) {
      // A sensor *model*, never live imagery.
      parts.push(tBox(mo.camera.size[0], mo.camera.size[1], mo.camera.size[2],
                      T_COL.camera, tMul(rm, tTrans(mo.camera.position[0],
                                                      mo.camera.position[1],
                                                      mo.camera.position[2]))));
    }
    if (mo.sensor) {
      parts.push(tCyl(mo.sensor.radius, mo.sensor.height, 10, T_COL.sensor,
                      tMul(rm, tTrans(mo.sensor.position[0], mo.sensor.position[1],
                                      mo.sensor.position[2]))));
    }
    if (mo.manipulator_mount) {
      parts.push(tBox(mo.manipulator_mount.size[0],
                      mo.manipulator_mount.size[1],
                      mo.manipulator_mount.size[2], T_COL.mount,
                      tMul(rm, tTrans(mo.manipulator_mount.position[0],
                                      mo.manipulator_mount.position[1],
                                      mo.manipulator_mount.position[2]))));
    }
    // Forward indicator: proves orientation is visible even from directly above.
    parts.push(tBox(0.16, 0.05, 0.03, [1, 1, 1],
                    tMul(rm, tTrans(ch.size[0] / 2 + 0.06, 0, ch.center_z))));
  }
  return { mesh: tMesh(parts), labels: labels };
}

// -- WebGL plumbing ------------------------------------------------------- //
function tInit() {
  var canvas = document.getElementById("t-canvas");
  var fallback = document.getElementById("t-fallback");
  if (!canvas) return false;
  var opts = { antialias: true, alpha: false, preserveDrawingBuffer: false };
  var gl = null;
  try {
    gl = canvas.getContext("webgl", opts) || canvas.getContext("experimental-webgl", opts);
  } catch (e) { gl = null; }
  if (!gl) {
    // Honest degradation: say so instead of showing an empty black box.
    if (fallback) fallback.hidden = false;
    canvas.style.display = "none";
    return false;
  }
  var vs = tCompile(gl, gl.VERTEX_SHADER, T_VS);
  var fs = tCompile(gl, gl.FRAGMENT_SHADER, T_FS);
  if (!vs || !fs) {
    if (fallback) fallback.hidden = false;
    return false;
  }
  var prog = gl.createProgram();
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    console.error("twin link:", gl.getProgramInfoLog(prog));
    if (fallback) fallback.hidden = false;
    return false;
  }
  TWIN.gl = gl;
  TWIN.canvas = canvas;
  TWIN.prog = prog;
  TWIN.aPos = gl.getAttribLocation(prog, "aPos");
  TWIN.aCol = gl.getAttribLocation(prog, "aCol");
  TWIN.uMVP = gl.getUniformLocation(prog, "uMVP");
  TWIN.uAlpha = gl.getUniformLocation(prog, "uAlpha");
  TWIN.bufPos = gl.createBuffer();
  TWIN.bufCol = gl.createBuffer();
  gl.enable(gl.DEPTH_TEST);
  TWIN.ready = true;
  return true;
}

function tUpload(mesh) {
  var gl = TWIN.gl;
  gl.bindBuffer(gl.ARRAY_BUFFER, TWIN.bufPos);
  gl.bufferData(gl.ARRAY_BUFFER, mesh.pos, gl.DYNAMIC_DRAW);
  gl.enableVertexAttribArray(TWIN.aPos);
  gl.vertexAttribPointer(TWIN.aPos, 3, gl.FLOAT, false, 0, 0);
  gl.bindBuffer(gl.ARRAY_BUFFER, TWIN.bufCol);
  gl.bufferData(gl.ARRAY_BUFFER, mesh.col, gl.DYNAMIC_DRAW);
  gl.enableVertexAttribArray(TWIN.aCol);
  gl.vertexAttribPointer(TWIN.aCol, 3, gl.FLOAT, false, 0, 0);
}

function tDraw() {
  var gl = TWIN.gl, canvas = TWIN.canvas;
  if (!gl || !canvas) return;
  var dpr = Math.min(2, window.devicePixelRatio || 1);
  var w = Math.max(1, Math.round(canvas.clientWidth * dpr));
  var h = Math.max(1, Math.round(canvas.clientHeight * dpr));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w; canvas.height = h;
  }
  gl.viewport(0, 0, w, h);
  gl.clearColor(0.027, 0.043, 0.071, 1.0);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

  if (!TWIN.state) return;
  var scene = tBuildScene(TWIN.state);
  if (!scene.mesh || !scene.mesh.n) return;
  tUpload(scene.mesh);

  var t = TWIN.target;
  var eye = [
    t[0] + TWIN.dist * Math.cos(TWIN.pitch) * Math.cos(TWIN.yaw),
    t[1] + TWIN.dist * Math.cos(TWIN.pitch) * Math.sin(TWIN.yaw),
    t[2] + TWIN.dist * Math.sin(TWIN.pitch)
  ];
  var aspect = w / Math.max(1, h);
  var mvp = tMul(tPersp(50 * Math.PI / 180, aspect, 0.1, 200.0),
                 tLookAt(eye, t, [0, 0, 1]));

  gl.useProgram(TWIN.prog);
  gl.uniformMatrix4fv(TWIN.uMVP, false, mvp);
  gl.uniform1f(TWIN.uAlpha, 1.0);
  gl.drawArrays(gl.TRIANGLES, 0, scene.mesh.n);
  TWIN.labelAt = scene.labels;
  tUpdateLegend();
}

function tUpdateLegend() {
  var el = document.getElementById("t-legend");
  if (!el) return;
  if (!TWIN.showLabels) { el.hidden = true; return; }
  var s = TWIN.state;
  if (!s) { el.hidden = true; return; }
  var roleName = { dock: "dock / charging", pickup: "pickup", drop: "drop" };
  var lines = ["<b>legend</b>"];
  var seen = {};
  for (var i = 0; i < (s.waypoints || []).length; i++) {
    var r = s.waypoints[i].role;
    if (!seen[r]) {
      seen[r] = 1;
      lines.push("&#9679; " + (roleName[r] || "waypoint"));
    }
  }
  if ((s.route || []).length > 1) lines.push("&#9472; planned route");
  if ((s.path || []).length > 1) lines.push("&#183; travelled path");
  if (s.goal) lines.push("&#9673; goal");
  if ((s.hazards || []).length) lines.push("&#9679; hazard (placed)");
  if ((s.unlocated || []).length) {
    lines.push("&#9679; " + s.unlocated.length + " hazard(s) unlocated");
  }
  el.innerHTML = lines.join("<br>");
  el.hidden = false;
}

function tResetView() {
  TWIN.yaw = 0.9;
  TWIN.pitch = 0.62;
  TWIN.dist = 9.0;
  TWIN.target = [0, 0, 0];
}

function tPoll() {
  // Read-only. C11 routes the twin through the consolidated console payload, so
  // the page issues one request per tick; this direct fetch remains for the
  // "follow" button, which needs a fresh sample immediately.
  fetch("/digital-twin", { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(function (s) { tApplyState(s); })
    .catch(function () { /* the twin must never break the rest of the panel */ });
}

// C11: apply a twin payload that arrived inside /dashboard/state. Identical to
// what tPoll does after its fetch, so the 3D view is unchanged by C11.
function tApplyState(s) {
  if (!s) return;
  TWIN.state = s;
  // "Follow" keeps the camera locked on the AMR; otherwise frame the data.
  if (TWIN.follow && s.robot) {
    TWIN.target = [s.robot.position[0], s.robot.position[1], 0.3];
    TWIN.dist = 4.0;
  } else if (s.floor && s.floor.available) {
    var c = s.floor.corners;
    if (c.length === 4) {
      var cx = (c[0][0] + c[2][0]) / 2, cy = (c[0][1] + c[2][1]) / 2;
      var span = Math.max(
        Math.abs(c[2][0] - c[0][0]), Math.abs(c[2][1] - c[0][1]), 2.0);
      TWIN.target = [cx, cy, 0.2];
      TWIN.dist = Math.max(4.0, span * 1.8);
    }
  }
  tRenderStatus(s);
  tDraw();
}

function pollTwinWith(s) { tApplyState(s); }

function tRenderStatus(s) {
  txt("t-src", s.source || "UNAVAILABLE");
  var sf = s.safety || {};
  var sb = document.getElementById("t-safety");
  if (sb) {
    sb.textContent = "SAFETY " + (sf.action || sf.state || "unknown") +
      (sf.emergency_stop ? " / E-STOP" : "");
    sb.className = "badge " + (sf.emergency_stop || sf.latched ? "b-crit" : "b-dim");
  }
  var m = s.mission || {};
  txt("t-mission", m.current_task
    ? (m.current_task + (m.current_task_status ? " (" + m.current_task_status + ")" : ""))
    : (m.mission_id || "no active mission"));
  txt("t-robot", s.robot
    ? "(" + (-s.robot.position[1]).toFixed(2) + ", " + s.robot.position[0].toFixed(2) +
      ") m  yaw " + s.robot.yaw_rad.toFixed(2) + " rad"
    : "not available");
  txt("t-goal", s.goal ? s.goal.name : "none");
  txt("t-hazards", s.hazards.length ? s.hazards.length + " placed in world" : "none placed");
  txt("t-unplaced", s.unlocated.length
    ? s.unlocated.length + " (no world location)" : "none");
  txt("t-geo", s.floor && s.floor.available
    ? "schematic - data extent " + s.floor.size_m.map(function (v) {
        return v.toFixed(1); }).join(" x ") + " m"
    : "not available");
  var note = document.getElementById("t-note");
  if (note) note.textContent = s.geometry_disclaimer || "";
}

function tInitControls() {
  var canvas = document.getElementById("t-canvas");
  if (canvas) {
    canvas.addEventListener("wheel", function (e) {
      e.preventDefault();
      TWIN.dist = Math.max(1.2, Math.min(40, TWIN.dist * (e.deltaY < 0 ? 0.9 : 1.1)));
      tDraw();
    }, { passive: false });
    canvas.addEventListener("pointerdown", function (e) {
      TWIN.dragging = true; TWIN.lx = e.clientX; TWIN.ly = e.clientY;
      if (canvas.setPointerCapture) canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", function (e) {
      if (!TWIN.dragging) return;
      // Orbit: horizontal drag spins the camera, vertical drag changes pitch.
      TWIN.yaw -= (e.clientX - TWIN.lx) * 0.01;
      TWIN.pitch = Math.max(0.08, Math.min(1.5,
        TWIN.pitch + (e.clientY - TWIN.ly) * 0.008));
      TWIN.lx = e.clientX; TWIN.ly = e.clientY;
      tDraw();
    });
    var stop = function (e) {
      TWIN.dragging = false;
      if (canvas.hasPointerCapture && canvas.hasPointerCapture(e.pointerId)) {
        canvas.releasePointerCapture(e.pointerId);
      }
    };
    canvas.addEventListener("pointerup", stop);
    canvas.addEventListener("pointercancel", stop);
  }
  function bind(id, fn) {
    var el = document.getElementById(id);
    if (el) el.addEventListener("click", fn);
  }
  function toggle(id, key) {
    bind(id, function () {
      TWIN[key] = !TWIN[key];
      var el = document.getElementById(id);
      if (el) el.setAttribute("aria-pressed", TWIN[key] ? "true" : "false");
      tDraw();
    });
  }
  bind("t-reset", function () { tResetView(); tDraw(); });
  bind("t-iso", function () { TWIN.yaw = 0.9; TWIN.pitch = 0.62; tDraw(); });
  bind("t-top", function () { TWIN.yaw = 0.0; TWIN.pitch = 1.5; tDraw(); });
  bind("t-front", function () { TWIN.yaw = 0.0; TWIN.pitch = 0.15; tDraw(); });
  bind("t-follow", function () {
    TWIN.follow = !TWIN.follow;
    var el = document.getElementById("t-follow");
    if (el) el.setAttribute("aria-pressed", TWIN.follow ? "true" : "false");
    tPoll();
  });
  toggle("t-route", "showRoute");
  toggle("t-path", "showPath");
  toggle("t-haz", "showHazards");
  toggle("t-labels", "showLabels");
}



// ------------------------------------------------------------------------ //
// C9 — live 2D map. READ-ONLY: this only ever issues GET /map.
// ------------------------------------------------------------------------ //
// The world->screen transform lives here for *interactive* controls (zoom/pan),
// but it is the same formula the server uses in amr.map.transform: one uniform
// scale with y flipped, because the warehouse frame is y-up and SVG y grows
// downward. Semantic decisions (which hazards are placeable, what is real) are
// made server-side and arrive already resolved.
var MAP_W = 720, MAP_H = 460, MAP_PAD = 24;
var mapZoom = 1.0, mapPanX = 0, mapPanY = 0, mapFollow = false, mapLabels = true;
var mapData = null;

function mapScale(b) {
  var uw = Math.max(1, MAP_W - 2 * MAP_PAD);
  var uh = Math.max(1, MAP_H - 2 * MAP_PAD);
  var sx = uw / Math.max(1e-6, b.x_max - b.x_min);
  var sy = uh / Math.max(1e-6, b.y_max - b.y_min);
  return Math.min(sx, sy) * mapZoom;
}
function mapToScreen(x, y, b) {
  var s = mapScale(b);
  return [x * s + (MAP_PAD - b.x_min * s + mapPanX * s),
          (MAP_PAD + b.y_max * s - mapPanY * s) - y * s];
}
function esc(v) {
  return String(v === null || v === undefined ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function isNum(v) { return typeof v === "number" && isFinite(v); }

function drawGrid(b) {
  var out = "", cands = [10, 5, 2, 1, 0.5, 0.2, 0.1, 0.05, 0.02], step = 1.0;
  var s = mapScale(b);
  for (var i = 0; i < cands.length; i++) {
    if (cands[i] * s >= 28) { step = cands[i]; break; }
  }
  for (var x = Math.floor(b.x_min / step) * step; x <= b.x_max + step * 0.5; x += step) {
    var p = mapToScreen(x, 0, b);
    out += '<line x1="' + p[0].toFixed(2) + '" y1="0" x2="' + p[0].toFixed(2) +
           '" y2="' + MAP_H + '" stroke="' + (Math.abs(x) < 1e-9 ? "#33415c" : "#1b2433") +
           '" stroke-width="1"/>';
  }
  for (var y = Math.floor(b.y_min / step) * step; y <= b.y_max + step * 0.5; y += step) {
    var q = mapToScreen(0, y, b);
    out += '<line x1="0" y1="' + q[1].toFixed(2) + '" x2="' + MAP_W + '" y2="' +
           q[1].toFixed(2) + '" stroke="' + (Math.abs(y) < 1e-9 ? "#33415c" : "#1b2433") +
           '" stroke-width="1"/>';
  }
  return out;
}

function renderMap(m) {
  mapData = m;
  var svg = document.getElementById("m-svg");
  var empty = document.getElementById("m-empty");
  if (!svg) return;
  var b = m.warehouse && m.warehouse.bounds;
  if (!b) {
    svg.innerHTML = "";
    if (empty) empty.hidden = false;
  } else {
    if (empty) empty.hidden = true;
    var g = drawGrid(b), i, p, q, a, c;
    for (i = 0; i < m.zones.length; i++) {
      var z = m.zones[i];
      a = mapToScreen(z.x_min, z.y_min, b);
      c = mapToScreen(z.x_max, z.y_max, b);
      g += '<rect x="' + Math.min(a[0], c[0]).toFixed(2) + '" y="' +
           Math.min(a[1], c[1]).toFixed(2) + '" width="' +
           Math.abs(c[0] - a[0]).toFixed(2) + '" height="' +
           Math.abs(c[1] - a[1]).toFixed(2) + '" fill="#f59e0b" fill-opacity="0.10" ' +
           'stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="6 4"><title>' +
           esc(z.name) + " (" + esc(z.severity) + ")</title></rect>";
      if (mapLabels) {
        g += '<text x="' + (Math.min(a[0], c[0]) + 5).toFixed(2) + '" y="' +
             (Math.min(a[1], c[1]) + 14).toFixed(2) +
             '" fill="#f59e0b" font-size="10">' + esc(z.name) + "</text>";
      }
    }
    if (m.path.length > 1) {
      var pp = m.path.map(function (pt) {
        var r = mapToScreen(pt.x, pt.y, b);
        return r[0].toFixed(2) + "," + r[1].toFixed(2);
      });
      g += '<polyline points="' + pp.join(" ") + '" fill="none" stroke="#475569" ' +
           'stroke-width="1.5" stroke-dasharray="3 3"/>';
    }
    if (m.route.length > 1) {
      var rp = m.route.map(function (pt) {
        var r = mapToScreen(pt.x, pt.y, b);
        return r[0].toFixed(2) + "," + r[1].toFixed(2);
      });
      g += '<polyline points="' + rp.join(" ") + '" fill="none" stroke="#38bdf8" ' +
           'stroke-width="2"/>';
    }
    var wps = (m.warehouse && m.warehouse.waypoints) || [];
    for (i = 0; i < wps.length; i++) {
      var w = wps[i];
      if (!isNum(w.x) || !isNum(w.y)) continue;
      p = mapToScreen(w.x, w.y, b);
      g += '<circle cx="' + p[0].toFixed(2) + '" cy="' + p[1].toFixed(2) +
           '" r="4" fill="none" stroke="#38bdf8" stroke-width="1.5"><title>' +
           esc(w.name) + " (" + w.x.toFixed(2) + ", " + w.y.toFixed(2) +
           ") m</title></circle>";
      if (mapLabels) {
        g += '<text x="' + (p[0] + 8).toFixed(2) + '" y="' + (p[1] + 4).toFixed(2) +
             '" fill="#94a3b8" font-size="10">' + esc(w.name) + "</text>";
      }
    }
    if (m.goal && isNum(m.goal.x)) {
      p = mapToScreen(m.goal.x, m.goal.y, b);
      var gd = -((m.goal.theta || 0) * 180 / Math.PI);
      g += '<g class="layer-goal" transform="translate(' + p[0].toFixed(2) + "," +
           p[1].toFixed(2) + ") rotate(" + gd.toFixed(2) + ')"><circle r="7" ' +
           'fill="none" stroke="#a855f7" stroke-width="2"/><circle r="2" ' +
           'fill="#a855f7"><title>goal ' + esc(m.goal.name) + "</title></circle></g>";
    }
    for (i = 0; i < m.hazards.length; i++) {
      var h = m.hazards[i];
      if (!isNum(h.x) || !isNum(h.y)) continue;
      p = mapToScreen(h.x, h.y, b);
      var sev = String(h.severity || "").toUpperCase();
      var crit = (sev === "EMERGENCY" || sev === "STOP" || sev === "CRITICAL");
      var col = crit ? "#ef4444" : "#f59e0b", rad = crit ? 9 : 7;
      var conf = isNum(h.confidence) ? ", confidence " + h.confidence.toFixed(2) : "";
      g += '<circle class="hazard" cx="' + p[0].toFixed(2) + '" cy="' +
           p[1].toFixed(2) + '" r="' + rad + '" fill="' + col +
           '" fill-opacity="0.75" stroke="' + col + '" stroke-width="2"><title>' +
           esc(h.kind) + " (" + esc(h.severity) + ")" + conf + ", source " +
           esc(h.source) + "</title></circle>";
      if (mapLabels) {
        g += '<text x="' + (p[0] + rad + 3).toFixed(2) + '" y="' +
             (p[1] + 4).toFixed(2) + '" fill="' + col + '" font-size="10">' +
             esc(h.kind) + "</text>";
      }
    }
    if (m.robot && isNum(m.robot.x)) {
      p = mapToScreen(m.robot.x, m.robot.y, b);
      var deg = -((m.robot.yaw || 0) * 180 / Math.PI);
      g += '<g class="layer-robot" data-layer="robot" transform="translate(' +
           p[0].toFixed(2) + "," + p[1].toFixed(2) + ") rotate(" + deg.toFixed(2) +
           ')"><polygon points="0,-11 8,8 0,4 -8,8" fill="#22c55e" stroke="#0b101a" ' +
           'stroke-width="1"><title>AMR (' + m.robot.x.toFixed(2) + ", " +
           m.robot.y.toFixed(2) + ") m, yaw " + (m.robot.yaw || 0).toFixed(2) +
           " rad</title></polygon></g>";
    }
    svg.innerHTML = g;
  }
  txt("m-src", m.source || "UNAVAILABLE");
  var sf = m.safety || {};
  var badge = document.getElementById("m-safety");
  if (badge) {
    badge.textContent = "SAFETY " + (sf.action || sf.state || "unknown") +
      (sf.emergency_stop ? " / E-STOP" : "");
    badge.className = "badge " + (sf.emergency_stop || sf.latched ? "b-crit" : "b-dim");
  }
  txt("m-robot", m.robot ? "(" + m.robot.x.toFixed(2) + ", " + m.robot.y.toFixed(2) +
      ") m  yaw " + (m.robot.yaw || 0).toFixed(2) + " rad" : "not available");
  txt("m-goal", m.goal ? m.goal.name : "none");
  txt("m-route", m.route.length ? m.route.length + " waypoints" : "no route");
  txt("m-hazards", m.hazards.length ? m.hazards.length + " placed" : "none placed");
  txt("m-unplaced", m.unlocated.length
      ? m.unlocated.length + " (no world location)" : "none");
  var note = document.getElementById("m-note");
  if (note) note.textContent = m.warehouse ? m.warehouse.note : "";
}

function mapReset() { mapZoom = 1.0; mapPanX = 0; mapPanY = 0; }

function pollMapWith(m) {
  // C11: the map payload now arrives inside the console response.
  if (!m) return;
  if (m.robot && mapFollow) mapReset();
  renderMap(m);
}

function initMapControls() {
  var svg = document.getElementById("m-svg");
  if (svg) {
    svg.addEventListener("wheel", function (e) {
      if (!mapData || !mapData.warehouse || !mapData.warehouse.bounds) return;
      e.preventDefault();
      mapZoom = Math.max(0.2, Math.min(10, mapZoom * (e.deltaY < 0 ? 1.15 : 0.87)));
      renderMap(mapData);
    }, { passive: false });
    var dragging = false, lastX = 0, lastY = 0;
    svg.addEventListener("pointerdown", function (e) {
      dragging = true; lastX = e.clientX; lastY = e.clientY;
      if (svg.setPointerCapture) svg.setPointerCapture(e.pointerId);
    });
    svg.addEventListener("pointermove", function (e) {
      if (!dragging || !mapData || !mapData.warehouse || !mapData.warehouse.bounds) return;
      var b = mapData.warehouse.bounds, s = mapScale(b);
      // Drag right -> the content follows the cursor, so the world pans the
      // opposite way; the y sign is inverted to match the flipped axis.
      mapPanX -= (e.clientX - lastX) / s;
      mapPanY += (e.clientY - lastY) / s;
      lastX = e.clientX; lastY = e.clientY;
      renderMap(mapData);
    });
    var endDrag = function (e) {
      dragging = false;
      if (svg.hasPointerCapture && svg.hasPointerCapture(e.pointerId)) {
        svg.releasePointerCapture(e.pointerId);
      }
    };
    svg.addEventListener("pointerup", endDrag);
    svg.addEventListener("pointercancel", endDrag);
  }
  var follow = document.getElementById("m-follow");
  if (follow) {
    follow.addEventListener("click", function () {
      mapFollow = !mapFollow;
      follow.setAttribute("aria-pressed", mapFollow ? "true" : "false");
      if (mapFollow) mapReset();
    });
  }
  var fit = document.getElementById("m-fit");
  if (fit) {
    fit.addEventListener("click", function () {
      mapReset();
      if (mapData) renderMap(mapData);
    });
  }
  var toggle = document.getElementById("m-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      mapLabels = !mapLabels;
      toggle.setAttribute("aria-pressed", mapLabels ? "true" : "false");
      if (mapData) renderMap(mapData);
    });
  }
}

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

// ------------------------------------------------------------------------ //
// C11 — operations console rendering. Everything here reads the single
// /dashboard/state payload; no panel computes robot state of its own.
// ------------------------------------------------------------------------ //
function bar(id, frac, crit) {
  var el = document.getElementById(id);
  if (!el) return;
  // 10 segments, filled only up to a real, known fraction.
  var cells = "";
  var lit = (typeof frac === "number" && isFinite(frac))
    ? Math.round(Math.max(0, Math.min(1, frac)) * 10) : 0;
  for (var i = 0; i < 10; i++) {
    cells += '<i class="' + (i < lit ? (crit ? "crit" : "on") : "") + '"></i>';
  }
  el.innerHTML = cells;
}

function renderOpsbar(s) {
  function set(id, value, cls) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = value;
    el.className = "ops-v " + (cls || "b-dim");
  }
  // Source first: every other value is read under this light.
  set("o-source", s.source + (s.simulated ? " (mock runtime)" : ""),
      s.simulated ? "b-sim" : "b-ok");
  set("o-robot", s.summary.robot, s.robot.connected ? "b-ok" : "b-crit");
  var navOk = s.navigation.availability === "AVAILABLE";
  set("o-nav", s.summary.navigation, navOk ? "b-ok" : "b-dim");
  var safetyTxt = s.summary.safety;
  var safetyCls = "b-ok";
  if (s.safety.emergency_stop) { safetyTxt = "E-STOP"; safetyCls = "b-crit"; }
  else if (safetyTxt === "STOP" || safetyTxt === "WAIT") { safetyCls = "b-warn"; }
  set("o-safety", safetyTxt, safetyCls);
  set("o-mission", s.mission.state,
      s.mission.availability === "AVAILABLE" ? "b-ok" : "b-dim");
  var hzTxt = s.hazards.active + " active";
  if (s.hazards.unlocated) { hzTxt += " / " + s.hazards.unlocated + " unlocated"; }
  set("o-hazards", hzTxt, s.hazards.critical ? "b-crit"
      : (s.hazards.active ? "b-warn" : "b-dim"));
}

function renderMission(m, route) {
  txt("m-state", m.state);
  txt("m-id", m.mission_id || "none");
  txt("m-task", m.current_task || "none");
  txt("m-status", m.current_task_status || "none");
  txt("m-queued", m.queued === null || m.queued === undefined ? "N/A" : m.queued);
  txt("m-done", m.completed_tasks === null ? "N/A" : m.completed_tasks);
  txt("m-fail", m.failed_tasks === null ? "N/A" : m.failed_tasks);
  // A bar is drawn only when the runtime supplied real progress.
  var p = route && route.progress_available ? route.progress_pct / 100 : null;
  bar("m-bar", p, m.state === "FAILED");
  var note;
  if (m.availability !== "AVAILABLE") {
    note = "Mission source: " + m.source + " \u2014 no mission runtime attached.";
  } else if (route && route.progress_available) {
    note = "progress " + route.progress_pct.toFixed(0) + "% (" + route.progress_basis + ")";
  } else {
    note = "No route progress available; showing task counters only.";
  }
  txt("m-note", note);
}

function renderGoal(nav) {
  txt("g-name", nav.current_goal || "none");
  txt("g-state", nav.state || "N/A");
  var r = nav.route;
  txt("g-points", r ? r.waypoints : "no route");
  if (r && r.progress_available) {
    txt("g-prog", r.progress_pct.toFixed(0) + " %");
    txt("g-note", r.progress_basis + " \u2014 display only, never a planner input.");
  } else {
    txt("g-prog", "N/A");
    txt("g-note", "Progress unavailable: no goal/pose pair in the runtime.");
  }
}

function renderSafety(s, hz) {
  txt("s-state", s.state || "N/A");
  txt("s-action", s.action || "N/A");
  txt("s-estop", s.emergency_stop ? "ACTIVE" : "clear");
  // Extra C11 rows reuse the same elements the map/twin badges already show.
  var extra = document.getElementById("s-extra");
  if (extra) {
    extra.innerHTML = [
      row("Active hazards", hz.active),
      row("Critical", hz.critical),
      row("Latched", hz.latched ? "yes" : "no"),
      row("Avoidance", s.avoidance || "inactive"),
      row("Reasons", s.reasons.length ? s.reasons.join("; ") : "none")
    ].join("");
  }
  function row(k, v) {
    return '<div class="health-row"><span class="h-name">' + k
      + '</span><span>' + v + "</span></div>";
  }
}

function renderBattery(b) {
  txt("b-state", b.source);
  txt("b-pct", b.percentage === null ? "N/A" : b.percentage + " %");
  txt("b-volt", b.voltage === null ? "N/A" : b.voltage + " V");
  txt("b-chg", b.charging === null || b.charging === undefined
    ? "N/A" : (b.charging ? "yes" : "no"));
  txt("b-note", b.note || ("source: " + b.source));
}

function renderSensors(s) {
  var ul = document.getElementById("sensors");
  var out = [];
  for (var i = 0; i < s.rows.length; i++) {
    var r = s.rows[i];
    var v = (r.value === null || r.value === undefined) ? "no reading" : r.value + " " + r.unit;
    out.push("<li>" + r.sensor + " &middot; " + v + " " + src(r.source) + "</li>");
  }
  ul.innerHTML = out.length ? out.join("")
    : '<li class="empty">no sensor readings (source: ' + s.source + ")</li>";
}

function renderHealth(sys) {
  var el = document.getElementById("health");
  if (!el) return;
  var out = [];
  for (var i = 0; i < sys.components.length; i++) {
    var c = sys.components[i];
    var cls = c.availability === "AVAILABLE" ? "b-ok" : "b-dim";
    out.push('<div class="health-row"><span class="h-name">' + c.component
      + '</span><span class="badge ' + cls + '">' + c.source + "</span></div>");
  }
  el.innerHTML = out.join("");
  var note = document.getElementById("y-note");
  if (note) {
    var degraded = sys.degraded.length ? sys.degraded.join(", ") : "none";
    note.textContent = "status " + (sys.status || "N/A")
      + (sys.last_error ? " \u00b7 last error: " + sys.last_error : "")
      + " \u00b7 degraded: " + degraded;
  }
}

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

// C11: one entry point for the operations console. The existing apply() logic
// is preserved by mapping the console payload back onto the C7 field names it
// already reads, so C7-C10 rendering code is untouched.
function applyConsole(s) {
  var route = s.navigation.route;
  var t = {
    schema_version: s.telemetry_schema_version,
    timestamp: s.timestamp,
    simulated: s.simulated,
    position: s.robot.position,
    orientation: s.robot.orientation,
    velocity: s.robot.velocity,
    navigation: {
      state: s.navigation.state,
      current_goal: s.navigation.current_goal,
      // The C7 renderer only counts route points; a route with no known
      // progress is reported as empty rather than as a zero-length route.
      route: route ? [0] : [],
      progress: route ? route.progress : null,
      avoidance: s.navigation.avoidance,
      source: s.navigation.source
    },
    safety: {
      state: s.safety.state,
      action: s.safety.action,
      emergency_stop: s.safety.emergency_stop,
      reasons: s.safety.reasons,
      hazard_state: s.safety.hazard_state,
      latched: s.safety.hazard_latched,
      source: s.safety.source
    },
    hazards: s.hazard_list,
    battery: s.battery,
    sensors: { ultrasonic: s.sensors.rows, source: s.sensors.source },
    mission: s.mission,
    camera: s.camera,
    system: {
      uptime: s.system.uptime,
      software_version: s.system.software_version,
      connected: s.robot.connected,
      mode: s.robot.mode,
      last_error: s.system.last_error,
      source: s.system.source
    }
  };
  apply(t);
  // C11-only panels.
  renderOpsbar(s);
  renderMission(s.mission, route);
  renderGoal(s.navigation);
  renderSafety(s.safety, s.hazards);
  renderBattery(s.battery);
  renderSensors(s.sensors);
  renderHealth(s.system);
}

function poll() {
  // C11: one request per tick instead of four. /dashboard/state carries the
  // telemetry, health, map and twin projections; the map and twin renderers
  // are handed their existing payloads unchanged.
  fetch("/dashboard/state", { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) { throw new Error("HTTP " + r.status); }
      return r.json();
    })
    .then(function (s) {
      // Hand the untouched C9/C10 payloads to the existing renderers.
      pollMapWith(s.map);
      pollTwinWith(s.twin);
      applyConsole(s);
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

tInitControls();
if (tInit()) { tResetView(); }
initMapControls();
poll();
setInterval(poll, POLL_MS);
</script>"""

# Substitute the JS token once, at import time, so the served document is a
# single self-contained HTML string with no templating left on the wire.
DASHBOARD_HTML = DASHBOARD_HTML.replace("__DASHBOARD_JS__", DASHBOARD_JS)

