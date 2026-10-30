# Arduino firmware — build, flash, and validate

How to compile and upload the UNO firmware in
[`firmware/arduino/amr_controller/`](../firmware/arduino/amr_controller), and how
to prove it works before the Pi is involved. This is Stage 1 of
[`hardware.md`](hardware.md).

> **The firmware has never been flashed to a real UNO by this repository.** It
> compiles in the Arduino IDE / `arduino-cli`; it has not been run on hardware.
> This document is how you change that.

---

## 1. What you are flashing

| File                                    | Role                                                                                |
| --------------------------------------- | ----------------------------------------------------------------------------------- |
| `amr_controller.ino`                    | `setup()` / `loop()`: read a line, dispatch, run the watchdog, poll the ultrasonics |
| `protocol.h` / `protocol.cpp`           | Command parser — mirrors `raspberry_pi/amr/communication/protocol.py`               |
| `motor_control.h` / `motor_control.cpp` | L298N PWM + direction HAL                                                           |
| `safety.h` / `safety.cpp`               | Communication watchdog (default 1000 ms)                                            |
| `ultrasonic.h` / `ultrasonic.cpp`       | 4× HC-SR04 polling, `SENSOR F= L= R= B=`                                            |
| `dht11.h` / `dht11.cpp`                 | Bit-banged DHT11 on `A1`, `ENV T= H=` (no library)                                  |
| `gas_sensor.h` / `gas_sensor.cpp`       | MQ gas raw ADC. **No pin assigned**, so `GAS RAW=-1`                                |
| `lcd_i2c.h` / `lcd_i2c.cpp`             | 16×2 HD44780 over PCF8574 using the core's `Wire` (no library)                      |
| `buzzer.h` / `buzzer.cpp`               | Timer-free buzzer on `A0` (deliberately not `tone()`)                               |

Properties you can rely on:

- **Boots stopped.** It only moves on an explicit `MOVE`/legacy command.
- **Watchdog.** After `DEFAULT_WATCHDOG_MS` (1000 ms) of silence it stops, beeps,
  and emits `WATCHDOG TRIGGERED` once.
- **Proximity stop.** A _valid_ reading below its threshold stops the motors.
- **Sensors and PWM are enabled** (`ULTRASONIC_ENABLED 1`, `MOTOR_PWM_ENABLED 1`)
  because the applied pin map puts both ENA/ENB on real PWM pins (`D10`/`D11`).
  **Neither is verified on hardware.**
- **`dht11.cpp` and `lcd_i2c.cpp` are hand-rolled** — no third-party library, so
  `DHT11` and `LCD` need no library install. Neither is hardware-tested.
- **The buzzer avoids `tone()`** (Timer2 drives `D11` = ENB) and toggles the pin
  directly instead.

Compile-time switches, and what each now ships as:

```c
// motor_control.h — 1 because ENA(D10)/ENB(D11) are PWM-capable
#define MOTOR_PWM_ENABLED   1
// ultrasonic.h
#define ULTRASONIC_ENABLED  1
#define ULTRASONIC_TELEMETRY 0   // 1 = also emit unsolicited SENSOR lines
// gas_sensor.h — 0 with NO PIN: the pin chart leaves the MQ analog output
// unassigned, so GAS reports -1 and the Pi shows UNAVAILABLE (never 0 ppm).
#define GAS_ENABLED         0
#define PIN_GAS_AO          (-1)
```

---

## 2. Prerequisites

| Tool                   | Version | Why                                   |
| ---------------------- | ------- | ------------------------------------- |
| Arduino IDE            | 2.x     | Easiest path; bundles the toolchain   |
| — _or_ — `arduino-cli` | 0.35+   | Scriptable / headless                 |
| `arduino:avr` core     | latest  | Provides the **UNO** board definition |
| USB data cable         | —       | Charge-only cables cannot upload      |

Install with `arduino-cli` (Linux/macOS):

```bash
# Install the CLI (macOS example)
brew install arduino-cli

# Add the AVR core index and install the core (this brings avr-gcc + avrdude)
arduino-cli core update-index
arduino-cli core install arduino:avr

# Confirm the board is known
arduino-cli board listall | grep -i "uno"
```

---

## 3. Compile

### With the Arduino IDE

1. `File → Open…` → `firmware/arduino/amr_controller/amr_controller.ino`.
   The IDE loads every `.h`/`.cpp` in the folder as part of the sketch.
2. `Tools → Board → Arduino AVR Boards → Arduino Uno`.
3. `Tools → Port →` your UNO's port.
4. `Sketch → Verify/Compile` (the ✓ button).

**Pass:** "Done compiling", no errors, and a flash/RAM usage line.

### With `arduino-cli`

```bash
cd firmware/arduino/amr_controller
arduino-cli compile --fqbn arduino:avr:uno .
```

**Pass:** exit code 0 and a sketch-size report. To check without a board
attached, that is all you need.

---

## 4. Upload

```bash
# 1. Plug in the UNO, then find its port
arduino-cli board list
#   → e.g. /dev/ttyACM0  arduino:avr:uno

# 2. Upload
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:uno .
```

Or, in the IDE, press the **→ Upload** button.

