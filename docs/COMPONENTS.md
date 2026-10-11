# Component & connection analysis

Every part in the build, how they connect, and every finding that falls out of
reading the firmware and config side by side. Derived from the **actual source**
— `firmware/arduino/amr_controller/*.h`, `config/*.yaml` — not from assumptions.

> Nothing here has been run on real hardware. Where a value is a placeholder it
> says so.

---

## 1. Component inventory

| # | Component | Role | Power source | Interface | Where it's configured |
| --- | --- | --- | --- | --- | --- |
| 1 | **Raspberry Pi 5** | brain: web server, safety policy, navigation, tasks | its own official PSU | — | `config/serial.yaml` |
| 2 | **Arduino UNO** | reflexes: motor drive, watchdog, hardware stop | 5 V via USB from the Pi | USB CDC serial | `firmware/.../*.h` |
| 3 | **L298N H-bridge** | drives the two motors (direction + PWM) | **external battery pack** | 6 GPIO from the UNO | `firmware/.../motor_control.h` |
| 4 | **2× DC gear motor** | differential drive, one per side | via the L298N | 2 wires each | `config/robot.yaml` |
| 5 | **4× HC-SR04 ultrasonic** | front / left / right / rear ranging | 5 V from the UNO | 8 GPIO (4 trig + 4 echo) | `firmware/.../ultrasonic.h` |
| 6 | **Raspberry Pi Camera** | vision (optional) | from the Pi | CSI ribbon | `config/robot.yaml` → `camera` |
| 7 | **Motor battery pack** | motor power | — | 2 wires to the L298N | — |
| 8 | **Chassis + caster** | mechanical | — | — | `robot.wheel_track_m` (unmeasured) |

**Not present** (no hardware exists in this repo, despite code paths): gripper,
RFID reader, gas/fire sensors. Those subsystems are simulated only.

---

## 2. Connection map

```
        ┌───────────────────────────────┐
        │  Raspberry Pi 5   (brain)     │
        │  python -m amr.main --web     │
        └───┬───────────────────────┬───┘
            │ USB (CDC serial)      │ CSI ribbon
            │ 9600 8N1              │
    ┌───────▼────────┐      ┌───────▼────────┐
    │ Arduino UNO    │      │ Camera module  │
    │ (reflexes)     │      └────────────────┘
    └──┬──────────┬──┘
       │ 6 GPIO   │ 8 GPIO
   ┌───▼───────┐ ┌▼──────────────┐
   │  L298N    │ │ 4× HC-SR04    │
   │ H-bridge  │ │ F / L / R / B │
   └───┬───────┘ └───────────────┘
       │ OUT1/2, OUT3/4
   ┌───▼──────────────┐
   │ 2× DC gear motor │
   └──────────────────┘

   MOTOR BATTERY PACK ──► L298N 12V/GND  (never the Pi's or Arduino's 5 V)
   Common ground: battery − ─ L298N GND ─ Arduino GND ─ (Pi via USB)
```

### Wire-by-wire

| From | To | Signal | Notes |
| --- | --- | --- | --- |
| Pi USB-A | Arduino USB-B | serial, 9600 8N1 | data cable required; also powers the UNO |
| Arduino `D5` | L298N `IN1` | left forward | |
| Arduino `D4` | L298N `IN2` | left reverse | **also rear ultrasonic trig — see §5** |
| Arduino `D6` | L298N `ENA` | left enable (PWM) | PWM-capable ✅ |
| Arduino `D10` | L298N `IN3` | right forward | |
| Arduino `D9` | L298N `IN4` | right reverse | |
| Arduino `D8` | L298N `ENB` | right enable | **not PWM-capable — see §5** |
| L298N `OUT1`/`OUT2` | left motor | motor drive | swap the 2 leads to reverse that wheel |
| L298N `OUT3`/`OUT4` | right motor | motor drive | |
| Battery `+` | L298N `12V` (VS) | motor power | |
| Battery `−` | L298N `GND` | motor return | **must be common with Arduino GND** |
| Arduino `5V`/`GND` | each HC-SR04 `VCC`/`GND` | sensor power | 5 V, not 3.3 V |
| Arduino trig/echo pins | each HC-SR04 `Trig`/`Echo` | ranging | see §3 |
| Pi CSI | camera ribbon | camera | latch closed, contacts correct way |

