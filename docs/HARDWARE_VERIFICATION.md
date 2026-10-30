# Hardware Verification Matrix

Inventory of every hardware component in the AMR project, with its real
configuration, software status, and what still needs physical verification.

> **Honesty rule.** This project drives a robot. A passing mock test or a
> successful import does **not** prove a physical device works. Nothing here is
> marked `HARDWARE_VERIFIED` without actual hardware evidence. Where the wiring
> cannot be established from the repository, the component is marked
> `UNKNOWN` / `CONFIGURED_NOT_CONNECTED`, never guessed.

---

## Verification states

| State                      | Meaning                                                                                                                              |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `SOFTWARE_VERIFIED`        | Driver + tests + a live value through the full stack are all correct, but on mock/simulated data only. No physical device exercised. |
| `HARDWARE_VERIFIED`        | A real powered device produced the value, traced from driver to dashboard. **Requires physical evidence.**                           |
| `CONFIGURED_NOT_CONNECTED` | In the config/driver, but nothing physically answering.                                                                              |
| `SIMULATION_ONLY`          | Only meaningful in mock mode; there is no physical counterpart.                                                                      |
| `FAILED`                   | Software-verified path, but the physical device does not produce a value (e.g. DHT11 not reading).                                   |
| `UNKNOWN`                  | No wiring/configuration evidence to determine the state.                                                                             |
| `NOT_IMPLEMENTED`          | No driver or wiring at all.                                                                                                          |

---

## Component inventory

All pins/addresses are from the applied pin chart (verified against the firmware
headers and `config/robot.yaml` in the sensors phase). The **software** column
states what was verified during this phase; the **physical** column states what
remains to be tested against powered hardware.

| ID         | Type             | Purpose                               | Interface             | Pin / address                                   | Driver                                | Backend source                           | API source                                   | Dashboard location                | Value (units)               | Physical                                                          |
| ---------- | ---------------- | ------------------------------------- | --------------------- | ----------------------------------------------- | ------------------------------------- | ---------------------------------------- | -------------------------------------------- | --------------------------------- | --------------------------- | ----------------------------------------------------------------- |
| `pi`       | Raspberry Pi 5   | Main controller                       | —                     | —                                               | —                                     | process                                  | `GET /health`                                | Header (backend online)           | —                           | `HARDWARE_VERIFIED` (serving)                                     |
| `arduino`  | Arduino UNO      | Reflexes (motor, watchdog, proximity) | USB CDC serial 9600   | `/dev/ttyACM0`                                  | `amr/communication/arduino_serial.py` | `RobotState.connected`                   | `GET /dashboard/state` → `hardware`          | Hardware grid, conn chip          | —                           | `HARDWARE_VERIFIED` (PING/VERSION/STATUS)                         |
| `motors`   | 2× DC gear motor | Robot movement                        | via L298N             | `IN1=D12 IN2=D13 ENA=D10 IN3=A3 IN4=A2 ENB=D11` | `firmware/.../motor_control.cpp`      | `is_moving`, `left/right_speed`          | `/dashboard/state` → `io.motors`, `hardware` | I/O panel, Hardware grid          | requested speed (PWM 0–255) | `CONFIGURED_NOT_CONNECTED` — **never commanded**                  |
| `us_front` | HC-SR04          | Front range                           | GPIO                  | `D2` trig / `D3` echo                           | `firmware/.../ultrasonic.cpp`         | `sensors.front_cm`                       | `/dashboard/state` → `sensors`               | Ultrasonic monitor, Hardware grid | cm                          | `HARDWARE_VERIFIED` (live 195 cm)                                 |
| `us_left`  | HC-SR04          | Left range                            | GPIO                  | `D4` / `D5`                                     | `firmware/.../ultrasonic.cpp`         | `sensors.left_cm`                        | same                                         | same                              | cm                          | `HARDWARE_VERIFIED` (live 155 cm)                                 |
| `us_right` | HC-SR04          | Right range                           | GPIO                  | `D6` / `D7`                                     | `firmware/.../ultrasonic.cpp`         | `sensors.right_cm`                       | same                                         | same                              | cm                          | `HARDWARE_VERIFIED` (live 52 cm)                                  |
| `us_rear`  | HC-SR04          | Rear range                            | GPIO                  | `D8` / `D9`                                     | `firmware/.../ultrasonic.cpp`         | `sensors.rear_cm`                        | same                                         | same                              | cm                          | `HARDWARE_VERIFIED` (live 57 cm)                                  |
| `dht11`    | DHT11            | Temp + humidity                       | GPIO (bit-banged)     | `A1`                                            | `firmware/.../dht11.cpp`              | `sensors.temperature_c` / `humidity_pct` | `/dashboard/state` → `sensors`               | Hardware grid, I/O panel          | °C / %RH                    | `FAILED` — not reading (likely missing 10 kΩ pull-up)             |
| `gas`      | MQ-series        | Gas level                             | analog (not assigned) | **none**                                        | `firmware/.../gas_sensor.cpp`         | `sensors.gas_raw`                        | `/dashboard/state` → `sensors`               | Hardware grid, I/O panel          | raw 0–1023                  | `CONFIGURED_NOT_CONNECTED` — no pin, reports unmeasured (never 0) |
| `lcd`      | 16×2 I2C LCD     | Status display                        | I2C (PCF8574)         | `A4` SDA / `A5` SCL, `0x27`                     | `firmware/.../lcd_i2c.cpp`            | intended state (`build_lcd_state`)       | `/dashboard/state` → `lcd`                   | LCD panel                         | 2×16 chars                  | `CONFIGURED_NOT_CONNECTED` — write-only, no read-back             |
| `buzzer`   | 2-wire buzzer    | Audible alert                         | GPIO (digital toggle) | `A0`                                            | `firmware/.../buzzer.cpp`             | command-driven                           | `BUZZ` command                               | (no dashboard state)              | on/off                      | `CONFIGURED_NOT_CONNECTED` — command-driven, no continuous state  |
| `camera`   | imx219 Camera v2 | Vision input                          | CSI ribbon            | Pi CSI port                                     | `amr/camera/frame.py` (picamera2)     | `telemetry.camera`                       | `GET /camera/status`, `/camera/frame`        | Camera panel, Hardware grid       | 1280×720 PNG                | `HARDWARE_VERIFIED` (live frame)                                  |
| `battery`  | (none)           | Power monitoring                      | —                     | —                                               | —                                     | `telemetry.battery`                      | `/dashboard/state` → `sensors`               | Hardware grid                     | % (absent)                  | `NOT_IMPLEMENTED` — no voltage sensor; `UNAVAILABLE`, never 0     |

