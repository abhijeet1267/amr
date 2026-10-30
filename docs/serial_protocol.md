# AMR Serial Protocol

**Version:** `1.1` — **Transport:** USB CDC serial (Arduino UNO ↔ Raspberry Pi 5)
**Baud rate:** `9600` — **Framing:** one command per line, `\r\n` (or `\n`) terminated
**Encoding:** ASCII/UTF-8, verbs are **case-insensitive** (LCD text keeps its case)

This is the single source of truth for the text protocol. Two implementations
must stay in sync:

- **Pi (Python):** `raspberry_pi/amr/communication/protocol.py` (unit-tested)
- **Arduino (C++):** `firmware/arduino/amr_controller/protocol.cpp`

> Migration note: this replaces the legacy single-character commands
> (`F` `B` `L` `R` `S`). The legacy commands **remain supported** for backward
> compatibility with the already-tested baseline, so the existing prototype
> keeps working while the new structured protocol is adopted.

> v1.1 adds the environmental/display commands (`ENV`, `GAS`, `LCD`, `BUZZ`).
> They are additive: a v1.0 controller answers them with `ERR UNKNOWN`, which
> the Pi tolerates as a failed read (values stay `UNAVAILABLE`, never invented).

---

## 1. Command set (Pi → Arduino)

| Command                     | Example             | Purpose                                   |
| --------------------------- | ------------------- | ----------------------------------------- |
| `PING`                      | `PING`              | Liveness check                            |
| `STATUS`                    | `STATUS`            | Query motor + drive state                 |
| `STOP`                      | `STOP`              | Immediately stop both motor sides         |
| `VERSION`                   | `VERSION`           | Report firmware protocol version          |
| `SENSOR`                    | `SENSOR`            | Request an immediate ultrasonic report    |
| `WDT <ms>`                  | `WDT 1000`          | Set the communication watchdog timeout    |
| `MOVE L=<int> R=<int>`      | `MOVE L=150 R=150`  | Set left/right wheel-group speed          |
| `ENV`                       | `ENV`               | DHT11 temperature + humidity reading      |
| `GAS`                       | `GAS`               | MQ gas sensor raw ADC reading             |
| `LCD <l0>\|<l1>`            | `LCD MODE RUNNING…` | Set the 16×2 I2C LCD (≤16 chars per line) |
| `BUZZ <hz> [<ms>]`          | `BUZZ 1200 150`     | Buzzer tone; `0` stops, `<ms>` auto-stops |
| `F` / `B` / `L` / `R` / `S` | `F`                 | **Legacy** baseline commands (still work) |

### Speed semantics (`MOVE`)

- Range: **`-255 .. +255`** per side. Positive = forward, negative = reverse,
  `0` = stop that side.
- `L` and `R` are the two _wheel groups_ (left side motors, right side motors),
  **not** individual wheels — differential drive is applied by the Pi.
- Presets:
  - Forward: `MOVE L=1 R=1`
  - Reverse: `MOVE L=-1 R=-1`
  - Turn left: `MOVE L=-1 R=1`
  - Turn right: `MOVE L=1 R=-1`
  - Stop: `MOVE L=0 R=0` (equivalent to `STOP`)

### Legacy commands (backward compatibility)

| Char | Behaviour  | Equivalent       |
| ---- | ---------- | ---------------- |
| `F`  | forward    | `MOVE L=1 R=1`   |
| `B`  | backward   | `MOVE L=-1 R=-1` |
| `L`  | turn left  | `MOVE L=-1 R=1`  |
| `R`  | turn right | `MOVE L=1 R=-1`  |
| `S`  | stop       | `MOVE L=0 R=0`   |

---

## 2. Response set (Arduino → Pi)

| Response                                 | Example                       | Meaning                                     |
| ---------------------------------------- | ----------------------------- | ------------------------------------------- |
| `PONG`                                   | `PONG`                        | Reply to `PING`                             |
| `ACK <verb> [args]`                      | `ACK MOVE L=1 R=1`            | Command accepted                            |
| `ERR <code> [msg]`                       | `ERR RANGE out of range`      | Command rejected                            |
| `STATUS L=<int> R=<int> MODE=<str>`      | `STATUS L=1 R=1 MODE=RUNNING` | Motor + drive state                         |
| `SENSOR F=<int> L=<int> R=<int> B=<int>` | `SENSOR F=82 L=45 R=91 B=120` | Ultrasonic distances (cm)                   |
| `ENV T=<int> H=<int>`                    | `ENV T=24 H=51`               | DHT11 degC / %RH; `-1` = invalid/unmeasured |
| `GAS RAW=<int>`                          | `GAS RAW=312`                 | MQ gas raw ADC; `-1` = no pin assigned      |
| `VERSION <semver>`                       | `VERSION 1.1`                 | Protocol version                            |
| `WATCHDOG TRIGGERED`                     | `WATCHDOG TRIGGERED`          | Unsolicited: Pi went silent, motors stopped |

