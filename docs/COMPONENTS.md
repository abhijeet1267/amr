# Component & connection analysis

Every part in the build, how they connect, and every finding that falls out of  
reading the firmware and config side by side. Derived from the **actual source**  
— `firmware/arduino/amr_controller/*.h`, `config/*.yaml` — not from assumptions.

> Nothing here has been run on real hardware. Where a value is a placeholder it  
> says so.

---

## 1. Component inventory

| #   | Component                 | Role                                                | Power source              | Interface                | Where it's configured              |
| --- | ------------------------- | --------------------------------------------------- | ------------------------- | ------------------------ | ---------------------------------- |
| 1   | **Raspberry Pi 5**        | brain: web server, safety policy, navigation, tasks | its own official PSU      | —                        | `config/serial.yaml`               |
| 2   | **Arduino UNO**           | reflexes: motor drive, watchdog, hardware stop      | 5 V via USB from the Pi   | USB CDC serial           | `firmware/.../*.h`                 |
| 3   | **L298N H-bridge**        | drives the two motors (direction + PWM)             | **external battery pack** | 6 GPIO from the UNO      | `firmware/.../motor_control.h`     |
| 4   | **2× DC gear motor**      | differential drive, one per side                    | via the L298N             | 2 wires each             | `config/robot.yaml`                |
| 5   | **4× HC-SR04 ultrasonic** | front / left / right / rear ranging                 | 5 V from the UNO          | 8 GPIO (4 trig + 4 echo) | `firmware/.../ultrasonic.h`        |
| 6   | **Raspberry Pi Camera**   | vision (optional)                                   | from the Pi               | CSI ribbon               | `config/robot.yaml` → `camera`     |
| 7   | **Motor battery pack**    | motor power                                         | —                         | 2 wires to the L298N     | —                                  |
| 8   | **Chassis + caster**      | mechanical                                          | —                         | —                        | `robot.wheel_track_m` (unmeasured) |

**Not present** (no hardware exists in this repo, despite code paths): gripper,  
RFID reader, gas/fire sensors. Those subsystems are simulated only.

---

> **Pin map applied (2026-10-12).** The final AMR pin chart is now implemented
> in the firmware headers *and* `config/robot.yaml`. **Nothing has been run on
> real hardware** — the map is wired into code, not verified on a bench.

```
        ┌───────────────────────────────────────────────────────────────┐
        │  Raspberry Pi 5   (brain)                                     │
        │  python -m amr.main --web                                     │
        └───┬────────────────────────────┬──────────────────────────────┘
            │ USB (CDC serial)           │ CSI ribbon
            │ 9600 8N1                   │
    ┌───────▼──────────────────────────┐ ┌▼────────────┐
    │  Arduino UNO (reflexes)          │ │ imx219 cam  │
    │                                  │ └─────────────┘
    │  D2..D9   4× HC-SR04 (8 pins)    │
    │  D10/D11  L298N ENA/ENB (PWM)    │
    │  D12/D13  L298N IN1/IN2 (left)   │
    │  A2/A3    L298N IN4/IN3 (right)  │
    │  A1       DHT11 data             │
    │  A0       buzzer                 │
    │  A4/A5    I2C LCD (SDA/SCL)      │
    │  MQ AO    NOT ASSIGNED           │
    └──┬────────────────────────────────┴───┐
       │ 6 GPIO                            │ 8 GPIO
   ┌───▼──────────┐   ┌────────────────────▼──────────────┐
   │  L298N       │   │ 4× HC-SR04 + DHT11 + LCD + buzzer │
   └───┬──────────┘   └───────────────────────────────────┘
       │ OUT1/2, OUT3/4
   ┌───▼──────────────┐
   │ 2× DC gear motor │
   └──────────────────┘

   MOTOR BATTERY PACK ──► L298N 12V/GND  (never the Pi's or Arduino's 5 V)
   Common ground: battery − ─ L298N GND ─ Arduino GND ─ (Pi via USB)
```

### Wire-by-wire

