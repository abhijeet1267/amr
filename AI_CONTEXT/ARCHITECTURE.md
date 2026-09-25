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

Layer 3 gained an optional **obstacle-avoidance** extension (C6) in
`amr/safety/avoidance.py`, consumed by an avoidance gate at the top of
`LocalNavigator.step()`. It emits `TURN`/`REPLAN` for **non-blocking**
obstacles only, and returns a Layer-3 `STOP`/`WAIT` **unchanged** — so
emergency stop keeps absolute priority. The gate runs before the control law
and can only reduce motion; commands still leave through the one existing
`command()` → `RobotManager` gate. All hooks default to `None` and
`safety.avoidance.enabled` is `false`, so the default stack is unchanged.
See `docs/safety.md` §C6. **Simulation only; thresholds NOT_VERIFIED.**

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
| A new dashboard/monitoring view | read the C7 `TelemetrySnapshot` | add a second copy of robot state, or give the view a write path |

---

## 9. Web API surface

Stdlib-only (`ThreadingHTTPServer`), no build step, no external assets, and **no
authentication** (single-operator LAN tool — never expose the port).

`GET /` panel · `GET /status` · `GET /sensor` · `GET /camera` ·
`GET /camera/status` · `GET /camera/frame` · `GET /image` · `GET /hazard` ·
`GET /telemetry` · `GET /health` · `GET /map` · `GET /map.svg` ·
`GET /dashboard` · `POST /command` (`estop`, `stop`, `mode`,
drive commands) · `POST /hazard/acknowledge` (step 1 of the two-step
emergency release — never resets the robot mode). `estop`/`stop` are never
gated. Details: `docs/web_control.md`.

---

## 10. Telemetry / digital-twin layer (C7)

`amr/telemetry/` sits **beside** the runtime, not inside it:

```
existing runtime (RobotManager, SafetyManager, HazardManager,
                   Navigator, WarehouseTaskManager, CameraManager)
        ↓  read-only — no tick(), no writes, no command path
TelemetryCollector  →  TelemetrySnapshot (frozen, schema-versioned)
        ↓
GET /telemetry · GET /health · GET /dashboard
```

It is an **observation** layer. The collector holds no Arduino/GPIO/PWM handle
and imports no hardware driver; `POST /command` remains the only path to the
actuators, and a test asserts the collector writes nothing to the serial
transport. Each section carries a `source` tag (`LIVE` / `SIMULATION` /
`UNAVAILABLE`) and missing measurements are `null`, never invented — so the UI
can honestly show `NOT AVAILABLE` instead of a plausible-looking number.

Later milestones (camera monitor, 2D map, 3D twin, mission/hazard panels,
replay) all read this one snapshot rather than each holding their own copy of
robot state. See `docs/telemetry.md`.

---

## 11. Map layer (C9)

`amr/map/` is also an **observation** layer, and splits map *state* from map
*drawing* so C10 can reuse the state:

```
WarehouseMap · HazardZone · Navigator · HazardManager · TelemetryCollector
        ↓  read-only adapters (world metres, y-up, radians — unchanged)
MapSnapshot  →  GET /map          (JSON, presentation-independent)
            →  GET /map.svg      (server-rendered SVG)
            →  dashboard panel   (interactive SVG, same data)
            →  C10 3D twin       (GET /digital-twin, same snapshot)
```

* **One** coordinate conversion lives in `amr/map/transform.py`
  (uniform scale, y flipped for SVG). The browser repeats the same formula for
  zoom/pan only; it never decides map semantics.
* `PathHistory` bounds the travelled trail (600 pts, de-duplicated) so a
  1 Hz dashboard poll cannot grow memory without limit.
* The C5 rule is enforced at this boundary: a hazard is placed **only** with a
  real world `location`; image-space evidence is listed under `unlocated` with
  no coordinates.
* The project models **no** shelf/rack/obstacle/boundary geometry, so those
  report `UNAVAILABLE` with a visible note instead of an invented floor plan.
* Read-only: `amr/map/` imports no motor/PWM/serial/GPIO code, never steps the
  navigator, and a test proves map reads write nothing to the serial transport.

See `docs/map.md`.

## 12. Digital twin layer (C10)

