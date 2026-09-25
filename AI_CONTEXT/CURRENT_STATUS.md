# CURRENT_STATUS — verified state of the repository

**Last verified:** the C13 working tree — full suite
**973 passed, 2 skipped, 0 failed** (910 at C12 + 63 overlay tests).
Re-verify with the commands below before trusting these numbers.

---

## 1. Verified test run

| Check | Result |
|---|---|
| `cd raspberry_pi && python -m pytest` | **592 passed, 2 skipped, 0 failed** |
| Test files | 23 (`tests/test_*.py`) |
| CI | `.github/workflows/ci.yml` — pytest matrix on Python 3.10/3.11/3.12 + advisory `ruff` |
| Hardware required | **None.** Everything runs on `amr/mocks/` |
| Live web smoke (C2, `--mock --web` + `hazard.enabled=true`) | `GET /hazard` → `attached:true, state:NORMAL, sources:["zones"]`; `POST /hazard/acknowledge` → `ok:true`; `/status` carries the `hazard` key |
| Dashboard smoke (C7, `--mock --web`) | `GET /health` → 200 `ok:true, simulated:true, read_only:true`; `GET /telemetry` → 200 valid schema-1.0 JSON with per-section `source` tags; `GET /dashboard` → 200 HTML |
| 3D twin smoke (C10, `--mock --web`) | `GET /digital-twin` → 200 `source:SIMULATION`, `robot` pose **identical** to `GET /map`, 5 config waypoints, `renderer.library: null`; `GET /dashboard` → 200 containing the 3D card and canvas; `/telemetry`, `/map.svg`, `/camera/status` all 200 |
| Console smoke (C12, `--mock --web --mission-demo`) | `GET /dashboard/state` → 200 `read_only:true`, `source:SIMULATION`; mission `phase:NAVIGATE` → `DROP`, `destination:station`, `mission_progress:0.33`, `total_tasks:3`, `mission_id:web-run`; `mission` **no longer** in `degraded`; all prior endpoints still 200 |
| Console smoke (C11, `--mock --web`) | `GET /dashboard/state` → 200 `read_only:true`, `source:SIMULATION`; `console["map"] == GET /map` and `console["twin"] == GET /digital-twin` **exactly**; battery `UNAVAILABLE` with `note: "no battery source in this build"`; mission `Mission data unavailable` when no warehouse runtime is attached; all prior endpoints still 200 |

The 2 skips are the camera tests that need `opencv-python`/`numpy`; they run when
those are installed and skip gracefully otherwise. They are the only conditional
tests.

Per-file test counts (from `pytest --collect-only -q`):

```
test_camera_manager.py      9    test_motor_controller.py  21
test_config.py             18    test_navigation.py        50
test_differential_drive.py 25    test_protocol.py          37
test_hazard.py             48    test_robot_manager.py     20
test_hazard_visualisation.py 23  test_robot_state.py        5
test_logging.py            12    test_safety_manager.py    14
test_mode_controller.py    13    test_ultrasonic.py         9
test_warehouse.py          39    test_web_server.py        59
test_vision.py             95    test_avoidance.py         76
test_telemetry.py          52    test_map.py              111
test_camera_frame.py       49    test_digital_twin.py      37
test_console.py            35    (new in C11 — operations console)
test_mission_monitoring.py 45    (new in C12 — mission monitoring)
test_camera_overlay.py   40    (new in C13 — camera hazard overlays)
```

---

## 2. Module status

| Module | Status | Evidence |
|---|---|---|
| `communication` (protocol, serial) | **Implemented, unit-tested** | `test_protocol.py` (37) |
| `control` (driver, diff drive) | **Implemented, unit-tested** | `test_motor_controller.py`, `test_differential_drive.py` |
| `safety` (Layer 3, incl. C6 avoidance) | **Implemented, unit-tested, opt-in** | `test_safety_manager.py` (14), `test_avoidance.py` (76) |
| `hazard` (Layer 3.5, incl. `visualisation`, `vision`) | **Implemented, unit-tested, opt-in** | `test_hazard.py` (48), `test_hazard_visualisation.py` (23), `test_vision.py` (95), `python -m amr.hazard`, `python -m amr.hazard.vision` |
| `sensors` (ultrasonic validation) | **Implemented, unit-tested** | `test_ultrasonic.py` |
| `robot` (manager, modes, state) | **Implemented, unit-tested** | `test_robot_manager.py`, `test_mode_controller.py`, `test_robot_state.py` |
| `camera` | **Implemented, partially tested** (2 tests need OpenCV) | `test_camera_manager.py` |
| `navigation` (incl. C6 avoidance gate) | **Implemented, unit-tested** | `test_navigation.py` (50), `test_avoidance.py` (76) |
| `warehouse` (tasks, map, manipulator) | **Implemented, unit-tested** | `test_warehouse.py` (39) |
| `telemetry` (C7 read-only contract + collector) | **Implemented, unit-tested** | `test_telemetry.py` (46) |
| `web` (panel + dashboard + JSON API over a real HTTP server) | **Implemented, unit-tested** | `test_web_server.py` (69), incl. `GET /hazard` + acknowledge (C2), `/telemetry` `/health` `/dashboard` (C7), `/map` + `/map.svg` (C9), `/digital-twin` (C10) and `/dashboard/state` (C11) |
| `map` (C9 2D state + SVG, C10 3D twin state) | **Implemented, unit-tested** | `test_map.py` (111), `test_digital_twin.py` (37) |
| `telemetry` (C7 contract, C11 console, C12 mission monitoring) | **Implemented, unit-tested** | `test_telemetry.py` (52), `test_console.py` (35), `test_mission_monitoring.py` (45) |
| `logging` | **Implemented, unit-tested** | `test_logging.py` |
| `utils/config` | **Implemented, unit-tested** | `test_config.py` (18) |
| `mocks` | **Implemented**, indirectly covered by every suite | — |

