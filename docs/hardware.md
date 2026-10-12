# Hardware verification & bring-up

This is the **master checklist** for taking the AMR from "runs on mocks" to  
"runs on the real robot". It is the document `config/robot.yaml`,  
`config/safety.yaml`, `firmware/arduino/amr_controller/*.h` and  
`raspberry_pi/amr/utils/config.py` all point at.

> **Status: nothing in this repository has ever been run on physical hardware.**  
> The suite is mock-based, the firmware has never been flashed to an UNO, and no  
> camera has produced a real frame. This document exists to change that — and it  
> says exactly what to do, in what order, and how to know each step worked.

---

## 0. The honesty rule (read first)

This project never invents a hardware fact. Three placeholder markers appear  
throughout, and every one of them is an instruction to _you_:

| Marker         | Where                        | Means                                                 |
| -------------- | ---------------------------- | ----------------------------------------------------- |
| `null`         | `robot.yaml` geometry        | Not measured. Must be measured with a ruler/calipers. |
| `TODO_VERIFY`  | ultrasonic trig/echo pins    | Not wired yet. Must be set from your actual wiring.   |
| `NOT_VERIFIED` | `safety.yaml`, `hazard.yaml` | Thresholds are software defaults, never validated.    |

**Definition of done for this whole document:** every component passes its own  
validation _and_ the end-to-end test passes, then you flip the statuses to  
`VERIFIED` and record who/when/where (§11). Until then, treat the robot as  
untrusted at any speed above a crawl.

The most important rule, and it is not negotiable:

> ⚠️ **The motors are powered by the L298N external supply — never the  
> Raspberry Pi 5 V rail and never the Arduino 5 V rail.** The Pi cannot source  
> motor current; trying will brown-out or destroy it.

---

## 1. Bill of materials

| #   | Part                          | Notes that bite you if ignored                            |
| --- | ----------------------------- | --------------------------------------------------------- |
| 1   | Raspberry Pi 5 (or 4)         | Any Pi with a 40-pin header and a CSI port.               |
| 2   | microSD card (≥ 16 GB, A2)    | Raspberry Pi OS **64-bit Bookworm** recommended.          |
| 3   | Pi power supply               | Official PSU. Undervoltage causes random serial dropouts. |
| 4   | Arduino UNO (+ USB cable)     | The cable must be a **data** cable, not charge-only.      |
| 5   | L298N dual H-bridge module    | With **ENA/ENB jumper caps** (you will remove them).      |
| 6   | 2× DC gear motor + wheels     | Differential drive, one per side.                         |
| 7   | Separate motor battery pack   | e.g. 4–6× AA, or 2S Li-ion. Powers the L298N only.        |
| 8   | 4× HC-SR04 ultrasonic         | 5 V logic. Front/Left/Right/Rear.                         |
| 9   | Raspberry Pi Camera Module    | + the **correct ribbon** for your Pi's CSI connector.     |
| 10  | DHT11 temperature/humidity    | 3-pin module. `DATA` -> `A1`. **Pin order varies — read the silkscreen.**  |
| 11  | MQ-series gas sensor (e.g. MQ-2) | Analog output. **No pin is free for it yet** — see §5.                 |
| 12  | 16x2 I2C LCD (PCF8574)        | `SDA`->`A4`, `SCL`->`A5`. Address usually `0x27`, sometimes `0x3F`.    |
| 13  | 2-wire buzzer                 | + -> `A0`. Passive makes a tone; active only clicks.                     |
| 14  | Jumper wires, chassis, caster | Plus a multimeter.                                                        |

> A Pi 5 uses a narrower **mini** CSI ribbon than a Pi 4. The wrong ribbon is  
> the single most common "the camera doesn't work" cause.

---

## 2. System overview

```
        ┌────────────────────────────┐
        │  Raspberry Pi (the brain)  │   Python control stack
        │  web · nav · tasks · safety│   `python -m amr.main --web`
        └───────┬─────────────┬──────┘
                │ USB CDC     │ CSI ribbon
                │ 9600 8N1    │
        ┌───────▼──────┐   ┌──▼─────────────┐
        │ Arduino UNO  │   │ Camera Module  │
        │ (the reflexes)│  └────────────────┘
        └───┬──────┬───┘
     6 GPIO │      │ 8 GPIO
   ┌────────▼──┐ ┌─▼─────────────┐
   │  L298N    │ │ 4× HC-SR04    │
   │ H-bridge  │ │ F / L / R / B │
   └────┬──────┘ └───────────────┘
        │ motor power (external pack — NEVER the Pi/Arduino 5 V)
   ┌────▼──────────────┐
   │ 2× DC gear motor  │
   └───────────────────┘
```