> On Linux, if upload says _"Permission denied"_, add yourself to `dialout`:
> `sudo usermod -aG dialout $USER` and log out/in. On macOS the port is usually
> `/dev/cu.usbmodem*`.

**Pass:** avrdude reports "bytes written" and "Verified", and the board resets.

---

## 5. Validate over the serial monitor

Open the serial monitor at **9600 baud** (IDE: `Tools → Serial Monitor`), with
line ending set to **Newline**. Then type each command and check the reply.

| You type         | You should see                                          |
| ---------------- | ------------------------------------------------------- |
| `PING`           | `PONG`                                                  |
| `VERSION`        | `VERSION 1.1`                                           |
| `STATUS`         | `STATUS L=0 R=0 MODE=STOPPED`                           |
| `SENSOR`         | `SENSOR F=-1 L=-1 R=-1 B=-1` until sensors are wired    |
| `MOVE L=1 R=1`   | `ACK MOVE L=1 R=1` (then `STATUS` shows `MODE=RUNNING`) |
| `STOP`           | `ACK STOP`                                              |
| `MOVE L=300 R=0` | `ERR RANGE invalid`                                     |
| `XYZ`            | `ERR UNKNOWN invalid`                                   |
| `ENV`            | `ENV T=-1 H=-1` (until the DHT11 reads cleanly)         |
| `GAS`            | `GAS RAW=-1` (**no pin assigned** — the shipped state)  |
| `LCD MODE IDLE   | ready`                                                  | `ACK LCD` (check the display, if connected) |
| `BUZZ 1200 150`  | `ACK BUZZ 1200`, then ~150 ms of tone                   |
| `BUZZ 99`        | `ERR RANGE invalid` (minimum is 20 Hz)                  |

The very first line after opening the monitor is `AMR FW READY v1.1` (the boot
banner). That is expected; the Pi's read loop tolerates it.

### Watchdog check

Send one command, then **wait more than 1 second** without sending anything.

**Pass:** the firmware prints `WATCHDOG TRIGGERED` once, and `STATUS` now shows
`MODE=WATCHDOG`. Any subsequent valid command clears it.

---

## 6. Firmware bring-up tests (from the Pi or any serial host)

These mirror Stage 1–3 of [`hardware.md`](hardware.md). Run them from the Pi
once the link is up.

```bash
python3 - <<'PY'
import serial, time
port = "/dev/ttyACM0"          # <-- your port
s = serial.Serial(port, 9600, timeout=1)
time.sleep(2)                  # the UNO resets when the port opens
s.reset_input_buffer()

def send(cmd):
    s.write((cmd + "\n").encode())
    return s.readline().decode(errors="replace").strip()

# 1. Link
assert send("PING") == "PONG", "no PONG — check port/baud/cable"
assert send("VERSION").startswith("VERSION"), "no VERSION"
print("link OK")

# 2. Motion (wheels OFF the ground)
for cmd in ["MOVE L=1 R=1", "STOP", "MOVE L=-1 R=1", "STOP"]:
    print(f"{cmd:16} -> {send(cmd)}")
print("motors exercised")

# 3. Sensors (only after ULTRASONIC_ENABLED = 1 and pins set)
print(send("SENSOR"))
s.close()
PY
```

**Pass:** `link OK`, an `ACK` for each motion command, and a `SENSOR` line.

---

## 7. Rebuilding after a pin or flag change

When you change a pin in `motor_control.h` / `ultrasonic.h`, or flip
`MOTOR_PWM_ENABLED` / `ULTRASONIC_ENABLED`:

1. Edit the header.
2. **Mirror the pin change in `config/robot.yaml`** so the Pi and firmware agree.
3. Recompile and re-upload (§3–§4).
4. Re-run §5–§6.

The protocol itself is versioned: if you change any command/response, bump
`PROTOCOL_VERSION` in `protocol.h` **and** update
[`serial_protocol.md`](serial_protocol.md) and the Pi's
`amr/communication/protocol.py` in the same commit.

---

## 8. Common issues

| Symptom                                    | Cause / fix                                                                                                  |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| `avrdude: programmer is not responding`    | Wrong board/port, or a charge-only cable. Try another cable and port.                                        |
| Port disappears right after upload         | Normal — the UNO resets. Reopen the monitor.                                                                 |
| Compile error: `Arduino.h` not found       | The sketch was opened as a single file; open the whole folder in the IDE.                                    |
| `PONG` never arrives from the Pi           | Baud mismatch (9600), or the port is held by another program.                                                |
| Garbage characters                         | Wrong baud, or the monitor's line-ending is not Newline.                                                     |
| Motors don't move though `ACK` is returned | ENA/ENB jumpers still fitted, no motor battery, or no common ground — see [`hardware.md`](hardware.md) §4.1. |
| `ERR RANGE` for `MOVE L=1 R=1`             | You are not running this firmware (legacy build?). Re-flash.                                                 |
| Watchdog fires while you are testing       | You paused > 1 s. Send a command to keep it fed.                                                             |
| `SENSOR` always `-1`                       | `ULTRASONIC_ENABLED` is still `0`, or the sensors are unwired.                                               |

---

**See also:** [`hardware.md`](hardware.md) (wiring + the full bring-up order) ·
[`setup_raspberry_pi.md`](setup_raspberry_pi.md) ·
[`serial_protocol.md`](serial_protocol.md)