### `STATUS MODE` values (firmware drive state)

`STOPPED`, `RUNNING`, `WATCHDOG`.

> This is the **firmware** drive state. It is distinct from the Pi's higher-level
> robot mode (`IDLE/MANUAL/AUTONOMOUS/SAFETY_STOP/ERROR`) tracked in
> `amr.robot.robot_state`.

### Error codes (`ERR <code>`)

| Code      | Cause                                                                 |
| --------- | --------------------------------------------------------------------- |
| `PARSE`   | Malformed / missing fields                                            |
| `RANGE`   | A value is outside its allowed range (speed ±255, buzzer 20–20000 Hz) |
| `UNKNOWN` | Unrecognised command                                                  |

---

## 3. Sensor report (`SENSOR`)

- Units: **centimetres (cm)**.
- A value of **`-1`** means _no usable echo_ (timeout / clear — no obstacle in
  range). It is **not** an obstacle.
- Valid readings are within the sensor's physical range (see `safety.yaml`
  `sensor_min_valid_cm` / `sensor_max_valid_cm`).
- The Pi polls `SENSOR` on demand; the firmware can also emit unsolicited
  `SENSOR` lines when telemetry is enabled (`ULTRASONIC_TELEMETRY`), and the
  Pi buffers those into `ArduinoSerial.last_sensor`.

---

## 4. Environmental sensors (`ENV`, `GAS`)

| Read       | Values                        | Notes                                                     |
| ---------- | ----------------------------- | --------------------------------------------------------- |
| **DHT11**  | `T` degC (int), `H` %RH (int) | `-1` = invalid/unmeasured. Sampling one-shot, on request. |
| **MQ gas** | `RAW` ADC count (0..1023)     | `-1` = _no pin assigned_, the shipped default.            |

**Honesty contract:** `-1` means "not measured". The Pi parser maps `-1` to
`None` and telemetry surfaces `UNAVAILABLE` — it never invents `0 ppm`.

**Safety contract:** neither value reaches `SafetyManager`, `HazardManager`, or
`RobotManager._gate()`. There is no path from a gas reading to the motors. The
buzzer/LCD are similarly actuation-free of _motion_: `LCD`/`BUZZ` are accepted
in any mode and never reach `dispatch()`.

### Buzzer (`BUZZ`)

- `BUZZ <hz>` — tone frequency, 20–20000 Hz (0 = stop).
- `BUZZ <hz> <ms>` — stops automatically after `<ms>` (prevents a stuck buzzer).
- Frequency outside range → `ERR RANGE`; a non-numeric argument → `ERR PARSE`.
- **The firmware does not use `tone()`.** `tone()` occupies Timer2, which also
  drives D11 — the right motor's PWM pin (ENB). It would corrupt speed
  control, so the buzzer is toggled with plain `digitalWrite()`.

---

## 5. Watchdog (`WATCHDOG TRIGGERED`)

If no **valid** command is received for `watchdog_timeout_ms` (default **1000 ms**),
the firmware stops all motors and emits `WATCHDOG TRIGGERED` once. See
[`safety.md`](safety.md).

---

## 6. Worked session

```
Pi                          Arduino
--                          -------
PING                        ->  PONG
VERSION                     ->  VERSION 1.1
MOVE L=1 R=1                ->  ACK MOVE L=1 R=1
STATUS                      ->  STATUS L=1 R=1 MODE=RUNNING
SENSOR                      ->  SENSOR F=82 L=45 R=91 B=120
ENV                         ->  ENV T=24 H=51
GAS                         ->  GAS RAW=312
LCD MODE RUNNING|T24 H51     ->  ACK LCD
BUZZ 1200 150               ->  ACK BUZZ 1200
STOP                        ->  ACK STOP
MOVE L=300 R=0              ->  ERR RANGE out of range
BUZZ 99                    ->  ERR RANGE out of range  (min 20 Hz)
XYZ                         ->  ERR UNKNOWN XYZ
        (Pi goes silent > 1000 ms)
                            ->  WATCHDOG TRIGGERED   (motors stopped)
```

---

## 7. Robustness rules (both sides)

- The Pi reads until it sees the expected response, an `ERR`, or a timeout.
- Unsolicited `SENSOR`/`WATCHDOG` lines are tolerated and buffered, never fatal.
- Unrecognised lines become `UNKNOWN` (safe failure) — parsing never throws.
- A serial timeout raises a typed error on the Pi; the robot manager decides the
  safe action (typically treat as disconnected and stop).

## 8. Extensibility

New verbs should be **additive** (new command/response pairs) and must be added
to **both** implementations plus this document and `PROTOCOL_VERSION` bumped on
any breaking change.