---

## Value-flow verification (this phase)

A known value was pushed through the real stack at each stage to confirm the
units, identifiers, and validity propagate without corruption or a fabricated
zero.

### Ultrasonic (per-face)

| Stage              | File / function                                          | Verified value                             |
| ------------------ | -------------------------------------------------------- | ------------------------------------------ |
| Driver (Arduino)   | `firmware/.../ultrasonic.cpp` → `SENSOR F= L= R= B=`     | 195 / 155 / 52 / 57 cm                     |
| Serial parse       | `amr/communication/protocol.py` `parse_response`         | `front=195 …`                              |
| Manager (validate) | `amr/sensors/ultrasonic.py` `UltrasonicManager.latest()` | `{front:195, left:155, right:52, rear:57}` |
| State              | `amr/robot/robot_manager.py` → `RobotState.to_dict()`    | `front_cm=195 …`                           |
| Telemetry          | `amr/telemetry/collector.py` `snapshot()["sensors"]`     | `front_cm:195 … source:LIVE`               |
| Hardware grid      | `amr/telemetry/hardware.py` `build_hardware_inventory`   | `us_front: 195cm → CLEAR`                  |
| Dashboard          | `command_center.js` `renderHardware` / `renderUsMonitor` | `195 cm`, `CLEAR`                          |

- Units consistent (cm) at every stage. ✓
- `None` (no echo) → `n/a`, never `0`. ✓
- **Per-face classification now matches the `SafetyManager`** — see the fix
  below. Previously a single global threshold was applied to all four faces and
  the server fed it the _left_ stop distance as a global "caution" value, so the
  dashboard could classify a face differently from the robot. Fixed to use each
  face's own `*_stop_distance_cm` with the `CAUTION_FACTOR × stop` band,
  imported from `safety/safety_manager.py` (single source of truth).

