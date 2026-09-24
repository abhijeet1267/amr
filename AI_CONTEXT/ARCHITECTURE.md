# ARCHITECTURE — AMR Smart-Warehouse Platform

Verified against the code in this repository. When you change structure, update
this file **and** the diagram in `assets/architecture.svg` (README).

---

## 1. Runtime split

```
┌──────────────────────── Raspberry Pi (brain) ─────────────────────────┐
│  web (stdlib HTTP)        warehouse (tasks)        camera (optional)  │
│                     └──────────┬──────────┘                           │
│                    navigation (odometry, waypoints)                   │
│                                │                                      │
│                    ┌───────────▼───────────┐      layer 3.5           │
│                    │      RobotManager     │◄──── HazardManager       │
│                    │  (the ONLY motion     │      (NORMAL/WARNING/    │
│                    │   gate; owns state)   │       SLOW/STOP/         │
│                    └───┬───────────┬───────┘       EMERGENCY)         │
│        ┌───────────────┤           │                                  │
│        ▼               ▼           ▼                                  │
│   safety (L3)     control      sensors                                │
│   SafetyManager   DiffDrive    UltrasonicManager                      │
│        └───────────────┴───────────┴─────────► communication          │
│                                                protocol.py            │
└────────────────────────────────┬──────────────────────────────────────┘
                                 │ USB CDC serial, 9600 8N1, text protocol
┌────────────────────────────────▼──────────────────────────────────────┐
│                    Arduino UNO (reflexes)                             │
│  protocol.cpp   safety.cpp (watchdog + proximity stop)                │
│  motor_control.cpp (L298N PWM + direction)   ultrasonic.cpp           │
└───────────────────────────────────────────────────────────────────────┘
```

The split is deliberate: the Pi runs everything that may be slow or buggy; the
Arduino runs the small loop that must not miss a beat. The Arduino **boots
stopped**, moves only on explicit commands, and can stop on its own — so a Pi
crash, reboot, or pulled cable can never leave the robot driving.

---

## 2. Layers (bottom → top)

Each layer depends only on the layers below it.

| # | Package | Responsibility | Key types |
|---|---|---|---|
| 1 | `amr.communication` | Serial protocol + transport | `protocol.py`, `ArduinoSerial`, `ArduinoSerialTransport` |
| 2 | `amr.control` | Motor driver + differential-drive vocabulary | `MotorDriver`, `ArduinoMotorDriver`, `DifferentialDrive`, `clamp_speed` |
| 3 | `amr.safety` | Deterministic proximity policy | `SafetyManager`, `SafetyDecision`, `SafetyAction` |
| 3.5 | `amr.hazard` | Context-aware multi-hazard aggregation + read-side spatial visualisation | `HazardManager`, `HazardSource`, `HazardState`, `HazardEventLog`, `render_map_svg` |
| 4 | `amr.sensors` | Ultrasonic read + validation | `UltrasonicManager`, `UltrasonicReading` |
| 5 | `amr.robot` | The gated runtime owner | `RobotManager`, `RobotState`, `ModeController`, `RobotMode` |
| 6 | `amr.camera` | Camera facade (libcamera / V4L2 / mock) | `CameraManager` |
| 7 | `amr.navigation` | Odometry + waypoint planning | `Navigator`, `LocalNavigator`, `Pose`, `Goal`, `NavResult` |
| 8 | `amr.warehouse` | Task queue + orchestration | `WarehouseTaskManager`, `WarehouseMap`, `Task`, `Manipulator` |
| 9 | `amr.web` | HTTP control panel + JSON API | `AMRWebApp` |
| — | `amr.mocks` | Hardware-free doubles | `MockSerialTransport`, `MockMotorDriver`, `MockUltrasonicSensor`, `MockCamera` |
| — | `amr.logging` | Rotating structured logging | `setup_logging`, `get_logger`, `log_event` |
| — | `amr.utils` | Config loading + validation | `load_config`, `AppConfig`, `SerialConfig`, `SafetyConfig`, `RobotConfig`, `WarehouseConfig`, `HazardConfig` |

---

## 3. The gate — `RobotManager`

`RobotManager` is the single owner of runtime behaviour and the **only** path to
the motors.

* Owns `RobotState` (the one published snapshot), `ModeController`,
  `SafetyManager`, `UltrasonicManager`, `DifferentialDrive`.
* `_gate()` rejects a motion command unless: connected **and** the mode allows
  motion **and** the safety decision is `PROCEED` **and** (when attached) the
  hazard verdict does not block.
* `stop()` / `estop()` are **never** gated — you must always be able to stop.
* `tick()` is one control-loop iteration: poll sensors → evaluate Layer 3 →
  enforce `STOP` → evaluate Layer 3.5 (if attached) → enforce its veto.