---

## 3. Arduino pin allocation — every pin, and what's on it

| Pin | Assigned to | Kind | Source |
| --- | --- | --- | --- |
| `D0` | USB RX | serial | reserved |
| `D1` | USB TX | serial | reserved |
| `D2` | RIGHT ultrasonic `TRIG` | output | `ultrasonic.h` |
| `D3` | RIGHT ultrasonic `ECHO` | input | `ultrasonic.h` |
| **`D4`** | **`IN2` (left reverse) + REAR ultrasonic `TRIG`** | **conflict** | both headers |
| **`D5`** | **`IN1` (left forward) + REAR ultrasonic `ECHO`** | **conflict** | both headers |
| `D6` | `ENA` (left PWM) | PWM output ✅ | `motor_control.h` |
| `D7` | LEFT ultrasonic `TRIG` | output | `ultrasonic.h` |
| `D8` | `ENB` (right enable) | digital only ❌ | `motor_control.h` |
| `D9` | `IN4` (right reverse) | output | `motor_control.h` |
| `D10` | `IN3` (right forward) | output | `motor_control.h` |
| `D11` | LEFT ultrasonic `ECHO` | input | `ultrasonic.h` |
| `D12` | FRONT ultrasonic `TRIG` | output | `ultrasonic.h` |
| `D13` | FRONT ultrasonic `ECHO` | input | `ultrasonic.h` |
| `A0`–`A5` | **free** | analog / digital I/O | — |

So the firmware allocates **14 of 20** usable pins; `A0`–`A5` are spare.

---

## 4. Interfaces

| Link | Physical | Protocol | Configured in |
| --- | --- | --- | --- |
| Pi ↔ Arduino | USB (CDC serial) — **not** GPIO UART | 9600 8N1, newline ASCII, protocol `1.0` | `config/serial.yaml` |
| Pi ↔ camera | CSI ribbon — **not** USB | libcamera / picamera2 / V4L2 | `config/robot.yaml` |
| Arduino ↔ L298N | 6 GPIO | direction + enable | `motor_control.h` |
| Arduino ↔ HC-SR04 | 8 GPIO | 40 kHz pulses, `pulseIn` | `ultrasonic.h` |
| App ↔ Pi | Wi-Fi / LAN | HTTP JSON on port 8080 | `config/applications.yaml` |

**The Pi never touches a motor or sensor pin.** It sends `MOVE`/`STOP` over
serial; the firmware is the only code that knows about pins.

---

## 5. Findings — the things that will bite

### 🔴 F1. `D4`/`D5` are double-booked (motor **and** rear sensor)

```
PIN_IN2 = 4   ==   PIN_REAR_TRIG = 4
PIN_IN1 = 5   ==   PIN_REAR_ECHO = 5
```

Wire the rear sensor to `D4`/`D5` and the left motor drives the sensor's trig
line and reads the echo line — the wheel and the reading corrupt each other.
**Move the rear sensor** (e.g. `A1`/`A2`) in `ultrasonic.h` **and**
`config/robot.yaml`.

### 🔴 F2. `ENB = D8` cannot do PWM

On the UNO the PWM pins are **`3, 5, 6, 9, 10, 11`**. `D8` is not one, so
`analogWrite(PIN_ENB, …)` degrades to on/off — the right motor can never be
speed-controlled. Harmless **today** (`MOTOR_PWM_ENABLED 0`), a wall the moment
you enable PWM.

**And there is no free PWM pin to move it to:**

