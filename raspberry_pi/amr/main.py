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
from typing import List, Optional

from . import __version__
from .camera import CameraManager
from .communication.arduino_serial import ArduinoSerial, ArduinoSerialTransport
from .control import ArduinoMotorDriver
from .hazard import HazardManager
from .logging import get_logger, setup_logging
from .mocks import MockCamera
from .robot import RobotCommandError, RobotManager, RobotMode
from .utils.config import AppConfig, ConfigError, load_config
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


def build_camera(config: AppConfig, mock: bool) -> CameraManager:
    """Camera facade for the web UI; always degrades gracefully."""
    cam_cfg = config.robot.camera
    if mock:
        return CameraManager(MockCamera(available=True), cam_cfg)
    return CameraManager.create_real(cam_cfg)


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
    app = AMRWebApp(
        mgr,
        camera=build_camera(config, args.mock),
        # C7: the dashboard is told the truth about where its numbers come
        # from. A mock run is tagged SIMULATION everywhere, so the UI can never
        # present simulated telemetry as a physical measurement.
        simulated=args.mock,
        software_version=__version__,
    )
    port = app.start(host=args.host, port=args.port)
    shown = "localhost" if args.host in ("0.0.0.0", "") else args.host
    print(f"AMR web control: http://{shown}:{port}  (Ctrl-C to stop)")
    get_logger("main").info("web control listening on %s:%d", args.host, port)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
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