**Two processors on purpose.** The Pi runs everything that may be slow or buggy.  
The Arduino runs the small loop that must not miss a beat, and it **boots  
stopped** — it only moves on an explicit command and can stop itself via the  
watchdog or a close obstacle. A Pi crash, reboot, or pulled cable therefore can  
never leave the robot driving.

---

## 3. Interfaces

| Link              | Physical                                   | Protocol                                           | Where it is configured         |
| ----------------- | ------------------------------------------ | -------------------------------------------------- | ------------------------------ |
| Pi ↔ Arduino      | **USB** (USB CDC serial) — _not_ GPIO UART | 9600 8N1, newline-terminated ASCII, protocol `1.0` | `config/serial.yaml`           |
| Pi ↔ camera       | **CSI ribbon** — _not_ USB                 | libcamera / picamera2 / V4L2                       | `config/robot.yaml` → `camera` |
| Arduino ↔ L298N   | 6 GPIO (2 direction + 1 enable per side)   | —                                                  | `firmware/.../motor_control.h` |
| Arduino ↔ HC-SR04 | 8 GPIO (4 trig + 4 echo)                   | 40 kHz pulses, `pulseIn`                           | `firmware/.../ultrasonic.h`    |
| L298N ↔ motors    | 2 wires per motor + external power         | —                                                  | —                              |

The Pi **never** talks to motor or sensor pins directly. It sends `MOVE`/`STOP`  
over the serial link, and the firmware is the only code that knows about pins.

---

## 4. Wiring

### 4.1 Power (get this right first)

```
   Motor battery (+) ──► L298N  +12V   (VS)
   Motor battery (−) ──► L298N  GND ──┬──► Arduino GND   (COMMON GROUND — required)
                                      └──► Pi GND        (via the USB cable shield/ground)
   L298N 5V output  ──► (leave the 5V jumper ON if the module's regulator feeds its logic)
```

Rules:

1. **Motors run off the external pack.** The Pi's 5 V and the Arduino's 5 V are  
   logic rails only.
2. **All grounds must be common** — battery, L298N, Arduino, and (through USB)  
   the Pi. A missing common ground makes the serial link flaky and the sensors  
   read garbage.
3. Power the Pi from its own official PSU. Do **not** try to run the Pi from the  
   motor pack through the L298N.

### 4.2 Motors → L298N → Arduino

The firmware's pin map (`motor_control.h`) — **verify these against your wiring  
before flashing**:

| Signal        | Arduino pin | L298N pin | Notes                           |
| ------------- | ----------- | --------- | ------------------------------- |
| Left forward  | `D5`        | `IN1`     |                                 |
| Left reverse  | `D4`        | `IN2`     |                                 |
| Left enable   | `D6`        | `ENA`     | PWM-capable ✅                  |
| Right forward | `D10`       | `IN3`     |                                 |
| Right reverse | `D9`        | `IN4`     |                                 |
| Right enable  | `D8`        | `ENB`     | **NOT PWM-capable ⚠️ — see §5** |

> **Remove the ENA/ENB jumper caps** on the L298N. With the caps fitted, `ENA`  
> and `ENB` are tied to the module's own 5 V and the Arduino's PWM output is  
> ignored — the motors will run at full speed no matter what you command.

### 4.3 Ultrasonic (HC-SR04)

Firmware placeholders (`ultrasonic.h`) — **these are `TODO_VERIFY` and collide  
with the motor pins; see §5 before you wire them**:

| Sensor | Trig    | Echo    |
| ------ | ------- | ------- |
| Front  | `D12`   | `D13`   |
| Left   | `D7`    | `D11`   |
| Right  | `D2`    | `D3`    |
| Rear   | `D4` ⚠️ | `D5` ⚠️ |

Wiring each HC-SR04: `VCC → 5 V`, `GND → GND`, `Trig → Arduino trig pin`,  
`Echo → Arduino echo pin`. The UNO is 5 V logic, so **no level shifter is  
needed** on the Arduino side (you _would_ need one if these were on the Pi's  
3.3 V GPIO — which is exactly why the design puts them on the Arduino).