### Environment (DHT11 / gas)

| Stage            | Verified value                                                                   |
| ---------------- | -------------------------------------------------------------------------------- |
| Driver (Arduino) | `ENV T=24 H=51`, `GAS RAW=312`                                                   |
| Manager          | `EnvironmentManager.poll()` → `{temperature_c:24, humidity_pct:51, gas_raw:312}` |
| State            | `RobotState.temperature_c/humidity_pct/gas_raw`                                  |
| Telemetry / grid | `sensors.temperature_c:24 …`, gas `CONFIGURED` when `None`                       |

- DHT11/gas flow is correct when the hardware reads. ✓
- When the hardware does not read (the current DHT11), the value is `None` →
  `CONFIGURED`/`n/a`, never a fabricated number. ✓

### Command execution

- `forward` in `MANUAL` → recorded `SUCCEEDED`, `executed: True` (robot state
  confirms motion). ✓
- `forward` in `IDLE` → recorded `REJECTED` with the gate's reason — **not**
  marked successful just because it was dispatched. ✓
- `stop` → `SUCCEEDED`, `executed: None` (not a motion command; N/A, not a false
  True). ✓
- Every command carries a `command_id` and an `environment` (SIMULATION/HARDWARE). ✓

### I/O and motors

- Motor values are labelled **requested**, not measured — the I/O note reads
  "Requested PWM; no tachometer, so not a measured speed." ✓
- I/O panel reports configuration + logical state only; it does not probe or
  toggle any pin. ✓
- `is_moving` reflects the robot state, not an assumption. ✓

### LCD

- The panel shows **intended** content (2×16, row-fitted) and `content_confirmed
: false`, labelled "intended, not read back". ✓
- A physical E-STOP/safety condition takes row 1 over a stale command label. ✓

---

## Genuine problems found and fixed this phase

| #   | Problem                                                                                                                                                                      | Fix                                                                                                                                                                                                                                                                                                                |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Ultrasonic classification used a single global threshold (and the server fed the _left_ stop distance as a global "caution"), so it could disagree with the `SafetyManager`. | `hardware.py` now classifies **per face** using each face's own stop distance and the `CAUTION_FACTOR × stop` band imported from `safety/safety_manager.py`. `server.py` now passes all four `*_stop_cm`. Added a test that asserts the dashboard classification matches the `SafetyManager` for the same reading. |

No other value-flow, unit, stale-data, or contract problems were found. The
value paths (ultrasonic, environment, command, I/O, LCD) were each traced and
match end to end.

---

## Simulation vs physical separation

- Mock mode runs the whole robot in-process; the dashboard shows `SIMULATION`
  with a banner, per-value `SIM` tags, and `environment: SIMULATION` on every
  command. ✓
- A mock command can never reach a physical actuator (the mock transport has no
  real device, and the console submits nothing). ✓
- The hardware grid distinguishes `SIMULATED` from `CONNECTED`/`LIVE` per value. ✓
- A `HARDWARE_VERIFIED` value (e.g. a live ultrasonic reading) and a `SIMULATION`
  value are reported differently — the same UI element is never used to claim a
  mock reading is physical.

---

## Physical verification still required

These are honest gaps — the software is complete and tested, but the following
have **not** been exercised against powered hardware:

1. **Motors have never been commanded.** Direction, polarity, PWM speed
   control, and real stop distances are untested. _Test first, wheels off the
   ground._
2. **DHT11** — currently not reading; confirm it reads after adding the 10 kΩ
   VCC–DATA pull-up (or check the module type).
3. **MQ gas** — requires freeing an analog pin (all 20 UNO pins are currently
   assigned) before it can report.
4. **LCD** — confirm the physical display shows what the panel shows (there is
   no read-back, so the dashboard can only show intended content).
5. **Buzzer** — confirm it tones on `BUZZ` and stops on `BUZZ 0`.
6. **Safety thresholds** — still `NOT_VERIFIED`; measure stop distances on the
   robot before trusting it at speed.
7. **Robot geometry** — `wheel_track_m` / `wheel_diameter_m` still `null`;
   odometry/navigation math is unvalidated until measured.

The step-by-step physical checklist is in `docs/DEPLOY.md` and the physical
verification section of the final report.
