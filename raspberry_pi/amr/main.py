"""AMR command-line entry point.

Usage (from the ``raspberry_pi/`` directory):

    python -m amr.main --mock          # interactive REPL against the in-process mock
    python -m amr.main --mock --demo   # scripted demo sequence, no input, exits
    python -m amr.main                 # interactive REPL against the real controller
    python -m amr.main --mock --web    # web control panel, fully offline
    python -m amr.main --web --port 8090  # web control panel against hardware

Mock mode exercises the *entire* high-level stack (protocol, serial API,
motor driver, differential drive, safety, modes, camera) against
:class:`~amr.mocks.mock_serial.MockSerialTransport` — no hardware and no
pyserial required.

Every REPL answer is a single JSON line that the web control UI (Phase 10)
consumes unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, List, Optional, Tuple

from . import __version__
from .camera import (
    CameraManager,  # noqa: F401  (legacy backend, still public)
    RaspberryPiCameraSource,
    SimulatedCameraSource,
)
from .communication.arduino_serial import ArduinoSerial, ArduinoSerialTransport
from .control import ArduinoMotorDriver
from .hazard import HazardManager
from .logging import get_logger, setup_logging
from .navigation import LocalNavigator
from .robot import RobotCommandError, RobotManager, RobotMode
from .utils.config import AppConfig, ConfigError, load_config
from .warehouse import WarehouseTaskManager
from .web import AMRWebApp

MODES = {m.value: m for m in RobotMode}

HELP = """\
commands:
  status                 full robot snapshot (JSON)
  sensor                 one sensor poll + safety decision
  ping                   controller PING
  mode <idle|manual|autonomous|safety_stop|error>
  forward <speed>        straight forward (1..max_speed)
  backward <speed>       straight backward
  left <speed>           arc turn left (inner wheel stopped)
  right <speed>          arc turn right
  rotate <ccw|cw> <speed>  in-place rotation
  stop                   motion stop (always allowed)
  estop                  emergency stop + SAFETY_STOP mode
  help                   this text
  quit                   exit