* `request_mode()` enforces the mode machine; entering `AUTONOMOUS` additionally
  requires a `PROCEED` decision.

### Mode state machine

```
IDLE ──► MANUAL ──► AUTONOMOUS
   └──────┴─────────┴──► SAFETY_STOP   (sensor / comm / watchdog / hazard fault)
   └──────┴─────────┴──► ERROR         (unrecoverable, needs a human)
SAFETY_STOP / ERROR ──► IDLE           (only after an explicit operator reset)
```

`SAFETY_STOP` is reachable from any mode and is **never auto-released**.

---

## 4. Safety layers

| Layer | Where | Mechanism | Can stop the robot alone |
|---|---|---|---|
| 1 | Arduino firmware | comms watchdog (1000 ms) + proximity stop below thresholds | yes |
| 2 | Pi, `RobotState` | structured state from `STATUS`/`SENSOR` polls, link-loss detection | yes (`_on_link_loss`) |
| 3 | Pi, `amr.safety` | deterministic proximity rules → `PROCEED/WAIT/STOP/TURN/REPLAN` | yes |
| 3.5 | Pi, `amr.hazard` | multi-input aggregation → `NORMAL/WARNING/SLOW/STOP/EMERGENCY` | yes (escalate-only) |

Layer 3.5 hard rules: **escalate only**, **never drive**, **fail safe**,
**deterministic**. It is opt-in via `RobotManager.attach_hazard()`, so the
default stack is behaviourally identical to the pre-hazard code. See
`docs/hazard.md`.

A reading of `-1` (no echo / clear) is *not* an obstacle, per direction.
A complete loss of valid sensor data **is** unsafe (Layer 3 rule 2).

---

## 5. Serial protocol

`amr/communication/protocol.py` is the single source of truth for the text
grammar; the firmware mirrors it (`firmware/arduino/amr_controller/protocol.*`).
Full reference: `docs/serial_protocol.md`. Do not change one side alone.

---

## 6. Configuration

`amr/utils/config.py` loads `config/*.yaml` → typed dataclasses → validates
fail-fast (`ConfigError`). A missing file yields documented defaults; a
malformed file raises. Unknown keys are ignored (forward-compatible).

| File | Dataclass |
|---|---|
| `serial.yaml` | `SerialConfig` |
| `safety.yaml` | `SafetyConfig` |
| `robot.yaml` | `RobotConfig` (motors, ultrasonic pins, camera) |
| `warehouse.yaml` | `WarehouseConfig` (map, tuning, manipulator) |
| `hazard.yaml` | `HazardConfig` (thresholds, kinds, zones, event log) |

Status flags: `safety.yaml` and `hazard.yaml` are `NOT_VERIFIED`, and
`robot.yaml` geometry is `null`, until measured on the physical robot.

---

## 7. Testability architecture

* **`amr/mocks/`** lets the entire high-level stack run with no hardware:
  `MockSerialTransport` emulates the Arduino protocol, `MockMotorDriver` records
  speeds, `MockUltrasonicSensor` sets ranges, `MockCamera` fakes frames.
* `RobotManager.create_mock(config)` wires the full stack over the mock
  transport — the **same code path** as hardware; only the transport differs.
* New components must follow this pattern: depend on **injected callables**, not
  on hardware. `amr.hazard` sources are the newest example.
* Import discipline: no module may require `pyserial`, OpenCV or ROS *to
  import*. `amr.hazard` deliberately imports nothing from `amr.robot` /
  `amr.navigation` (duck typing) to avoid import cycles — it is imported *by*
  the robot manager.

---

## 8. Extension points

| To add… | Extend | Do not |
|---|---|---|
| A new hazard input | implement `HazardSource.read()`; add via `HazardManager.add_source` | reach into the motors |
| A new motion capability | add a gated method on `RobotManager` | call `MotorDriver`/`ArduinoSerial` directly |
| A new stop condition | route through `SafetyManager`/`ModeController` → `SAFETY_STOP` | add an ad-hoc motor write |
| A new manipulator | implement `amr.warehouse.tasks.Manipulator` | modify the task manager |
| A new config knob | add to the relevant dataclass + YAML + `_validate_*` | hardcode it |

---

## 9. Web API surface

Stdlib-only (`ThreadingHTTPServer`), no build step, no external assets, and **no
authentication** (single-operator LAN tool — never expose the port).

`GET /` panel · `GET /status` · `GET /sensor` · `GET /camera` ·
`GET /image` · `GET /hazard` · `POST /command` (`estop`, `stop`, `mode`,
drive commands) · `POST /hazard/acknowledge` (step 1 of the two-step
emergency release — never resets the robot mode). `estop`/`stop` are never
gated. Details: `docs/web_control.md`.