### 4.4 Camera ribbon

1. Power the Pi **off** before touching the ribbon.
2. Lift the CSI connector's plastic latch, slide the ribbon in with the metal  
   contacts facing the correct way for your board, close the latch.
3. Use the ribbon that matches your Pi's connector width (Pi 5 = mini CSI).
4. Re-seat it once if the camera is not detected — partial seating is common.

---

## 5. Pin map — **applied** (2026-10-12)

The final AMR pin chart is implemented: both conflicts below are resolved in the
firmware headers and mirrored in `config/robot.yaml`. **Nothing has been run on
real hardware** — this is the map the code now expects, not a verified build.

| Function        | Pin           | Status                              |
| --------------- | ------------- | ----------------------------------- |
| `IN1` / `IN2`   | `D12` / `D13` | left motor (D13 also drives the LED) |
| `ENA`           | `D10`         | **PWM ✅**                          |
| `IN3` / `IN4`   | `A3` / `A2`   | right motor (analog pins as digital) |
| `ENB`           | `D11`         | **PWM ✅** — the former D8 fault     |
| Front trig/echo | `D2` / `D3`   |                                     |
| Left trig/echo  | `D4` / `D5`   |                                     |
| Right trig/echo | `D6` / `D7`   |                                     |
| Rear trig/echo  | `D8` / `D9`   | moved off the motor's D4/D5        |
| DHT11 `DATA`    | `A1`          | bit-banged, no library             |
| Buzzer          | `A0`          | `digitalWrite` toggle — **no `tone()`** |
| LCD `SDA`/`SCL` | `A4` / `A5`   | PCF8574 backpack, `0x27`           |
| MQ gas `AO`     | **none**      | 🔴 no analog pin is free (see below) |

### The resolved conflicts (kept for the record)

- **Rear ultrasonic vs left motor:** the rear sensor used to share `D4`/`D5`
  with `PIN_IN1`/`PIN_IN2`. The rear sensor now sits on `D8`/`D9` and the motor
  on `D12`/`D13`, so no pin is double-booked.
- **`ENB` was not PWM-capable:** `D8` cannot do `analogWrite()`. `ENB` is now
  `D11`, which can, and `MOTOR_PWM_ENABLED` is `1`.

### 🔴 The gas sensor still has no pin

`A0`–`A5` are fully allocated (buzzer, DHT11, motor ×2, LCD ×2), so the MQ
sensor's analog output has nowhere to go. The firmware ships
`PIN_GAS_AO -1` / `GAS_ENABLED 0`, so a `GAS` command returns **`-1`** and the
dashboard reports `UNAVAILABLE` — never a fabricated `0 ppm`.

To wire it: free an analog pin (move the buzzer to an I²C expander on `A4`/`A5`,
or drop the buzzer), set `PIN_GAS_AO` in `gas_sensor.h` and `GAS_ENABLED 1`, then
re-flash.

> **Rule:** when you change a pin, change it in **both**
> `firmware/arduino/amr_controller/*.h` **and** `config/robot.yaml`. The two must
> agree, and `ULTRASONIC_ENABLED` / `MOTOR_PWM_ENABLED` must be `1` for the
> sensors and PWM speed to work at all.

---

## 6. Prerequisites & tools

On your **laptop** (for flashing the Arduino):

- Arduino IDE 2.x, or `arduino-cli`
- The `arduino:avr` core (provides the UNO board definition)
- A USB cable that carries data

On the **Pi**:

- Raspberry Pi OS 64-bit; run `sudo apt update && sudo apt full-upgrade`
- Python 3.10–3.12 (the matrix CI tests)
- `pyserial` — installed by `pip install -e ".[serial]"` or `".[dev]"`
- Camera stack: `libcamera` tools (`libcamera-still`) and/or `python3-picamera2`
- Optional: `opencv-python` + `numpy` for the V4L2 camera path

Physical:

- A multimeter (for continuity and voltage checks)
- A way to **raise the drive wheels off the ground** for every first-run test

Full install commands are in [`setup_arduino.md`](setup_arduino.md) and  
[`setup_raspberry_pi.md`](setup_raspberry_pi.md).

---

## 7. Bring-up procedure — staged, never skip a stage