### Offline entry points that are known to work

```
python -m amr.main --mock            # headless tick loop
python -m amr.main --mock --web      # web panel, mock stack
python -m amr.main --demo            # scripted CLI demo, exits 0
python -m amr.warehouse              # dock -> shelf_a(pick) -> station(place) -> dock; "RESULT: completed=3 failed=0"
python -m amr.hazard                 # hazard scenario; "RESULT: steps=4 failures=0"
python -m amr.hazard.vision          # C5 vision->hazard scenarios (SIMULATED input)
python -m amr.hazard.visualisation   # render the events JSONL onto the map (SVG)
```

---

## 3. What is NOT verified — read before trusting the robot

> These are the honest gaps. Do **not** describe them as complete.

| Item | State | Blocker |
|---|---|---|
| Robot geometry (`wheel_track_m`, `wheel_diameter_m`) | **`null`** | Must be measured physically. Odometry/navigation math is unvalidated until then. |
| Safety thresholds (`config/safety.yaml`) | **`NOT_VERIFIED`** | Test values. Must be confirmed on hardware. |
| Hazard thresholds (`config/hazard.yaml`) | **`NOT_VERIFIED`**, `enabled: false` | Sensor-specific; no gas/fire sensor hardware exists yet. |
| Ultrasonic trig/echo pins | **`TODO_VERIFY`** | Wiring not documented; pins deliberately not invented. |
| Camera cable compatibility | Unconfirmed | Software degrades gracefully when absent. |
| Arduino firmware | **Never executed in CI** | No Arduino toolchain in CI; requires a physical UNO. |
| L298N ENA/ENB wiring | Unverified | PWM output is gated until confirmed. |
| Anything on real hardware | **Not tested** | Every claim above is mock-based. |

### Hardware-dependent (untested here)

* Motor direction/PWM polarity, encoder/odometry accuracy, real stop distances.
* The watchdog and proximity stop in `firmware/arduino/amr_controller/safety.cpp`.
* The serial link itself (`/dev/ttyACM0` @ 9600).
* Any gas/fire/human sensor — **none are wired at all**.

---

## 4. Known issues / debt

* `docs/safety.md` links to `docs/architecture.md`, which **does not exist**. The
  architecture content lives in `README.md`, `assets/architecture.svg` and now
  `AI_CONTEXT/ARCHITECTURE.md`. *Stale link, cosmetic.*
* `amr.hazard` is **wired into `amr/web`** (C2: `GET /hazard` +
  `POST /hazard/acknowledge`, opt-in via `config.hazard.enabled`) but **still
  not wired into `amr/warehouse`** — task scheduling ignores the hazard verdict.
* **No hazard sensor sources are wired.** `amr/main.py` attaches the layer
  without sources (no hardware); `RobotStateSource` is deliberately not
  auto-wired because `RobotState.last_error` is sticky and would pin `WARNING`
  forever after the first E-STOP.
* `VisionHazardSource` is now a **working pipeline, not a seam** (C5): the
  `VisionDetection` contract, a deterministic `SimulatedVisionDetector` and the
  end-to-end path into the event log / C3 map / C2 web API are implemented and
  tested. What is still missing is a **real detector**: no OpenCV, YOLO or
  hardware camera backend is wired, and the thresholds in `config/hazard.yaml`
  are unvalidated software defaults.
* C6 activated `TURN` / `REPLAN` for **non-blocking** obstacles
  (`amr/safety/avoidance.py` + an avoidance gate in `LocalNavigator`).
  `STOP`/`WAIT` are returned unchanged and a critical obstacle still takes the
  pre-existing hazard→`RobotManager` path, so emergency stop keeps priority.
  **Software/simulation only**, `enabled: false` by default, all thresholds
  NOT_VERIFIED. The ultrasonic clearance provider is **not yet wired**, so in
  the default configuration avoidance replans rather than steering.
* Web panel has **no authentication** — LAN-only, single operator.

---

## 5. Not started at all

| Area | Evidence |
|---|---|
| **ROS 2** | Zero occurrences of `rclpy`/`ros2`/`ament`/`colcon` in code (only future-tense mentions in docstrings). Navigation is a dependency-free `LocalNavigator`. |
| **RFID** | Zero occurrences anywhere. |
| **Real manipulator** | `warehouse.yaml` uses `manipulator: "mock"`; only `MockManipulator` / `NullManipulator` exist. |
| **Vision / marker / QR / shelf recognition** | No implementation; `CameraManager.capture()` is the seam. |
| **Gas / smoke / fire hardware** | No sensor code, no pins, no drivers — `amr.hazard` provides the aggregation layer and the seam. |
| **Telemetry / dashboard** | No *live* dashboard. A static hazard map renderer exists (`amr.hazard.visualisation`, C3); `RobotManager.snapshot()` and `HazardManager.snapshot()` remain the JSON sources a live dashboard would consume. |