| PWM pin | Currently used by |
| --- | --- |
| `D3` | RIGHT ultrasonic ECHO |
| `D5` | `IN1` + rear trig (see F1) |
| `D6` | `ENA` |
| `D9` | `IN4` |
| `D10` | `IN3` |
| `D11` | LEFT ultrasonic ECHO |

To free one, move `LEFT_ECHO` off `D11` (to `A0`), then set `ENB = D11`.

### 🟡 F3. All ultrasonic pins are `TODO_VERIFY`

`config/robot.yaml` still has `trig: "TODO_VERIFY"` for all four sensors — the
config does not yet agree with the firmware. Whichever pins you actually use,
set them in **both** places.

### 🟡 F4. `ULTRASONIC_ENABLED = 0`

Sensors are compiled **out**. Until you set it to `1`, `SENSOR` reports
`-1` for every direction and the Layer-1 proximity stop never fires.

### 🟡 F5. `MOTOR_PWM_ENABLED = 0`

Any non-zero speed is **full speed**. Do the first motion tests with the wheels
off the ground.

### 🟡 F6. Geometry is `null`

`robot.wheel_track_m` / `wheel_diameter_m` are unmeasured, so odometry and
navigation cannot be trusted. Measure them (`hardware.md` §10).

### 🟡 F7. Safety thresholds are `NOT_VERIFIED`

Front/rear 20 cm, left/right 15 cm are software defaults, not measurements.

---

## 6. A pin map that clears F1 and F2

| Function | Pin | Why |
| --- | --- | --- |
| `IN1` / `IN2` | `D5` / `D4` | unchanged |
| `ENA` | `D6` | PWM ✅ |
| `IN3` / `IN4` | `D10` / `D9` | unchanged |
| **`ENB`** | **`D11`** | PWM ✅ — moved off `D8` |
| Front trig / echo | `D12` / `D13` | unchanged |
| Left trig / echo | `D7` / **`A0`** | echo moved off `D11` |
| Right trig / echo | `D2` / `D3` | unchanged |
| **Rear trig / echo** | **`A1` / `A2`** | moved off `D4`/`D5` |

Change it in **both** `firmware/.../*.h` **and** `config/robot.yaml`, then
re-flash and re-verify.

---

## 7. Software ↔ hardware mapping

| Hardware | Firmware | Pi-side code |
| --- | --- | --- |
| Motors / L298N | `motor_control.cpp` (`MotorControl`) | `amr/control/` (`DifferentialDrive`, `MotorDriver`) |
| Watchdog | `safety.cpp` (`Safety`, 1000 ms) | `amr/safety/` (`SafetyManager`) |
| Ultrasonic | `ultrasonic.cpp` (`Ultrasonic`) | `amr/sensors/` (`UltrasonicManager`) |
| Serial link | `protocol.cpp` | `amr/communication/protocol.py` |
| Camera | — | `amr/camera/` (`CameraManager`, `CameraSource`) |

Two processors on purpose: the Pi runs anything slow or buggy; the UNO runs the
small loop that must not miss a beat. The UNO **boots stopped** and stops itself
on watchdog timeout or a close obstacle — so a Pi crash cannot leave it driving.

---

## 8. Verdict

**Structure: sound.** One serial link, one power rail for the motors, a common
ground, and a clean split between the Pi and the UNO.

**Two blocking wiring faults** (`F1`, `F2`) that must be fixed before the motors
and sensors can both be trusted, plus five unverified values (`F3`–`F7`).

**Fix order:** resolve `F1`/`F2` in the headers *and* the config → flash → then
work through [`WIRING_CHECK.md`](WIRING_CHECK.md) → [`DEPLOY.md`](DEPLOY.md) →
[`hardware.md`](hardware.md) §7.

**See also:** [`WIRING_CHECK.md`](WIRING_CHECK.md) · [`hardware.md`](hardware.md) ·
[`DEPLOY.md`](DEPLOY.md) · [`serial_protocol.md`](serial_protocol.md)