Each stage has a **validation** you must see pass before continuing. Stages 1–4  
can be done with the wheels off the ground; keep them that way until Stage 7.

### Stage 0 — Bench preparation

- Wheels **off the ground** (robot on a stand or blocks).
- Motor battery **disconnected**.
- Everything powered down.

**Validation:** you can spin both wheels freely by hand.

### Stage 1 — Flash the firmware and prove the serial link

Follow [`setup_arduino.md`](setup_arduino.md). Then, from the Pi:

```bash
# Discover the port (it may be ttyACM0 or ttyUSB0)
ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null

# Talk to the firmware directly
python3 - <<'PY'
import serial, time
port = "/dev/ttyACM0"          # <-- your discovered port
s = serial.Serial(port, 9600, timeout=1)
time.sleep(2)                  # UNO resets when the port opens
s.reset_input_buffer()
for cmd, want in [("PING", "PONG"), ("VERSION", "VERSION 1.0"),
                  ("STATUS", "STATUS"), ("SENSOR", "SENSOR")]:
    s.write((cmd + "\n").encode())
    print(f"{cmd:8} -> {s.readline().decode(errors='replace').strip()}")
s.close()
PY
```

**Validation:** you see `PONG`, `VERSION 1.0`, a `STATUS …` line, and a
`SENSOR F=… L=… R=… B=…` line. The first line after opening the port may be the
boot banner `AMR FW READY v1.0` — that is expected and harmless.

### Stage 2 — Motors (wheels still off the ground)

Connect the motor battery. Using the legacy single-letter commands for a quick
bench test (any non-zero speed = full speed while `MOTOR_PWM_ENABLED` is 0):

```bash
python3 - <<'PY'
import serial, time
s = serial.Serial("/dev/ttyACM0", 9600, timeout=1); time.sleep(2)
s.reset_input_buffer()
for cmd in ["F", "S", "L", "S", "R", "S", "B", "S"]:
    s.write((cmd + "\n").encode())
    print(cmd, "->", s.readline().decode(errors="replace").strip())
    time.sleep(0.6)
s.close()
PY
```

**Validation:** each letter moves the wheels the way the table in
[`serial_protocol.md`](serial_protocol.md) says — `F` both forward, `L` spin
left, `R` spin right, `B` both back, `S` stop. **If a wheel turns the wrong
way**, swap that motor's two leads at the L298N (or swap its IN pins). Do this
now, on the bench, not on the floor.

### Stage 3 — Ultrasonic sensors

First set the pins (§5), set `ULTRASONIC_ENABLED` to `1`, and re-flash. Then:

```bash
python3 - <<'PY'
import serial, time
s = serial.Serial("/dev/ttyACM0", 9600, timeout=1); time.sleep(2)
s.reset_input_buffer()
for _ in range(10):
    s.write(b"SENSOR\n")
    print(s.readline().decode(errors="replace").strip())
    time.sleep(0.3)
s.close()
PY
```

**Validation:** hold a book ~30 cm in front of each sensor in turn and watch the
matching number change; move it away and it grows. A `-1` means _no echo_ (clear
path), **not** an obstacle — this is deliberate and matches the safety logic.

### Stage 4 — Camera

Follow [`setup_raspberry_pi.md`](setup_raspberry_pi.md) §camera. Quick check:

```bash
libcamera-still -n -t 200 -o /tmp/frame.jpg && file /tmp/frame.jpg
```

**Validation:** `/tmp/frame.jpg` is a real JPEG of what the lens sees. Then start
the stack and confirm `GET /camera/status` reports `status: "LIVE"` (not
`SIMULATION`, not `UNAVAILABLE`).

### Stage 5 — The Pi stack, headless, against real hardware

```bash
cd raspberry_pi && source .venv/bin/activate
python -m amr.main --web --port 8080      # NO --mock: this uses the real serial link
```

**Validation:** the banner prints, `/health` returns 200, and `/status` shows
`connected: true`. Open `http://<pi-ip>:8080/` and confirm the telemetry tiles
update. This is also where you run [`tools/health_check.sh`](../tools/health_check.sh).

### Stage 6 — The operator console and the app

- Console: open `http://<pi-ip>:8080/command-center`.
- Flutter client: launch it, and on the **Connection** screen enter the Pi's
  **IP address** and port (not `localhost` — that would mean the phone itself).
  Tap **Ping**; the badge turns Connected.

