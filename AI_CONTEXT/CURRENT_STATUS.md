# CURRENT_STATUS — verified state of the repository

**Last verified:** 2026-10-09, C19 spatial heat map merged — full suite
**1675 passed, 2 skipped, 0 failed**.
Re-verify with the commands below before trusting these numbers.

---

## 1. Verified test run

| Check                                                       | Result                                                                                                                                                                                                                                                                                                                                 |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cd raspberry_pi && python -m pytest`                       | **1675 passed, 2 skipped, 0 failed**                                                                                                                                                                                                                                                                                                   |
| Test files                                                  | 41 (`tests/test_*.py`)                                                                                                                                                                                                                                                                                                                 |
| `python -m compileall amr`                                  | clean                                                                                                                                                                                                                                                                                                                                  |
| Orphan scan (every module imported by prod or tests)        | none — no dead modules                                                                                                                                                                                                                                                                                                                 |
| CI                                                          | `.github/workflows/ci.yml` — pytest matrix on Python 3.10/3.11/3.12 + advisory `ruff`                                                                                                                                                                                                                                                  |
| Hardware required                                           | **None.** Everything runs on `amr/mocks/`                                                                                                                                                                                                                                                                                              |
| Live app boot (not a fixture)                               | `python -m amr.main --mock --mission-demo --web` → 30 routes registered, all 20 exercised → 200, 0 bad                                                                                                                                                                                                                                 |
| Applications Hub                                            | `/applications` renders **25** applications; 17 openable, 13 of them deep links into a real Command Center view (asserted to resolve); `/applications/state` 200                                                                                                                                                                       |
| Logging (health pass)                                       | `logs/amr.log` created and written; `/health` → `{"active":true,"file":"amr.log","writable":true,"level":"INFO"}`                                                                                                                                                                                                                      |
| Live web smoke (C2, `--mock --web` + `hazard.enabled=true`) | `GET /hazard` → `attached:true, state:NORMAL, sources:["zones"]`; `POST /hazard/acknowledge` → `ok:true`; `/status` carries the `hazard` key                                                                                                                                                                                           |
| Dashboard smoke (C7, `--mock --web`)                        | `GET /health` → 200 `ok:true, simulated:true, read_only:true`; `GET /telemetry` → 200 valid schema-1.0 JSON with per-section `source` tags; `GET /dashboard` → 200 HTML                                                                                                                                                                |
| 3D twin smoke (C10, `--mock --web`)                         | `GET /digital-twin` → 200 `source:SIMULATION`, `robot` pose **identical** to `GET /map`, 5 config waypoints, `renderer.library: null`; `GET /dashboard` → 200 containing the 3D card and canvas; `/telemetry`, `/map.svg`, `/camera/status` all 200                                                                                    |
| Console smoke (C12, `--mock --web --mission-demo`)          | `GET /dashboard/state` → 200 `read_only:true`, `source:SIMULATION`; mission `phase:NAVIGATE` → `DROP`, `destination:station`, `mission_progress:0.33`, `total_tasks:3`, `mission_id:web-run`; `mission` **no longer** in `degraded`; all prior endpoints still 200                                                                     |
| Console smoke (C11, `--mock --web`)                         | `GET /dashboard/state` → 200 `read_only:true`, `source:SIMULATION`; `console["map"] == GET /map` and `console["twin"] == GET /digital-twin` **exactly**; battery `UNAVAILABLE` with `note: "no battery source in this build"`; mission `Mission data unavailable` when no warehouse runtime is attached; all prior endpoints still 200 |
| Heat map smoke (C19, `--mock --web --mission-demo`)         | `GET /heatmap` → 200, both grids on one shared extent (20×16 @ 0.25 m); `console["heatmap"] == GET /heatmap` **exactly**; after a driven mission `traffic` reports 81 samples over 31 cells, `clipped: 0`; `hazard` is empty on the shipped config (no sensor exists) and says so; all prior endpoints still 200                       |

The 2 skips are the camera tests that need `opencv-python`/`numpy`; they run when
those are installed and skip gracefully otherwise. They are the only conditional
tests.

Per-file test counts (regenerated from `pytest --collect-only -q` — 41 files,
1682 tests: 1680 run + 2 skipped):

```
test_advanced_command_center.py 35    test_mode_controller.py        13
test_app_registry.py           46
test_applications_hub.py       27    test_motor_controller.py       21
test_auto_record.py            27    test_navigation.py             50
test_avoidance.py              76    test_ops_projection.py         52
test_camera_backend.py         50    test_protocol.py               41
test_camera_frame.py           60    test_replay.py                 59
test_camera_manager.py          9    test_replay_control.py         68
test_camera_overlay.py         40    test_rfid.py                   63
test_command_center.py         71    test_robot_manager.py          25
test_config.py                 25    test_robot_state.py             5
test_connectivity.py           14    test_ros_bridge.py             25
test_console.py                39    test_safety_manager.py         14
test_differential_drive.py     25    test_startup_banner.py          2
test_digital_twin.py           37    test_telemetry.py              52
test_environment.py            18    test_ultrasonic.py              9
test_hazard.py                 48    test_unified_demo.py           30
test_hazard_visualisation.py   23
test_heatmap.py                35    test_vision.py                101
test_logging.py                17    test_warehouse.py              61
test_map.py                   111    test_web_server.py            113
test_mission_monitoring.py     45
```

C17 added `test_rfid.py` (63), C18 added `test_ros_bridge.py` (25), C16
added 22 gripper tests (18 in `test_warehouse.py`, 3 config-validation in
`test_config.py`, 1 factory test) and C19 added `test_heatmap.py` (35) plus 18
tests across `test_web_server.py` (the `/heatmap` route and its read-only
guarantee) and `test_command_center.py` (the heat-map view, the two graphs, and
the light-by-default theme); the header, file count and total above were
regenerated from the same measured `pytest --collect-only -q` run.

---

## 2. Module status

| Module                                                         | Status                                                  | Evidence                                                                                                                                                                                   |
| -------------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `communication` (protocol, serial)                             | **Implemented, unit-tested**                            | `test_protocol.py` (37)                                                                                                                                                                    |
| `control` (driver, diff drive)                                 | **Implemented, unit-tested**                            | `test_motor_controller.py`, `test_differential_drive.py`                                                                                                                                   |
| `safety` (Layer 3, incl. C6 avoidance)                         | **Implemented, unit-tested, opt-in**                    | `test_safety_manager.py` (14), `test_avoidance.py` (76)                                                                                                                                    |
| `hazard` (Layer 3.5, incl. `visualisation`, `vision`)          | **Implemented, unit-tested, opt-in**                    | `test_hazard.py` (48), `test_hazard_visualisation.py` (23), `test_vision.py` (101), `python -m amr.hazard`, `python -m amr.hazard.vision`                                                  |
| `sensors` (ultrasonic validation)                              | **Implemented, unit-tested**                            | `test_ultrasonic.py`                                                                                                                                                                       |
| `sensors` (DHT11 + MQ gas, telemetry-only)                     | **Implemented, unit-tested**                            | `test_environment.py` (18); **MQ gas is UNAVAILABLE — no analog pin is assigned**                                                                                                          |
| `robot` (manager, modes, state)                                | **Implemented, unit-tested**                            | `test_robot_manager.py`, `test_mode_controller.py`, `test_robot_state.py`                                                                                                                  |
| `camera`                                                       | **Implemented, partially tested** (2 tests need OpenCV) | `test_camera_manager.py`                                                                                                                                                                   |
| `navigation` (incl. C6 avoidance gate)                         | **Implemented, unit-tested**                            | `test_navigation.py` (50), `test_avoidance.py` (76)                                                                                                                                        |
| `warehouse` (tasks, map, manipulator, C16 gripper backend)     | **Implemented, unit-tested**                            | `test_warehouse.py` (60); `manipulator: "gripper"` needs an injected `GripperActuator` — **no gripper hardware exists**, shipped default is `mock`                                         |
| `rfid` (C17 shelf/payload identification, opt-in)              | **Implemented, unit-tested, opt-in**                    | `test_rfid.py` (63); shipped default attaches no reader (`rfid.backend: "null"`)                                                                                                           |
| `ros2` (C18 dependency-free translation bridge)                | **Implemented, unit-tested**                            | `test_ros_bridge.py` (25); no `rclpy` anywhere; `ros2/amr_bringup` (the rclpy node) **not built**                                                                                          |
| `telemetry` (C7 read-only contract + collector)                | **Implemented, unit-tested**                            | `test_telemetry.py` (52)                                                                                                                                                                   |
| `web` (panel + dashboard + JSON API over a real HTTP server)   | **Implemented, unit-tested**                            | `test_web_server.py` (101), incl. `GET /hazard` + acknowledge (C2), `/telemetry` `/health` `/dashboard` (C7), `/map` + `/map.svg` (C9), `/digital-twin` (C10) and `/dashboard/state` (C11) |
| `map` (C9 2D state + SVG, C10 3D twin state, C19 heat map)     | **Implemented, unit-tested**                            | `test_map.py` (111), `test_digital_twin.py` (37), `test_heatmap.py` (35)                                                                                                                   |
| `telemetry` (C7 contract, C11 console, C12 mission monitoring) | **Implemented, unit-tested**                            | `test_telemetry.py` (52), `test_console.py` (35), `test_mission_monitoring.py` (45)                                                                                                        |
| `logging`                                                      | **Implemented, unit-tested**                            | `test_logging.py`                                                                                                                                                                          |
| `utils/config`                                                 | **Implemented, unit-tested**                            | `test_config.py` (25)                                                                                                                                                                      |
| `mocks`                                                        | **Implemented**, indirectly covered by every suite      | —                                                                                                                                                                                          |

### Offline entry points that are known to work

```
python -m amr.main --mock            # headless tick loop
python -m amr.main --mock --web      # web panel, mock stack
python -m amr.main --mock --demo     # scripted CLI demo, exits 0
python -m amr.warehouse              # dock -> shelf_a(pick) -> station(place) -> dock; "RESULT: completed=3 failed=0"
python -m amr.hazard                 # hazard scenario; "RESULT: steps=4 failures=0"
python -m amr.hazard.vision          # C5 vision->hazard scenarios (SIMULATED input)
python -m amr.hazard.visualisation   # render the events JSONL onto the map (SVG)
```

---

## 3. What is NOT verified — read before trusting the robot

> These are the honest gaps. Do **not** describe them as complete.

> **Hardware WAS exercised on 2026-10-13** (Pi 5 + UNO). The firmware compiled
> (44% flash / 32% RAM) and flashed, `PING`/`VERSION`/`STATUS`/`SENSOR` answered,
> four live ultrasonic distances were read, and the camera served a 1280×720
> PNG. Three real defects were found this way and fixed (picamera2 config,
> picamera2 venv visibility, serial DTR reset) — see `docs/camera.md` §1a.
> Everything below remains genuinely unverified.

| Item                                                 | State                                | Blocker                                                                           |
| ---------------------------------------------------- | ------------------------------------ | --------------------------------------------------------------------------------- |
| Robot geometry (`wheel_track_m`, `wheel_diameter_m`) | **`null`**                           | Must be measured physically. Odometry/navigation math is unvalidated until then.  |
| Safety thresholds (`config/safety.yaml`)             | **`NOT_VERIFIED`**                   | Test values. Must be confirmed on hardware.                                       |
| Hazard thresholds (`config/hazard.yaml`)             | **`NOT_VERIFIED`**, `enabled: false` | Sensor-specific; **no gas sensor is wired** (no analog pin free).                 |
| Motor drive / PWM polarity (L298N)                   | **Untested**                         | Firmware compiled and flashed, but no wheel has been commanded to move.           |
| Wheel direction & real stop distances                | **Untested**                         | Requires a bench test with the wheels off the ground.                             |
| DHT11 temperature/humidity                           | **Not reading** (`T=-1 H=-1`)        | Likely a missing ~10 kΩ pull-up; telemetry-only, blocks nothing.                  |
| MQ gas sensor                                        | **No pin assigned**                  | The pin chart uses all 20 UNO pins. Reports `UNAVAILABLE`, never a fake 0.        |
| LCD / buzzer on hardware                             | **Commands verified, effect not**    | `ACK LCD` / `ACK BUZZ` returned; whether the display/audio worked is unconfirmed. |
| Arduino firmware in CI                               | **Never executed in CI**             | No AVR toolchain in CI; flashed by hand on the Pi only.                           |

### Hardware-dependent (now partly exercised)

- **Verified 2026-10-13:** firmware compiles/flashes; serial link
  (`PING`/`VERSION`/`STATUS`); four ultrasonic readings; picamera2 frame capture.
- **Still untested:** motor direction/PWM polarity, encoder/odometry accuracy,
  real stop distances, the safety watchdog tripping during an actual drive, and
  any autonomous motion.
- The watchdog and proximity stop in `firmware/arduino/amr_controller/safety.cpp`.
- The serial link itself (`/dev/ttyACM0` @ 9600).
- Any gas/fire/human sensor — **none are wired at all**.

---

## 4. Known issues / debt

- ~~`docs/safety.md` links to `docs/architecture.md`~~ — **resolved (C19)**: the
  stale reference is gone from both `docs/safety.md` and
  `raspberry_pi/amr/logging/logger.py`, and the architecture content lives in
  `README.md`, `assets/architecture.svg` and `AI_CONTEXT/ARCHITECTURE.md`.
  Checked: `docs/` now has **no** broken relative `.md` links.
- **`safety.watchdog_timeout_ms` never reaches the firmware.** The Pi uses it
  only for its own link-loss detection (`robot_manager.py:221`), and nothing on
  the Pi ever sends the `WDT <ms>` verb the firmware implements and
  `docs/serial_protocol.md` documents. The Arduino therefore keeps its
  compiled-in `DEFAULT_WATCHDOG_MS` (1000 ms), which today _happens_ to equal
  `safety.yaml`. Raise the config and the two diverge silently: the Arduino
  stops the robot after 1 s of silence while the Pi still believes the link is
  healthy. Fix is additive (a `build_wdt` + a send at connect) but it changes
  hardware safety timing, so it needs a real UNO to verify.
- **`--demo` is not mock-guarded, unlike `--mission-demo`.** `run_demo()` issues
  `forward(100)` and `rotate_right(80)` (`main.py:268-269`), so on a bench with an
  Arduino attached `python -m amr.main --demo` **drives the robot** with no
  operator confirmation. `--mission-demo` was deliberately made mock-only for
  exactly this reason ("it commands autonomous motion ... refused against real
  hardware"), so the two flags are inconsistent. Without `--mock` and without
  hardware it exits 1 (documented in `HANDOFF.md`). Decide: guard it like
  `--mission-demo`, or document it as an intentional hardware bring-up check.
- `amr.hazard` is **wired into `amr/web`** (C2: `GET /hazard` +
  `POST /hazard/acknowledge`, opt-in via `config.hazard.enabled`) but **still
  not wired into `amr/warehouse`** — task scheduling ignores the hazard verdict.
- **No hazard sensor sources are wired.** `amr/main.py` attaches the layer
  without sources (no hardware); `RobotStateSource` is deliberately not
  auto-wired because `RobotState.last_error` is sticky and would pin `WARNING`
  forever after the first E-STOP.
- `VisionHazardSource` is a **working pipeline, not a seam** (C5): the
  `VisionDetection` contract, a deterministic `SimulatedVisionDetector` and the
  end-to-end path into the event log / C3 map / C2 web API are implemented and
  tested. What is still missing is a **real detector**: no OpenCV, YOLO or
  camera-backed detector is wired, and the thresholds in `config/hazard.yaml`
  are unvalidated software defaults.
  _(Note: a real acquisition backend does exist — `RaspberryPiCameraSource`,
  selected by `main.py:134` in hardware mode — but it is a stub-library-tested
  code path. **Camera hardware: NOT TESTED.**)_
- C6 activated `TURN` / `REPLAN` for **non-blocking** obstacles
  (`amr/safety/avoidance.py` + an avoidance gate in `LocalNavigator`).
  `STOP`/`WAIT` are returned unchanged and a critical obstacle still takes the
  pre-existing hazard→`RobotManager` path, so emergency stop keeps priority.
  **Software/simulation only**, `enabled: false` by default, all thresholds
  NOT_VERIFIED. The ultrasonic clearance provider is **not yet wired**, so in
  the default configuration avoidance replans rather than steering.
- Web panel has **no authentication** — LAN-only, single operator.
- `log_dir=None` now means the **default** directory; `log_dir=False` is the
  explicit opt-out (health pass, 2026-09-28). This changed a documented
  contract on purpose: `main.py` used to call `setup_logging(console=False)`,
  which installed **zero** handlers and silently discarded every log record.
  `/health` now reports `logging` state so this can never silently regress.

---

## 5. Not started at all

| Area                                | Evidence                                                                                                                                                                                                                                                                                                                                     |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ROS 2 (runtime)**                 | The **translation bridge** exists (`ros2/bridge.py`, C18, `test_ros_bridge.py` 25) but **zero `rclpy` imports anywhere**: no node, no publisher, no subscription, no `ros2/amr_bringup` package, no ROS in CI. No topic has ever been published or received by this code. Navigation is a dependency-free `LocalNavigator`.                  |
| **RFID hardware**                   | No antenna, no reader, no real tag. C17 ships the reader contract (`amr/rfid.RfidReader`), the pick/place identification rule (`confirm`), and a `simulated` backend tested end to end (`test_rfid.py`, 63). Shipped default attaches no reader.                                                                                             |
| **Real manipulator (hardware)**     | C16 ships the _driver_ — `GripperActuator` protocol + `GripperManipulator` + the `"gripper"` config backend, tested end to end with a fake actuator (`test_warehouse.py` 60). **No servo, no arm, no firmware verb exists**: the factory refuses `"gripper"` without an injected actuator, and `warehouse.yaml` ships `manipulator: "mock"`. |
| **Marker / QR / shelf recognition** | No implementation; `CameraManager.capture()` is the seam.                                                                                                                                                                                                                                                                                    |
| **Gas / smoke / fire hardware**     | No sensor code, no pins, no drivers — `amr.hazard` provides the aggregation layer and the seam.                                                                                                                                                                                                                                              |
| **Real hazard detector**            | `VisionHazardSource` is a working pipeline over a **simulated** detector. No YOLO, no OpenCV, no camera-backed detector. Thresholds in `config/hazard.yaml` are unvalidated software defaults.                                                                                                                                               |
| **Authentication**                  | The web panel has none. LAN-only, single operator.                                                                                                                                                                                                                                                                                           |
