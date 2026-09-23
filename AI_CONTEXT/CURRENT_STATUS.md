# CURRENT_STATUS — verified state of the repository

**Last verified:** commit `dfa70c6` (baseline) + the working tree described in
`HANDOFF.md`. Re-verify with the commands below before trusting these numbers.

---

## 1. Verified test run

| Check | Result |
|---|---|
| `cd raspberry_pi && python -m pytest` | **333 passed, 2 skipped, 0 failed** |
| Test files | 16 (`tests/test_*.py`) |
| CI | `.github/workflows/ci.yml` — pytest matrix on Python 3.10/3.11/3.12 + advisory `ruff` |
| Hardware required | **None.** Everything runs on `amr/mocks/` |

The 2 skips are the camera tests that need `opencv-python`/`numpy`; they run when
those are installed and skip gracefully otherwise. They are the only conditional
tests.

Per-file test counts (from `pytest --collect-only -q`):

```
test_camera_manager.py   9     test_navigation.py     50
test_config.py          18     test_protocol.py       37
test_differential_drive.py 25  test_robot_manager.py  20
test_hazard.py          48     test_robot_state.py     5
test_logging.py         12     test_safety_manager.py 14
test_mode_controller.py 13     test_ultrasonic.py      9
test_motor_controller.py 21    test_warehouse.py      39
                               test_web_server.py     15
```

---

## 2. Module status

| Module | Status | Evidence |
|---|---|---|
| `communication` (protocol, serial) | **Implemented, unit-tested** | `test_protocol.py` (37) |
| `control` (driver, diff drive) | **Implemented, unit-tested** | `test_motor_controller.py`, `test_differential_drive.py` |
| `safety` (Layer 3) | **Implemented, unit-tested** | `test_safety_manager.py` (14) |
| `hazard` (Layer 3.5) | **Implemented, unit-tested, opt-in** | `test_hazard.py` (48), `python -m amr.hazard` |
| `sensors` (ultrasonic validation) | **Implemented, unit-tested** | `test_ultrasonic.py` |
| `robot` (manager, modes, state) | **Implemented, unit-tested** | `test_robot_manager.py`, `test_mode_controller.py`, `test_robot_state.py` |
| `camera` | **Implemented, partially tested** (2 tests need OpenCV) | `test_camera_manager.py` |
| `navigation` | **Implemented, unit-tested** | `test_navigation.py` (50) |
| `warehouse` (tasks, map, manipulator) | **Implemented, unit-tested** | `test_warehouse.py` (39) |
| `web` (panel + JSON API over a real HTTP server) | **Implemented, unit-tested** | `test_web_server.py` (15) |
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
* `amr.hazard` is **not yet wired into `amr/web` or `amr/warehouse`**. The
  manager exposes a JSON `snapshot()`; the consumers are unwritten.
* No spatial hazard visualisation exists. Events are exported as JSONL and
  carry locations, but nothing renders them.
* `VisionHazardSource` is a *seam* only — no detector model is implemented.
* Aggressive obstacle avoidance is intentionally absent:
  `SafetyAction.TURN` / `REPLAN` are reserved and never emitted by Layer 3.
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
| **Telemetry / dashboard** | No dashboard code; `RobotManager.snapshot()` and `HazardManager.snapshot()` are the JSON sources it would consume. |