**Validation:** the client's Dashboard, Map and Camera screens populate from the
live robot, and the Teleop screen's E-STOP is reachable. Drive **only with the
wheels still off the ground** the first time.

### Stage 7 — Autonomous mission (only after §10 is done)

Do **not** run a mission until you have measured the geometry and confirmed the
stop distances (§10). Then, with clear floor space and a hand on the power
switch:

```bash
# Monitor only (safe): the console shows a live pose but drives nothing.
python -m amr.main --web --port 8080
```

`--mission-demo` is **mock-only by design** — the runtime refuses it against
real hardware (`main.py` raises `SystemExit`), because it commands autonomous
motion. Running a real autonomous round-trip is a deliberate, supervised step
you take after Stage 7 validation, not a flag.

---

## 8. Component validation summary

| Component     | Command                                     | Pass looks like                               |
| ------------- | ------------------------------------------- | --------------------------------------------- |
| Serial link   | `PING` / `VERSION` (§7 Stage 1)             | `PONG`, `VERSION 1.0`                         |
| Watchdog      | send one command, wait > 1 s, send nothing  | unsolicited `WATCHDOG TRIGGERED`, motors stop |
| Motors        | legacy `F/S/L/S/R/S` (§7 Stage 2)           | each direction correct                        |
| Ultrasonic    | `SENSOR` while moving a target (§7 Stage 3) | distance tracks the target; `-1` = clear      |
| Camera        | `libcamera-still …` (§7 Stage 4)            | real JPEG; `/camera/status` = `LIVE`          |
| Pi stack      | `python -m amr.main --web` (§7 Stage 5)     | `/health` 200, `/status` connected            |
| App           | Flutter Connection screen (§7 Stage 6)      | Ping → Connected; screens populate            |
| Health script | `tools/health_check.sh`                     | all checks PASS                               |

The watchdog test is worth doing deliberately: it is the safety property the
whole design rests on.

---

## 9. End-to-end validation

With wheels still off the ground:

1. Start the stack (Stage 5) and the console (Stage 6).
2. In the console, watch `telemetry`, `map`, `safety` and `events` update at 1 Hz.
3. Press the software **E-STOP**. Confirm: motors stop, mode → `SAFETY_STOP`,
   and the console shows the safety banner.
4. Release/acknowledge, then command a slow forward. Confirm the wheels turn and
   the event log records `COMMAND FORWARD L=… R=…`.
5. Cover the front sensor. Confirm the firmware's proximity stop halts the
   motors (Layer 1) **and** the Pi reports a safety stop (Layer 3).
6. Pull the USB cable. Confirm `WATCHDOG TRIGGERED` and that the robot stops;
   the Pi should report the link as disconnected.

Only when all six pass should you put the robot on the floor — and then only at
a crawl, in an open area, with a hand on the power switch.

---

## 10. Measuring geometry & confirming thresholds (then flip to VERIFIED)

### Geometry — `config/robot.yaml`

- `wheel_diameter_m`: measure the rolling diameter of a wheel (calipers or a
  tape around the tyre), in **metres**.
- `wheel_track_m`: measure the distance between the **centres** of the left and
  right wheels, in **metres**.

Set both, replacing `null`. They feed odometry and navigation, so a wrong value
makes the robot drive the wrong distance and turn the wrong angle.

### Thresholds — `config/safety.yaml`

1. For each of the four directions, drive slowly toward an obstacle and record
   the distance at which a stop is _actually_ needed for your robot's mass and
   speed.
2. Set `front/rear/left/right_stop_distance_cm` to those measured values.
3. Confirm `watchdog_timeout_ms` gives the Pi enough time to answer under load
   (the Pi polls well under 1 s, so 1000 ms is a sane starting point — but
   confirm it on your hardware).
4. Record who/when/where (§11) and set `status: VERIFIED`.

> Note the known gap: the Pi never sends the `WDT <ms>` verb the firmware
> implements, so the Arduino keeps its compiled-in 1000 ms default. If you change
> `watchdog_timeout_ms` in the config, change `DEFAULT_WATCHDOG_MS` in
> `amr_controller.ino` to match, or the two silently diverge.

---

## 11. Verification record

Fill this in and keep it with the robot. It is what turns `NOT_VERIFIED` into a
claim you can defend.

