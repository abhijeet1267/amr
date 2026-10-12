# AMR — Project State

> Single-page picture of what this project is, what is built, what is connected,
> and what is not. Every number here was measured from the working tree at
> `057f45e`, not copied from a plan.
>
> **The honesty rule this project follows:** a missing value is reported as
> `n/a`, never as `0` or a guess. "Not verified" is written where it is true.
> That rule is why several sections below read as unfinished — they are.

---

## 1. What this is

An autonomous mobile robot (AMR) built around a **Raspberry Pi 5** running a
Python control stack, with an **Arduino** motor controller underneath it, an
**Android/Web client**, and a 3D digital twin in the browser.

| Layer | Technology | Role |
| --- | --- | --- |
| Brain | Python 3.13 on Raspberry Pi OS (Debian trixie) | navigation, safety, telemetry, web server, camera |
| Motion | Arduino (C++/`.ino`) | motor PWM, ultrasonic, low-level stop |
| Client | Flutter (Android + Web) | drive / monitor from a phone or browser |
| Firmware | `firmware/arduino/` | the `.ino` and its helpers |
| Bridge | `ros2/bridge.py` | optional ROS 2 integration |

**Only third-party runtime dependency: PyYAML.** Raspberry Pi OS already ships
it (`python3-yaml`). No FastAPI, no uvicorn, no websockets, no build step.

---

## 2. Hardware reality — what is actually connected

This is the part most project documents get wrong, so it is first.

| Item | Status | Evidence |
| --- | --- | --- |
| Raspberry Pi 5 (`amr-pi`) | ✅ **Working** | Debian trixie, kernel `6.18.50+rpt-rpi-2712`, Python 3.13.5 |
| Pi camera (`imx219`, Camera Module v2) | ✅ **Working** | `rpicam-hello --list-cameras` lists it; `rpicam-still` produced a real 664 KB JPEG |
| `picamera2` + `rpicam-apps` | ✅ **Installed** | 0.3.37-1 and 1.13.0-1, "already the newest version" |
| Arduino | ❌ **Not connected** | still in its box |
| Motors (L298N) | ❌ **Not connected** | — |
| Ultrasonic sensors | ❌ **Not connected** | — |
| RFID reader | ❌ **Not connected** | — |
| Robot geometry | ❌ **`null` in config** | `wheel_track_m` / `wheel_diameter_m` must be physically measured |
| Safety thresholds | ⚠️ **`status: NOT_VERIFIED`** | `config/safety.yaml` says so explicitly |

Because the robot is unbuilt, the Pi runs in **mock mode**: the whole robot is
simulated in-process. Commands are accepted and telemetry is generated, but
nothing is sent to hardware. This is deliberate and documented in
`docs/DEPLOY.md`.

**Network:** Pi at `10.125.182.253`, SSH user `joshgree7`, console on port
`8080`.

---

## 3. Software architecture

21,752 lines of Python across 19 packages in `raspberry_pi/amr/`, plus 17,778
lines of tests, plus a 6,622-line Flutter client.

```
raspberry_pi/amr/
├── main.py                  CLI entry point, wiring, --mock / --camera flags
├── __main__.py              python -m amr
├── camera/      (5 files, 1620 lines)   frame sources, overlay, legacy manager
├── communication/(3 files, 514 lines)   Arduino serial, wire protocol
├── control/     (3 files, 237 lines)   differential drive, motor controller
├── hazard/      (8 files, 3049 lines)   hazard events, detection, visualisation
├── logging/     (2 files, 118 lines)    logging setup
├── map/         (6 files, 2133 lines)   2D map, heatmap, 3D twin payload
├── mocks/       (5 files, 252 lines)    mock camera/motor/sensor/serial
├── navigation/  (3 files, 498 lines)    navigator + local navigator
├── net/         (2 files, 281 lines)    connectivity checks
├── rfid/        (2 files, 290 lines)    RFID reader
├── robot/       (4 files, 664 lines)    robot state, modes, manager
├── safety/      (3 files, 531 lines)    safety manager, avoidance
├── sensors/     (2 files, 119 lines)    ultrasonic
├── telemetry/   (10 files, 4263 lines) collector, console, ops, replay
├── utils/       (2 files, 619 lines)    config loading
├── warehouse/   (5 files, 961 lines)    task manager, warehouse map
├── web/         (2 files, 3825 lines)   HTTP server, all 32 routes
└── apps/        (2 files, 410 lines)    application registry
```

### Key modules