The 3D twin is **another view of the C9 `MapSnapshot`**, not a new state model
and not a second robot. It adds exactly two things the 2D view does not need: the
world→3D conversion (centralised in Python, `amr/map/twin.py`, unit tested) and
scene assembly for a procedural AMR.

```
MapSnapshot  →  build_twin_state()  →  GET /digital-twin  →  WebGL card
```

* **Coordinate system:** the repository frame is unchanged — metres, y-up, yaw in
  radians. A z-up renderer needs `three.x = world.x`, `three.y = -world.y`,
  `rotation_z_deg = -degrees(yaw)`. One conversion, one place, tested at 0,
  ±π/2 and π. The browser never re-derives it.
* **Renderer:** raw **WebGL, no Three.js** — the project keeps zero frontend
  dependencies, so it stays one self-contained Python process with no npm, CDN
  or build step. `renderer.library` is `null` in the payload.
* **No command path:** GET only, no actuation controls, and the twin module
  references no `RobotManager`/`Navigator`/`SafetyManager`/serial/GPIO/PWM.
  Safety state is read and displayed, never acted on.
* **Honesty:** `source` is inherited from the map; the scene is labelled
  schematic because the project has no surveyed geometry; a missing camera or
  pose degrades to `UNAVAILABLE` rather than being faked.
* Uses the dashboard's existing 1 Hz poll — no second timer.

See `docs/digital_twin.md`.

## 13. Operations console layer (C11)

The dashboard console is **another read-only projection**, not a new state
model. `amr/telemetry/console.py` is a pure function that assembles the
existing projections into one response:

```text
TelemetrySnapshot (C7) ─┐
MapSnapshot (C9)       ─┼─→ build_console_state() ─→ GET /dashboard/state
DigitalTwinState (C10) ─┤                                  ↓
health (C7)            ─┘                              Dashboard
```

* **No new schema.** Every field is copied or derived arithmetically; the
  `map` and `twin` keys are the untouched C9/C10 payloads, asserted equal to
  their standalone endpoints so the console cannot become a second state.
* **One request per tick.** The page fetches `/dashboard/state` instead of
  telemetry + map + twin + health, still on the existing 1 Hz poll — no second
  timer, no WebSocket.
* **Absence stays absence.** `UNAVAILABLE` is never coerced to `0` or "healthy";
  an unwired mission runtime reports "Mission data unavailable". Route progress
  is reported with its basis, never recomputed or faked.
* **Read-only.** GET only, no actuation controls; `POST /command` remains the
  sole actuator path.
* **JavaScript is syntax-checked in CI** (`node --check` on the served
  scripts), permanently closing the C10 gap where a broken dashboard script
  passed every test. Node is a validation tool only, never a runtime dep.

See `docs/dashboard_console.md`.

## 14. Mission monitoring layer (C12)

C12 adds **no new state engine**. It makes the existing `WarehouseTaskManager`
observable through the same read-only chain the console already uses:

```
WarehouseTaskManager.status()   ManagerStatus
        │  mission_id · destination · total_tasks · counters
        ▼
TelemetryCollector._mission()  adapters + progress (one _goal_progress helper)
        ▼
MissionTelemetry                the C7 mission section, extended additively
        ▼
mission_phase()                 derived display phase, overridden by safety
        ▼
GET /dashboard/state  →  Mission panel
```

Three properties matter for anyone extending this:

* **One mission truth.** The collector adapts `ManagerStatus`; it never
  re-decides what the robot is doing. The reader accepts the object *or* a plain
  dict so third-party warehouse implementations still work.
* **Derived, never invented.** `mission_progress` is `completed / total` over
  real submitted work; `task_progress` is real straight-line distance to the
  navigator's own goal. Unknown stays `None` — and unknown is never read as
  arrival or as 0%.
* **Safety outranks the narrative.** The phase is presentation only; a
  `TURN`/`REPLAN` shows `AVOID`, `STOP`/`WAIT` show `HELD`, and an E-stop shows
  `EMERGENCY`. Nothing here feeds back into navigation.

The optional `--mission-demo` flag drives the standard warehouse scenario so the
panel has something to show. It is **mock-only by construction** — it is
refused without `--mock` — and it is a runtime loop, not a dashboard control.
The dashboard remains read-only throughout; `POST /command` is still the only
actuator path.

See `docs/mission_monitoring.md`.