"""


def build_manager(args: argparse.Namespace, config: AppConfig) -> RobotManager:
    """Wire the full stack for either mock or hardware mode."""
    max_speed = config.robot.motors.max_speed

    if args.mock:
        mgr, _transport = RobotManager.create_mock(config)
        return mgr

    transport = ArduinoSerialTransport(
        port=config.serial.port,
        baudrate=config.serial.baudrate,
        timeout=config.serial.timeout,
    )
    serial = ArduinoSerial(transport, timeout=config.serial.timeout)
    driver = ArduinoMotorDriver(serial, max_speed=max_speed)
    return RobotManager(serial, driver, config)


def parse_resolution(value: Any, default: Tuple[int, int] = (640, 480)
                     ) -> Tuple[int, int]:
    """Parse a ``"WIDTHxHEIGHT"`` setting into a pixel pair.

    C15b added this because :class:`CameraConfig` stores the resolution as a
    ``"1280x720"`` string, while :func:`build_camera` read ``cam_cfg.width`` /
    ``cam_cfg.height`` — attributes that do not exist. The result was that the
    configured resolution was silently discarded and the camera always opened at
    640x480.

    An unparsable, zero or negative value falls back to ``default`` rather than
    producing a size no camera could deliver.
    """
    try:
        text = str(value).strip().lower()
        if "x" in text:
            w_text, h_text = text.split("x", 1)
        elif "*" in text:
            w_text, h_text = text.split("*", 1)
        else:
            w_text = h_text = text
        width, height = int(float(w_text)), int(float(h_text))
    except (TypeError, ValueError):
        return default
    if width <= 0 or height <= 0:
        return default
    return width, height


def build_camera(config: AppConfig, mock: bool) -> Any:
    """Camera source for the web UI / telemetry; always degrades gracefully.

    C8: returns a :class:`CameraSource` from :mod:`amr.camera.frame`, so the
    dashboard and the C7 telemetry collector read one stable contract. The
    choice is explicit and honest about what is behind it:

    * ``--mock`` -> :class:`SimulatedCameraSource` (status ``SIMULATION``)
    * hardware  -> :class:`RaspberryPiCameraSource` (``LIVE`` / ``UNAVAILABLE``
      / ``ERROR`` depending on what the Pi actually offers)

    Nothing here opens a device, so a missing camera cannot stop the runtime
    from starting; the backend reports the failure through its status instead.

    C15b: the resolution now actually comes from ``camera.resolution``. It was
    previously read from non-existent ``width``/``height`` attributes, so the
    configured value was ignored and every camera opened at the 640x480
    fallback.
    """
    cam_cfg = config.robot.camera
    width, height = parse_resolution(getattr(cam_cfg, "resolution", None))
    if mock:
        return SimulatedCameraSource(width=width, height=height)
    return RaspberryPiCameraSource(width=width, height=height)


def build_frame_detector(camera: Any, config: AppConfig) -> Any:
    """A :class:`CameraFrameDetector` for the configured camera, or ``None``.

    C15b. The camera backend is real; the **model** is not, so no inference
    callable is supplied here and the detector honestly reports no detections.
    Wiring one in later is a config change plus a callable — the hazard pipeline
    downstream is untouched.

    Returns ``None`` when ``camera.enabled`` is false, so a camera-less
    deployment does not gain a pointless source.
    """
    from .camera.detector import CameraFrameDetector

    cam_cfg = config.robot.camera
    if not getattr(cam_cfg, "enabled", True):
        return None
    return CameraFrameDetector(camera, camera_id=getattr(cam_cfg, "camera_id", None))


def build_navigator(mgr: RobotManager, config: AppConfig,
                    hazard: Any = None) -> Any:
    """The single navigator for this runtime (C9).

    The dashboard reads pose/goal/route from this object; it never steps it.
    Motion is only ever driven by the warehouse task manager's own loop or the
    operator command path, both of which go through the safety gate.

    ``hazard`` (C15) is the optional hazard manager. When both it and
    ``config.safety.avoidance.enabled`` are present, the C6 obstacle-avoidance
    gate is wired in: the navigator asks the *existing* hazard layer what it is
    seeing, and the *existing* :class:`AvoidancePolicy` decides. Nothing about
    the manoeuvre is invented here, and with the flag off (the shipped default)
    this is byte-identical to before C6.
    """
    whcfg = config.warehouse
    wheel_base = config.robot.wheel_track_m or whcfg.wheel_base_m
    kwargs: dict = {}
    if hazard is not None and getattr(config.safety, "avoidance", None) is not None \
            and config.safety.avoidance.enabled:
        from .safety.avoidance import AvoidancePolicy, report_from_hazard
        kwargs.update(
            avoidance=AvoidancePolicy.from_config(config.safety.avoidance),
            # The navigator asks the hazard layer; it never re-reads sensors.
            # ``status`` is a property on HazardManager, so read the attribute.
            obstacle_provider=lambda: report_from_hazard(hazard.status),
            # Layer 3 keeps absolute priority: the navigator consults the real
            # safety verdict before considering any manoeuvre.
            decision_provider=lambda: mgr.decision,
        )
        get_logger("main").info(
            "C6 obstacle avoidance wired (hazard layer supplies the evidence)")
    return LocalNavigator(
        command=mgr.move,
        start_pose=None,  # starts at the map's dock (0, 0, 0)
        wheel_base_m=wheel_base,
        max_linear_speed=whcfg.task_speed,
        max_angular_speed=whcfg.turn_speed,
        max_pwm=mgr.drive.max_speed,
        **kwargs,
    )


def build_warehouse(mgr: RobotManager, config: AppConfig,
                    navigator: Any, mission_id: Optional[str] = None) -> Any:
    """Warehouse task manager, or ``None`` when disabled in config.

    Created so the map reads the existing waypoints from the single source of
    truth (the warehouse config) rather than a copy of it. ``mission_id`` (C12)
    is a caller-supplied display label for this run.
    """
    if not getattr(config.warehouse, "enabled", False):
        return None
    try:
        return WarehouseTaskManager.create(config, mgr, navigator,
                                           mission_id=mission_id)
    except Exception as exc:  # noqa: BLE001 - monitoring must still come up
        get_logger("main").warning("warehouse unavailable: %s", exc)
        return None


def attach_hazard_layer(mgr: RobotManager, config: AppConfig) -> bool:
    """Wire the opt-in hazard layer (Layer 3.5) onto the manager.

    Honours the deployment switch ``config.hazard.enabled``: when it is
    ``False`` (the default) nothing is attached and the stack behaves exactly
    as it did before the hazard feature existed.

    Deliberately attached **without sensor sources**: no gas, smoke or vision
    hardware exists yet (tasks C4/C5), and ``RobotStateSource`` is not wired
    automatically because ``RobotState.last_error`` is sticky — it would pin
    the layer at ``WARNING`` forever after the first E-STOP. The zone source
    (added by :meth:`HazardManager.from_config`) stays silent while no pose
    provider exists, which is the fail-safe design: a missing location never
    invents a hazard. Sources are added later via ``hazard.add_source(...)``.

    Returns ``True`` when a layer was attached.
    """
    if not config.hazard.enabled or mgr.hazard is not None:
        return False
    hazard = HazardManager.from_config(config.hazard)
    mgr.attach_hazard(hazard)
    get_logger("main").info(
        "hazard layer attached (%d source(s); no sensor hardware wired yet)",
        len(hazard.sources),
    )
    return True


# --------------------------------------------------------------------------- #
# Demo mode
# --------------------------------------------------------------------------- #
def run_demo(mgr: RobotManager, out=print) -> int:
    """Run a scripted end-to-end sequence; returns a process exit code.

    Each step prints one JSON line: ``{"step": ..., "ok": ..., ...}``.
    Exit code 0 iff every step succeeded.
    """
    steps: List[dict] = []

    def step(name: str, fn) -> None:
        try:
            result = fn()
            steps.append({"step": name, "ok": True, "result": result})
        except Exception as exc:  # noqa: BLE001 - demo reports every failure
            steps.append({"step": name, "ok": False, "error": str(exc)})
        out(json.dumps(steps[-1]))

    try:
        step("start", lambda: mgr.start())
        step("tick", lambda: mgr.tick().action.value)
        step("mode:manual", lambda: mgr.request_mode(RobotMode.MANUAL).value)
        step("forward:100", lambda: mgr.forward(100) or "ok")
        step("rotate_right:80", lambda: mgr.rotate_right(80) or "ok")
        step("stop", lambda: mgr.stop() or "ok")
        step("estop", lambda: mgr.estop() or "ok")
        step("mode:idle", lambda: mgr.request_mode(RobotMode.IDLE).value)
        step("snapshot", lambda: mgr.snapshot())
    finally:
        mgr.shutdown()

    return 0 if all(s["ok"] for s in steps) else 1


# --------------------------------------------------------------------------- #
# Web control (Phase 10)
# --------------------------------------------------------------------------- #
def run_web(mgr: RobotManager, config: AppConfig, args: argparse.Namespace) -> int:
    """Run the web control panel until Ctrl-C. Returns a process exit code."""
    camera = build_camera(config, args.mock)
    # C8: own the camera lifecycle here so the device is opened once and — more
    # importantly — released on exit. `start()` never raises, so a camera that
    # fails to open degrades to UNAVAILABLE/ERROR instead of blocking the panel.
    start = getattr(camera, "start", None)
    if callable(start):
        start()
    # C9: the map needs the same navigator the runtime uses. It is created once
    # here and handed to the dashboard read-only: the web layer never calls
    # step()/go_to(), so it cannot move the robot. `navigator=None` would simply
    # render an "unavailable" pose, so wiring it is what makes the map live.
    nav = build_navigator(mgr, config)
    # C14b: resolve the recordings directory once, here, so the dashboard only
    # ever sees a validated directory. It stays None unless config/replay.yaml
    # points at one.
    replay_cfg = getattr(config, "replay", None)
    replay_dir = (replay_cfg.resolved_dir(config.config_dir)
                  if replay_cfg is not None and replay_cfg.enabled else None)
    # C12: a caller-supplied label for this run, so the dashboard can name the
    # mission it is watching. It is a real label for a real run — not invented
    # inside the telemetry layer.
    wh = build_warehouse(mgr, config, nav, mission_id="web-run")
    # C12: optionally drive the standard warehouse mission so the dashboard's
    # Mission panel shows real task progress. This is opt-in and mock-only: it
    # commands autonomous motion, so it is refused against real hardware rather
    # than silently starting a mission nobody asked for.
    mission = None
    if getattr(args, "mission_demo", False):
        if not args.mock:
            raise SystemExit(
                "--mission-demo drives the robot autonomously and is mock-only. "
                "Re-run with --mock, or drop the flag to monitor only."
            )
        if wh is None:
            raise SystemExit("--mission-demo needs the warehouse layer enabled "
                             "in config/warehouse.yaml")
        wh.submit_pick("shelf_a", payload_id="SKU-1")
        wh.submit_place("station", payload_id="SKU-1")
        wh.submit_return_to_dock()
        mission = wh
    app = AMRWebApp(
        mgr,
        camera=camera,
        navigator=nav,
        warehouse=wh,
        # C5d: hand the mission to the server's EXISTING control loop instead of
        # ticking it here. run_web used to run a second, 1 Hz loop that called
        # mgr.tick() and mission.process(dt=1.0) while the server's loop was
        # already ticking at 5-10 Hz — the robot was integrated twice and the
        # planner's clock was 5-10x too fast, which showed up as the AMR
        # visibly oscillating back and forth along its route.
        run_warehouse=mission is not None,
        # C7: the dashboard is told the truth about where its numbers come
        # from. A mock run is tagged SIMULATION everywhere, so the UI can never
        # present simulated telemetry as a physical measurement.
        simulated=args.mock,
        software_version=__version__,
        # C13: let the overlay pair frames with the detections from this camera.
        camera_id=getattr(config.robot.camera, "camera_id", None),
        # C14b: where recorded runs live. None (the default) leaves the replay
        # panel present but reporting "no recordings configured".
        recordings_dir=replay_dir,
        auto_record=bool(getattr(replay_cfg, "auto_record", True)),
        # C5e: the console shows the configured unit name instead of a
        # placeholder. Sourced from config/robot.yaml (robot.name), so the
        # operator sees the robot they are actually watching. Read-only label.
        robot_id=getattr(config.robot, "name", None),
    )
    port = app.start(host=args.host, port=args.port)
    shown = "localhost" if args.host in ("0.0.0.0", "") else args.host
    print(f"AMR web control: http://{shown}:{port}  (Ctrl-C to stop)")
    if mission is not None:
        print("mission demo: pick shelf_a -> place station -> return to dock "
              "(mock only)")
    get_logger("main").info("web control listening on %s:%d", args.host, port)
    try:
        # C5d: this loop only keeps the process alive. The server's own control
        # loop drives mgr.tick(), the mission and the recorder; ticking here too
        # would double-integrate the robot.
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        # Release the camera device even if the server failed to come up.
        stop = getattr(camera, "stop", None)
        if callable(stop):
            stop()
        mgr.shutdown()
    return 0


# --------------------------------------------------------------------------- #
# Interactive REPL
# --------------------------------------------------------------------------- #
def _speed(args: List[str], default: int) -> int:
    return int(args[0]) if args else default


def run_repl(mgr: RobotManager) -> int:
    """Interactive JSON REPL. Returns a process exit code."""
    out = print
    try:
        line = input("amr> ").strip()
        while line:
            parts = line.split()
            cmd, rest = parts[0].lower(), parts[1:]
            try:
                if cmd in ("quit", "exit"):
                    break
                elif cmd == "help":
                    print(HELP)
                elif cmd == "status":
                    out(json.dumps(mgr.snapshot()))
                elif cmd == "sensor":
                    d = mgr.tick()
                    s = mgr.state
                    out(json.dumps(
                        {"safety": str(d), "front": s.front_cm, "left": s.left_cm,
                         "right": s.right_cm, "rear": s.rear_cm}
                    ))
                elif cmd == "ping":
                    out(json.dumps({"pong": mgr.ping()}))
                elif cmd == "mode":
                    if not rest or rest[0] not in MODES:
                        out(json.dumps({"error": "usage: mode <idle|manual|autonomous|safety_stop|error>"}))
                    else:
                        out(json.dumps({"mode": mgr.request_mode(MODES[rest[0]]).value}))
                elif cmd in ("forward", "backward"):
                    fn = mgr.forward if cmd == "forward" else mgr.backward
                    fn(_speed(rest, 100))
                    out(json.dumps({"ok": True, "cmd": cmd}))
                elif cmd in ("left", "right"):
                    fn = mgr.turn_left if cmd == "left" else mgr.turn_right
                    fn(_speed(rest, 80))
                    out(json.dumps({"ok": True, "cmd": cmd}))
                elif cmd == "rotate":
                    direction = rest[0].lower() if rest else ""
                    if direction not in ("ccw", "cw"):
                        out(json.dumps({"error": "usage: rotate <ccw|cw> [speed]"}))
                    else:
                        sp = _speed(rest[1:], 100)
                        (mgr.rotate_left if direction == "ccw" else mgr.rotate_right)(sp)
                        out(json.dumps({"ok": True, "cmd": f"rotate {direction}"}))
                elif cmd == "stop":
                    mgr.stop()
                    out(json.dumps({"ok": True, "cmd": "stop"}))
                elif cmd == "estop":
                    mgr.estop()
                    out(json.dumps({"ok": True, "cmd": "estop", "mode": mgr.state.mode.value}))
                else:
                    out(json.dumps({"error": f"unknown command: {cmd} (try 'help')"}))
            except RobotCommandError as exc:
                out(json.dumps({"error": str(exc)}))
            except (ValueError, IndexError) as exc:
                out(json.dumps({"error": f"bad argument: {exc}"}))

            line = input("amr> ").strip()
    except (EOFError, KeyboardInterrupt):
        pass
    mgr.shutdown()
    return 0


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="amr",
        description="AMR robot controller (smart-warehouse platform)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="run against the in-process mock controller (no hardware)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="run a scripted demo sequence and exit (implies no input)",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="run the web control panel instead of the REPL (Ctrl-C to stop)",
    )
    parser.add_argument(
        "--mission-demo",
        action="store_true",
        help=("C12: run the standard warehouse pick/place/return mission while the "
              "web panel is up, so the Mission panel shows real task progress. "
              "Requires --mock: it drives the robot autonomously, so it is "
              "refused against real hardware."),
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="web bind address (default: 0.0.0.0 — LAN access on the Pi)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="web port (default: 8080)",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        help="directory containing *.yaml config files (default: <repo>/config)",
    )
    args = parser.parse_args(argv)

    try:
        setup_logging(console=False)
    except Exception:  # noqa: BLE001 - logging is best-effort
        get_logger("main").warning("logging setup failed; continuing without file log")

    try:
        config = load_config(args.config_dir)
        mgr = build_manager(args, config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    mode = "MOCK" if args.mock else "HARDWARE"
    get_logger("main").info("amr v%s starting in %s mode", __version__, mode)

    if args.demo:
        return run_demo(mgr)

    try:
        mgr.start()
    except ConnectionError as exc:
        print(f"could not reach controller: {exc}", file=sys.stderr)
        return 3

    # Opt-in hazard layer (honours config.hazard.enabled; default off).
    attach_hazard_layer(mgr, config)

    if args.web:
        return run_web(mgr, config, args)

    print(f"AMR connected (v{__version__}, controller={mgr.version or 'unknown'}). 'help' for commands.")
    return run_repl(mgr)


if __name__ == "__main__":
    sys.exit(main())