| Module | Classes / functions | What it does |
| --- | --- | --- |
| `camera/frame.py` | `CameraStatus`, `CameraFrame`, `CameraSource`, `RaspberryPiCameraSource`, `SimulatedCameraSource`, `pattern_png`, `solid_png` | C8 camera contract. `RaspberryPiCameraSource` prefers **picamera2**, falls back to the **CLI** (`rpicam-still` / `libcamera-still`). |
| `camera/camera_manager.py` | `CameraManager`, `PiCameraBackend`, `CameraError` | the legacy `capture_jpeg()` path. Different contract — see §7. |
| `communication/protocol.py` | — | wire protocol: `PING`, `PONG`, `MOVE`, `SENSOR`, `RANGE`, `STATE`, `STOP`, `STATUS`, `VERSION`, `WATCHDOG`, `ACK`, `ERR` |
| `safety/safety_manager.py` | `SafetyAction`, `SafetyDecision`, `SafetyManager` | layered stop decision |
| `map/twin.py` | `robot_model`, `_floor_frame`, `_waypoints`, `_zones`, `_hazards`, `world_to_three`, `yaw_to_rotation_z` | builds the 3D twin payload |
| `telemetry/ops.py` | `_component_health`, `_sensor_matrix`, `_system_panel`, `_worst`, `_num`, `_txt`, `_section` | builds the `/dashboard/state` ops projection |
| `telemetry/collector.py` | `TelemetryCollector` | gathers the C7 snapshot |
| `web/server.py` | `MapService`, route handlers | hand-written `ThreadingHTTPServer`, 32 routes |
| `robot/robot_manager.py` | `RobotManager`, `RobotCommandError` | command → controller |
| `navigation/navigator.py` | `Navigator`, `LocalNavigator` | waypoint navigation |
| `warehouse/task_manager.py` | `WarehouseTaskManager`, `ManagerStatus` | warehouse task queue |
| `hazard/manager.py` | `HazardManager` | hazard event intake |

---

## 4. Connections — how the data flows

### 4.1 Steady-state path (what runs today)

```
┌─────────────┐   mock controller (in-process)   ┌──────────────────┐
│  amr.main   │ ───────────────────────────────▶ │  mock_serial /   │
│  --mock     │                                  │  mock_motor ...  │
└──────┬──────┘                                  └──────────────────┘
       │ real objects, no hardware
       ▼
┌─────────────┐   CameraFrame contract    ┌──────────────────────┐
│Telemetry-   │ ◀───────────────────────  │ camera/frame.py      │
│Collector    │                           │  ├ RaspberryPiCamera │──▶ picamera2 ──▶ imx219
└──────┬──────┘                           │  │    └ fallback ─── CLI rpicam-still
       │ C7 snapshot                       │  └ SimulatedCamera ─▶ pattern_png
       ▼                                   └──────────────────────┘
┌─────────────┐
│  ops.py     │  builds the ops projection (health, sensors, risk)
└──────┬──────┘
       ▼
┌─────────────┐   HTTP :8080    ┌──────────────────────┐
│ web/server  │ ───────────────▶ command_center.{js,  │──▶ browser
│ .py         │                 │ css,html}  (2799 JS) │──▶ Flutter app
└─────────────┘                 └──────────────────────┘
```

### 4.2 Camera pipeline — the one that has been breaking

Three sources implement the **same** `CameraSource` contract (`read()` →
`CameraFrame`):

| Source | Produces | Status value |
| --- | --- | --- |
| `RaspberryPiCameraSource` (picamera2) | raw RGB array → PNG | `LIVE` / `UNAVAILABLE` / `ERROR` |
| `RaspberryPiCameraSource` (CLI fallback) | bytes from `rpicam-still --encoding=jpg -` | `LIVE` |
| `SimulatedCameraSource` | deterministic PNG test pattern | `SIMULATION` |

`--camera auto` (default) follows `--mock`, i.e. the **simulated** source.
`--camera real` selects the hardware source even in mock mode — necessary
because hardware mode (no `--mock`) additionally requires `pyserial` **and** a
controller answering `PING`, which is impossible while the Arduino is boxed.

### 4.3 Web console views

| View | What it shows |
| --- | --- |
| **Overview** | identity, system panels, robot state, navigation, safety, mission, hazards |
| **3D Twin** | lit WebGL scene — see §6 |
| **Map** | 2D floor, waypoints, robot, hazard markers |
| **Camera** | live feed + overlay + status |
| **Heatmap** | traversal heat map |

### 4.4 HTTP API — all 32 routes

```
/  /health  /status  /telemetry  /sensor  /command  /connectivity
/command-center  /dashboard  /dashboard/state  /applications  /applications/state
/camera  /camera/status  /camera/frame  /camera/overlay  /image
/map  /map.svg  /heatmap  /digital-twin
/hazard  /hazard/acknowledge
/replay/load  /replay/recordings  /replay/play  /replay/pause  /replay/restart
/replay/speed  /replay/status  /replay/unload
/static/…
```

`GET`-only for reads; `/command`, `/hazard/acknowledge` and the replay controls
are the write paths. **There is no browser → GPIO/motor path.**

