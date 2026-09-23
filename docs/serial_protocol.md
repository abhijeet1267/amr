# AMR Serial Protocol

**Version:** `1.0` — **Transport:** USB CDC serial (Arduino UNO ↔ Raspberry Pi 5)
**Baud rate:** `9600` — **Framing:** one command per line, `\r\n` (or `\n`) terminated
**Encoding:** ASCII/UTF-8, verbs are **case-insensitive**

This is the single source of truth for the text protocol. Two implementations
must stay in sync:

* **Pi (Python):** `raspberry_pi/amr/communication/protocol.py` (unit-tested)
* **Arduino (C++):** `firmware/arduino/amr_controller/protocol.cpp`

> Migration note: this replaces the legacy single-character commands
> (`F` `B` `L` `R` `S`). The legacy commands **remain supported** for backward
> compatibility with the already-tested baseline, so the existing prototype
> keeps working while the new structured protocol is adopted.

---

## 1. Command set (Pi → Arduino)

| Command | Example | Purpose |
|---|---|---|
| `PING` | `PING` | Liveness check |
| `STATUS` | `STATUS` | Query motor + drive state |
| `STOP` | `STOP` | Immediately stop both motor sides |
| `VERSION` | `VERSION` | Report firmware protocol version |
| `SENSOR` | `SENSOR` | Request an immediate ultrasonic report |
| `WDT <ms>` | `WDT 1000` | Set the communication watchdog timeout |
| `MOVE L=<int> R=<int>` | `MOVE L=150 R=150` | Set left/right wheel-group speed |
| `F` / `B` / `L` / `R` / `S` | `F` | **Legacy** baseline commands (still work) |

### Speed semantics (`MOVE`)
* Range: **`-255 .. +255`** per side. Positive = forward, negative = reverse,
  `0` = stop that side.
* `L` and `R` are the two *wheel groups* (left side motors, right side motors),
  **not** individual wheels — differential drive is applied by the Pi.
* Presets:
  * Forward: `MOVE L=1 R=1`
  * Reverse: `MOVE L=-1 R=-1`
  * Turn left: `MOVE L=-1 R=1`
  * Turn right: `MOVE L=1 R=-1`
  * Stop: `MOVE L=0 R=0` (equivalent to `STOP`)

### Legacy commands (backward compatibility)
| Char | Behaviour | Equivalent |
|---|---|---|
| `F` | forward | `MOVE L=1 R=1` |
| `B` | backward | `MOVE L=-1 R=-1` |
| `L` | turn left | `MOVE L=-1 R=1` |
| `R` | turn right | `MOVE L=1 R=-1` |
| `S` | stop | `MOVE L=0 R=0` |

---

## 2. Response set (Arduino → Pi)

| Response | Example | Meaning |
|---|---|---|
| `PONG` | `PONG` | Reply to `PING` |
| `ACK <verb> [args]` | `ACK MOVE L=1 R=1` | Command accepted |
| `ERR <code> [msg]` | `ERR RANGE out of range` | Command rejected |
| `STATUS L=<int> R=<int> MODE=<str>` | `STATUS L=1 R=1 MODE=RUNNING` | Motor + drive state |
| `SENSOR F=<int> L=<int> R=<int> B=<int>` | `SENSOR F=82 L=45 R=91 B=120` | Ultrasonic distances (cm) |
| `VERSION <semver>` | `VERSION 1.0` | Protocol version |
| `WATCHDOG TRIGGERED` | `WATCHDOG TRIGGERED` | Unsolicited: Pi went silent, motors stopped |

### `STATUS MODE` values (firmware drive state)
`STOPPED`, `RUNNING`, `WATCHDOG`.

> This is the **firmware** drive state. It is distinct from the Pi's higher-level
> robot mode (`IDLE/MANUAL/AUTONOMOUS/SAFETY_STOP/ERROR`) tracked in
> `amr.robot.robot_state`.

### Error codes (`ERR <code>`)
| Code | Cause |
|---|---|
| `PARSE` | Malformed / missing fields |
| `RANGE` | A speed value is outside `-255 .. +255` |
| `UNKNOWN` | Unrecognised command |

---

## 3. Sensor report (`SENSOR`)
* Units: **centimetres (cm)**.
* A value of **`-1`** means *no usable echo* (timeout / clear — no obstacle in
  range). It is **not** an obstacle.
* Valid readings are within the sensor's physical range (see `safety.yaml`
  `sensor_min_valid_cm` / `sensor_max_valid_cm`).
* The Pi polls `SENSOR` on demand; the firmware can also emit unsolicited
  `SENSOR` lines when telemetry is enabled (`ULTRASONIC_TELEMETRY`), and the
  Pi buffers those into `ArduinoSerial.last_sensor`.

---

## 4. Watchdog (`WATCHDOG TRIGGERED`)
If no **valid** command is received for `watchdog_timeout_ms` (default **1000 ms**),
the firmware stops all motors and emits `WATCHDOG TRIGGERED` once. See
[`safety.md`](safety.md).

---

## 5. Worked session

```
Pi                          Arduino
--                          -------
PING                        ->  PONG
VERSION                     ->  VERSION 1.0
MOVE L=1 R=1                ->  ACK MOVE L=1 R=1
STATUS                      ->  STATUS L=1 R=1 MODE=RUNNING
SENSOR                      ->  SENSOR F=82 L=45 R=91 B=120
STOP                        ->  ACK STOP
MOVE L=300 R=0              ->  ERR RANGE out of range
XYZ                         ->  ERR UNKNOWN XYZ
        (Pi goes silent > 1000 ms)
                            ->  WATCHDOG TRIGGERED   (motors stopped)
```

---

## 6. Robustness rules (both sides)
* The Pi reads until it sees the expected response, an `ERR`, or a timeout.
* Unsolicited `SENSOR`/`WATCHDOG` lines are tolerated and buffered, never fatal.
* Unrecognised lines become `UNKNOWN` (safe failure) — parsing never throws.
* A serial timeout raises a typed error on the Pi; the robot manager decides the
  safe action (typically treat as disconnected and stop).

## 7. Extensibility
New verbs should be **additive** (new command/response pairs) and must be added
to **both** implementations plus this document and `PROTOCOL_VERSION` bumped on
any breaking change.