```
Hardware verification record
────────────────────────────
Date:
Operator:
Board / Pi revision:
Arduino:            UNO, firmware PROTOCOL_VERSION ______
Serial port:        /dev/______________ @ 9600

Geometry measured:
  wheel_diameter_m = ______
  wheel_track_m    = ______

Stop distances confirmed (cm):  front ___  rear ___  left ___  right ___
Watchdog timeout confirmed (ms): ______

Component results:
  [ ] Serial link      [ ] Watchdog      [ ] Motors
  [ ] Ultrasonic x4    [ ] Camera        [ ] Pi stack
  [ ] App (client)     [ ] E-STOP        [ ] End-to-end (all 6)

Statuses flipped to VERIFIED:   [ ] safety.yaml   [ ] robot.yaml (pins)
```

---

## 12. Common issues, by stage

| Stage      | Symptom                                    | Likely cause / fix                                                                               |
| ---------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| Serial     | No `/dev/ttyACM*`                          | Bad/charge-only USB cable; try another.                                                          |
| Serial     | Port name is `ttyUSB0`, not `ttyACM0`      | Different USB-serial chip. Update `serial.yaml` `port` or use discovery.                         |
| Serial     | `Permission denied`                        | Add your user to `dialout`: `sudo usermod -aG dialout $USER` then re-login.                      |
| Serial     | Port vanishes a few seconds after opening  | ModemManager grabbing it — see [`setup_raspberry_pi.md`](setup_raspberry_pi.md) (udev rule).     |
| Serial     | Garbage / `ERR UNKNOWN`                    | Baud mismatch (must be 9600) or wrong firmware.                                                  |
| Firmware   | Upload fails, "programmer not responding"  | Wrong board/port selected; try another USB cable/port.                                           |
| Motors     | Wheels don't turn at all                   | ENA/ENB jumpers still fitted; battery not connected; missing common ground.                      |
| Motors     | Wheels turn the wrong way                  | Swap that motor's two leads, or its IN pins.                                                     |
| Motors     | Only one side works                        | Check that side's IN pair + enable pin; check the L298N terminal screws.                         |
| Motors     | Pi reboots when motors start               | Motors drawing from the logic rail — give them the external pack.                                |
| Motors     | Speed control does nothing                 | `MOTOR_PWM_ENABLED` is 0, or `ENB` is on the non-PWM `D8` (§5).                                  |
| Ultrasonic | Always `-1`                                | Echo not wired; sensor not powered from 5 V; wrong pins.                                         |
| Ultrasonic | Random large values                        | Insufficient delay between sensors (they cross-talk) or a shared trig.                           |
| Ultrasonic | Reading equals a motor command glitch      | Rear sensor on `D4/D5`, colliding with the left motor (§5).                                      |
| Camera     | `UNAVAILABLE` in `/camera/status`          | Ribbon not seated / wrong ribbon / camera not enabled in `raspi-config`.                         |
| Camera     | `libcamera-still: command not found`       | `libcamera` tools not installed; install them or use the `v4l2` path.                            |
| App        | Can't connect from the phone               | Using `localhost` instead of the Pi's IP; Pi and phone on different networks.                    |
| App        | Connects but screens are empty             | Server running with `--mock`; the robot is simulated, not live.                                  |
| App        | Browser can't reach the robot cross-origin | By design — the server sends no CORS headers (a security choice). Use the client or same-origin. |
| Watchdog   | Motors stop ~1 s after you stop sending    | Working as intended — the watchdog fired. Send commands to keep it fed.                          |

---

## 13. Safety rules (non-negotiable)

1. Motors on the **external pack**; never the Pi or Arduino 5 V rail.
2. **Common ground** between battery, L298N, Arduino and Pi.
3. First runs **wheels off the ground**, always.
4. The E-STOP path — software, watchdog, or pulling power — must be reachable at
   all times; test it (§9) before trusting the robot.
5. Do not expose the web port to the internet: there is **no authentication**.
6. Do not enable `safety.avoidance` or autonomous missions until §10 is complete.

---

**See also:** [`setup_arduino.md`](setup_arduino.md) ·
[`setup_raspberry_pi.md`](setup_raspberry_pi.md) ·
[`serial_protocol.md`](serial_protocol.md) · [`safety.md`](safety.md) ·
[`camera.md`](camera.md) · [`../tools/health_check.sh`](../tools/health_check.sh)