### 4.5 Physical wiring (not connected yet)

The pin conflicts are documented in `docs/COMPONENTS.md` and `docs/hardware.md`.
They are unresolved because the hardware is unbuilt:

| Finding | Effect |
| --- | --- |
| 🔴 `D4`/`D5` double-booked (motor **and** rear ultrasonic) | must be resolved before wiring |
| 🔴 `ENB = D8` cannot do PWM | right motor cannot be speed-controlled |
| 🟡 Ultrasonic pins all `TODO_VERIFY` | — |
| 🟡 `ULTRASONIC_ENABLED = 0`, `MOTOR_PWM_ENABLED = 0` | firmware features compiled out |
| 🟡 Geometry `null`; safety thresholds `NOT_VERIFIED` | must be measured |

`docs/WIRING_CHECK.md` lists the 8 photographs to take when the parts arrive.

---

## 5. Serial protocol

```
PING / PONG      handshake
MOVE             motion command
SENSOR / RANGE   ultrasonic readings
STATE / STATUS   robot + controller state
STOP             immediate stop
VERSION          firmware version
WATCHDOG         liveness
ACK / ERR        acknowledgement / error
```

`docs/serial_protocol.md` has the full framing.

---

## 6. The 3D digital twin

A hand-written WebGL renderer in `command_center.js` — **no three.js, no build
step**. The payload comes from `map/twin.py`.

What it draws:

- lit robot (per-face Lambert key light + hemisphere ambient), upright wheels
  with hub caps, deck, camera lens, sensor mast, status LED, forward marker
- warehouse floor as a raised deck with a ground plane and horizon
- 0.5 m floor grid, distance fog, contact shadow
- waypoints, planned route, goal, hazards

The payload declares `renderer.shading` honestly — it is no longer `"flat"`,
because the lighting is real. `docs/digital_twin.md` describes the model.

---

## 7. Two camera contracts — do not mix them up

This has caused two separate bugs.

| | C8 (`camera/frame.py`) | Legacy (`camera/camera_manager.py`) |
| --- | --- | --- |
| Method | `read()` → `CameraFrame` | `capture_jpeg()` → `bytes` |
| Used by | web server, telemetry | legacy `CameraManager` only |
| Formats | PNG or JPEG | JPEG |
| Status | honest `LIVE`/`SIMULATION`/`UNAVAILABLE`/`ERROR` | — |

`GET /image` originally called `capture_jpeg()` directly, which **every C8
source lacks** — so it raised `AttributeError` and returned an empty reply (not
even a 503) for the simulated source and a real Pi camera alike. It now goes
through `camera_frame()`, the same path as `/camera/frame`. The bug survived
because the test fixture wires the legacy `CameraManager`, the one case that
worked.

---

## 8. Console charts — counts, never scores

`ops.py` **refuses to invent a health score**: the project defines no weighting,
so a percentage would be fabricated. What it does publish instead:

- **`health.counts`** — how many subsystems sit in each state. Every state is
  present even at zero, so the chart cannot change shape, and the bars sum to a
  number you can verify by counting the table beside them.
- **`risk_frequency`** — a histogram of real `SAFETY` events over a 10-minute
  window, from the same event stream as the safety history. Nothing is
  extrapolated into a rate. An empty bucket still draws a 2px stub, so "no
  events" is a drawn zero rather than an omission — an empty chart and a broken
  feed must never look alike.

Both render in the **Robot Health** card. The **Sensors** panel now shows real
per-face distances with units (`200 cm`), because `_sensor_panel` was only
reading a nested `ultrasonic` list while the runtime publishes flat
`front_cm`/`left_cm`/`right_cm`/`rear_cm` keys — so a robot reporting 200 cm on
every face looked identical to one with nothing wired.

---

## 9. Test suite

| Metric | Value |
| --- | --- |
| Tests collected | 1,620 |
| Passed | **1,618** |
| Skipped | 2 |
| Failed | **0** |
| Test files | 39 (+ `conftest.py`) |
| Test code | 17,778 lines |
| Flutter | `flutter analyze` clean, 31 tests pass |

Run with:

```bash
cd raspberry_pi && ./.venv/bin/python -m pytest
```

### The doc-sync tests (they will bite you)

`tests/test_app_registry.py` checks that documentation matches reality:

- `test_showcase_does_not_go_quietly_stale` — checks **`showcase.html`**, not
  the README
- `test_current_status_test_counts_are_not_stale` — the per-file table in
  `AI_CONTEXT/CURRENT_STATUS.md`

**Adding a test means updating, in the same commit:** README badge + table,
`showcase.html` (badge *and* the "N passed" row), and `CURRENT_STATUS.md`
(totals *and* the changed per-file counts).

Other recurring traps:

1. **JS has no tests but tests constrain it.** `tests/test_command_center.py`
   requires `node --check` validity, balanced delimiters, and the **absence** of
   `"/command"`, `estop(`, `forward(`, `pwm`, `gpio`; `setInterval(` count must
   stay 2. `forward(` is a trap — avoid the substring.
2. **Never name a production helper `test_*`** if a test module imports it —
   pytest collects it as a test.
3. **`grep "a\|b"` fails on macOS/BSD grep** — use `grep -E` or the Grep tool.

---

## 10. Bringing it up

From the Pi, one command:

```bash
cd ~/amr && ./tools/pi_quickstart.sh
```

It finds a working Python, checks the camera, and starts the console in mock
mode. No sudo, no system-wide installs, no GPIO.

```bash
./tools/pi_quickstart.sh --camera real   # use the imx219, controller still mocked
./tools/pi_quickstart.sh --setup         # check only, do not run
CAMERA=real ./tools/pi_quickstart.sh     # same, via the environment
PORT=8081 ./tools/pi_quickstart.sh       # another port
```

The script also clears a stale console: if another `amr.main` holds the port it
is stopped (it would otherwise keep serving old code), and a process that cannot
be proven to be this app is left alone with instructions to inspect it.

Then open `http://<pi-ip>:8080/command-center`, or enter the Pi IP and port
`8080` in the Flutter app's setup wizard.

> **`python3 -m amr.main` must be run from `~/amr/raspberry_pi`**, not `~/amr`.
> The package is `~/amr/raspberry_pi/amr`, so the repo-root invocation dies with
> `No module named 'amr'` — a wrong-directory error that reads like a missing
> install. Use the script, which `cd`s for you.

---

## 11. Documentation

| File | Contents |
| --- | --- |
| `docs/DEPLOY.md` | Pi bring-up, stopping/restarting, stale-console handling |
| `docs/COMPONENTS.md` | component inventory, connection map, wire-by-wire, pin conflicts |
| `docs/hardware.md` | BOM, interfaces, wiring, staged bring-up |
| `docs/WIRING_CHECK.md` | the 8 photographs to take when parts arrive |
| `docs/camera.md` | camera sources, routes, the test pattern |
| `docs/command_center.md` | console UI, the two charts, honesty rules |
| `docs/digital_twin.md` | the 3D model and its limitations |
| `docs/safety.md`, `docs/hazard.md`, `docs/telemetry.md` | subsystems |
| `docs/serial_protocol.md` | wire protocol |
| `docs/map.md`, `docs/heatmap.md`, `docs/replay.md` | mapping and replay |
| `docs/manipulator.md`, `docs/rfid.md`, `docs/ros2.md` | subsystems |
| `AI_CONTEXT/CURRENT_STATUS.md` | test counts, per-file table |
| `README.md`, `showcase.html` | overview and status badge |

---

## 12. Recent work — last 10 commits

| Commit | Change |
| --- | --- |
| `057f45e` | fix(camera): CLI fallback asked for `jpeg`, which `rpicam-still` rejects |
| `e8fc0ef` | feat(pi): `pi_quickstart.sh --camera real`, and the right directory for `amr.main` |
| `5e67725` | fix(pi): quickstart clears a stale console instead of dying on the port |
| `91ea5d2` | feat(camera): `--camera real` — use the Pi camera while the controller is mocked |
| `0893765` | docs: "Address already in use" means a stale server holds the port |
| `996e3e1` | fix(camera): `GET /image` crashed for every C8 camera source |
| `9f4fd0b` | docs: how to stop and restart the Pi console |
| `7c7319d` | feat(console): real sensor values, health bars, risk-frequency histogram |
| `8f87864` | feat(twin): real lighting, fog, contact shadow, floor grid |
| `528e268` | fix: duplicate class definitions, legacy camera CLI, dev extra |

95 commits total on `main`. Remote: `https://github.com/abhijeet1267/amr`.

---

## 13. Open items

| # | Item | Blocked on |
| --- | --- | --- |
| 1 | `D4`/`D5` pin conflict (motor vs rear ultrasonic) | parts + wiring decision |
| 2 | `ENB = D8` cannot do PWM | parts + wiring decision |
| 3 | Ultrasonic pin verification (`TODO_VERIFY`) | hardware |
| 4 | Robot geometry (`wheel_track_m`, `wheel_diameter_m`) | physical measurement |
| 5 | Safety thresholds (`status: NOT_VERIFIED`) | measurement on the real robot |
| 6 | `pyserial` install | attaching the Arduino |
| 7 | Manipulator mount | `implemented: false` in the payload — no arm exists |

---

## 14. One-line status

**The app, camera and console are working and tested (1,618 passing). The robot
is not: it is an unbuilt chassis with the Arduino still in its box, so the Pi
runs in mock mode — which is exactly what that mode is for.**