| From                   | To                         | Signal            | Notes                                    |
| ---------------------- | -------------------------- | ----------------- | ---------------------------------------- |
| Pi USB-A               | Arduino USB-B              | serial, 9600 8N1  | data cable required; also powers the UNO |
| Arduino `D5`           | L298N `IN1`                | left forward      |                                          |
| Arduino `D4`           | L298N `IN2`                | left reverse      | **also rear ultrasonic trig — see §5**   |
| Arduino `D6`           | L298N `ENA`                | left enable (PWM) | PWM-capable ✅                           |
| Arduino `D10`          | L298N `IN3`                | right forward     |                                          |
| Arduino `D9`           | L298N `IN4`                | right reverse     |                                          |
| Arduino `D8`           | L298N `ENB`                | right enable      | **not PWM-capable — see §5**             |
| L298N `OUT1`/`OUT2`    | left motor                 | motor drive       | swap the 2 leads to reverse that wheel   |
| L298N `OUT3`/`OUT4`    | right motor                | motor drive       |                                          |
| Battery `+`            | L298N `12V` (VS)           | motor power       |                                          |
| Battery `−`            | L298N `GND`                | motor return      | **must be common with Arduino GND**      |
| Arduino `5V`/`GND`     | each HC-SR04 `VCC`/`GND`   | sensor power      | 5 V, not 3.3 V                           |
| Arduino trig/echo pins | each HC-SR04 `Trig`/`Echo` | ranging           | see §3                                   |
| Pi CSI                 | camera ribbon              | camera            | latch closed, contacts correct way       |

---

## 3. Arduino pin allocation — every pin, and what's on it

| Pin       | Assigned to               | Kind               | Source            |
| --------- | ------------------------- | ------------------ | ----------------- |
| `D0`      | USB RX                    | serial             | reserved          |
| `D1`      | USB TX                    | serial             | reserved          |
| `D2`      | FRONT ultrasonic `TRIG`   | output             | `ultrasonic.h`    |
| `D3`      | FRONT ultrasonic `ECHO`   | input              | `ultrasonic.h`    |
| `D4`      | LEFT ultrasonic `TRIG`    | output             | `ultrasonic.h`    |
| `D5`      | LEFT ultrasonic `ECHO`    | input              | `ultrasonic.h`    |
| `D6`      | RIGHT ultrasonic `TRIG`   | output             | `ultrasonic.h`    |
| `D7`      | RIGHT ultrasonic `ECHO`   | input              | `ultrasonic.h`    |
| `D8`      | REAR ultrasonic `TRIG`    | output             | `ultrasonic.h`    |
| `D9`      | REAR ultrasonic `ECHO`    | input              | `ultrasonic.h`    |
| `D10`     | `ENA` (left PWM)          | PWM output ✅      | `motor_control.h` |
| `D11`     | `ENB` (right PWM)         | PWM output ✅      | `motor_control.h` |
| `D12`     | `IN1` (left forward)      | output (+ LED)     | `motor_control.h` |
| `D13`     | `IN2` (left reverse)      | output (+ LED)     | `motor_control.h` |
| `A0`      | buzzer                    | digital output     | `buzzer.h`        |
| `A1`      | DHT11 `DATA`              | digital I/O        | `dht11.h`         |
| `A2`      | `IN4` (right reverse)     | output             | `motor_control.h` |
| `A3`      | `IN3` (right forward)     | output             | `motor_control.h` |
| `A4`      | LCD `SDA`                 | I2C data           | `lcd_i2c.h`       |
| `A5`      | LCD `SCL`                 | I2C clock          | `lcd_i2c.h`       |

Every usable pin is allocated. **`A0`-`A5` are no longer spare** — which is
exactly why the MQ gas sensor's analog output has no assignment (see F3).

---

## 4. Interfaces

| Link              | Physical                             | Protocol                                | Configured in              |
| ----------------- | ------------------------------------ | --------------------------------------- | -------------------------- |
| Pi ↔ Arduino      | USB (CDC serial) — **not** GPIO UART | 9600 8N1, newline ASCII, protocol `1.0` | `config/serial.yaml`       |
| Pi ↔ camera       | CSI ribbon — **not** USB             | libcamera / picamera2 / V4L2            | `config/robot.yaml`        |
| Arduino ↔ L298N   | 6 GPIO                               | direction + enable                      | `motor_control.h`          |
| Arduino ↔ HC-SR04 | 8 GPIO                               | 40 kHz pulses, `pulseIn`                | `ultrasonic.h`             |
| App ↔ Pi          | Wi-Fi / LAN                          | HTTP JSON on port 8080                  | `config/applications.yaml` |

**The Pi never touches a motor or sensor pin.** It sends `MOVE`/`STOP` over  
serial; the firmware is the only code that knows about pins.

---

## 5. Findings

### ✅ RESOLVED by the applied pin map (2026-10-12)

| Old fault | What it was | How the chart fixes it |
| --------- | ----------- | ---------------------- |
| **F1** | `D4`/`D5` were double-booked (left motor **and** rear ultrasonic) | Rear ultrasonic moved to `D8`/`D9`; motor moved to `D12`/`D13`. No pin is shared. |
| **F2** | `ENB = D8` is **not** PWM-capable, so the right motor could not be speed-controlled | `ENB = D11`, which is PWM-capable. `ENA = D10` likewise. |
| **F3** | Ultrasonic pins in `config/robot.yaml` were `TODO_VERIFY` | Now match the firmware: `D2`/`D3` front, `D4`/`D5` left, `D6`/`D7` right, `D8`/`D9` rear. |
| **F4** | `ULTRASONIC_ENABLED = 0` compiled the sensors out | Now `1` — **unverified on hardware.** |
| **F5** | `MOTOR_PWM_ENABLED = 0` meant every speed was full speed | Now `1`, because both enable pins are on real PWM pins. **Unverified on hardware.** |

### 🔴 F3 (new). The MQ gas sensor has no pin

`A0` buzzer, `A1` DHT11, `A2`/`A3` motor, `A4`/`A5` LCD — **no analog input is
free** for the MQ sensor's `AO`. The firmware therefore ships
`PIN_GAS_AO -1` + `GAS_ENABLED 0`: a `GAS` command reports **`-1`** and the Pi
shows `UNAVAILABLE`. It never reports a fake `0 ppm`.

**Free an analog pin** — move the buzzer onto an I2C expander (sharing the LCD's
`A4`/`A5` bus), or drop the buzzer — then set `PIN_GAS_AO` and `GAS_ENABLED 1`.

### 🟡 F4 (new). The buzzer must not use `tone()`

`tone()` occupies **Timer2**, which also drives **`D11` = ENB** (right-motor
PWM). Using it would corrupt right-wheel speed control, so `buzzer.cpp` toggles
the pin with `digitalWrite()` and no timer. A passive buzzer sounds at the
toggled frequency; an active 3-wire module just clicks.

### 🟡 F5 (new). The DHT11 library is hand-rolled

No third-party library: the DHT11 bit protocol is bit-banged on `A1`
(`dht11.cpp`). **Not tested on hardware.** It updates at ~1 Hz, so the Pi only
reads it on an explicit `ENV` command.

### 🟡 F6 (new). The LCD driver is minimal

A from-scratch HD44780-over-PCF8574 driver using the core's built-in `Wire`
(lcd_i2c.cpp) — no `LiquidCrystal_I2C` dependency. Address defaults to `0x27`;
some modules are `0x3F`. **Not tested on hardware.**

### 🟡 Still open (unchanged)

| Finding | Effect |
| ------- | ------ |
| Geometry `null` (`wheel_track_m`, `wheel_diameter_m`) | odometry / navigation cannot be trusted |
| Safety thresholds `NOT_VERIFIED` | software defaults, not measurements |
| `D13` is also the onboard LED | the LED flickers as the left motor reverses — harmless |
| Everything on real hardware | **nothing has been flashed or run** |

---

## 7. Software ↔ hardware mapping

| Hardware       | Firmware                             | Pi-side code                                        |
| -------------- | ------------------------------------ | --------------------------------------------------- |
| Motors / L298N | `motor_control.cpp` (`MotorControl`) | `amr/control/` (`DifferentialDrive`, `MotorDriver`) |
| Watchdog       | `safety.cpp` (`Safety`, 1000 ms)     | `amr/safety/` (`SafetyManager`)                     |
| Ultrasonic     | `ultrasonic.cpp` (`Ultrasonic`)      | `amr/sensors/` (`UltrasonicManager`)                |
| Serial link    | `protocol.cpp`                       | `amr/communication/protocol.py`                     |
| Camera         | —                                    | `amr/camera/` (`CameraManager`, `CameraSource`)     |

Two processors on purpose: the Pi runs anything slow or buggy; the UNO runs the  
small loop that must not miss a beat. The UNO **boots stopped** and stops itself  
on watchdog timeout or a close obstacle — so a Pi crash cannot leave it driving.

---

## 8. Verdict

**Structure: sound.** One serial link, one power rail for the motors, a common  
ground, and a clean split between the Pi and the UNO.

**The two blocking wiring faults are resolved** in code (both enable pins are on
real PWM pins, and no ultrasonic pin shares a line with a motor). What remains
is **hardware verification**: nothing in this repository has been flashed or run
on a real robot.

**Fix order:** install the AVR toolchain and compile (`docs/setup_arduino.md`)
→ wire the sensors → photograph for [`WIRING_CHECK.md`](WIRING_CHECK.md) → flash
→ staged bring-up, wheels off the ground (`docs/hardware.md` §7).

> **One open decision:** the MQ gas sensor has no analog pin. Free one before
> wiring it — or leave it off and the firmware reports `UNAVAILABLE` honestly.

**See also:** [`WIRING_CHECK.md`](WIRING_CHECK.md) · [`hardware.md`](hardware.md) ·  
[`DEPLOY.md`](DEPLOY.md) · [`serial_protocol.md`](serial_protocol.md)
