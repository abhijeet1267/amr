# Deploy the AMR — the complete step-by-step checklist

**Direct answer to "do I need to upload code to the Raspberry Pi?" — yes, but  
only the Python control stack. Here is exactly what goes where.**

| Where              | What runs there                                           | How it gets there                               |
| ------------------ | --------------------------------------------------------- | ----------------------------------------------- |
| **Raspberry Pi**   | the Python control stack (`raspberry_pi/amr`) + `config/` | copied from your computer — **Part A**          |
| **Arduino UNO**    | the firmware (`firmware/arduino/amr_controller`)          | flashed over USB — **Part B**                   |
| **Phone / laptop** | the app (the APK, or the Pi's own console in a browser)   | installed / opened — **not** uploaded to the Pi |

You do **not** upload the app to the Pi. The Pi runs its own web console; the  
phone app connects to the Pi over Wi-Fi.

> **Nothing here has been run on real hardware by this repository.** Every step  
> has a validation so you can confirm it worked on *your* hardware.

---

## Part 0 — Prove the app and camera work first (no Arduino needed)

You do **not** need the Arduino, motors or sensors to get the app working. The
stack has a **mock mode** that runs the whole robot in-process, so you can verify
the network link, the console, the app and the camera on the Pi alone.

On the Pi:

```bash
cd ~/amr
./tools/pi_quickstart.sh
```

It finds a Python that can run the stack, checks the camera, and starts the
console in mock mode. It uses **no sudo**, touches no GPIO, and installs nothing
system-wide. Ctrl-C stops it, and it is safe to re-run.

### Stopping it, and starting it again

The console runs in the **foreground**, so your shell prompt does not come back
while it is up. That is the normal, working state — not a hang.

```bash
# stop it: press Ctrl-C in the terminal that is running it.
# if it was started in the background instead:
pkill -f "amr.main" && echo "stopped"

# check whether anything is still listening on the port:
ss -ltnp 2>/dev/null | grep 8080 || echo "port 8080 is free"

# start it again (same one command — it is idempotent):
cd ~/amr && ./tools/pi_quickstart.sh
```

### Stale console holding the port

`pi_quickstart.sh` now handles this itself: before starting, it checks the port
and, if the holder is another `amr.main`, stops it and says so — because that
process is serving the **old** code, so leaving it up means the new build never
starts and the console keeps looking out of date.

It deliberately does **not** kill a process it cannot prove is this app. If an
unrelated program holds the port it refuses and tells you how to inspect it or
pick another port:

```bash
PORT=8081 ./tools/pi_quickstart.sh
```

To check and stop it by hand:

```bash
sudo ss -ltnp | grep ':8080'      # shows which process owns the port
pkill -f "amr.main" && echo "stopped"
sudo ss -ltnp | grep ':8080' || echo "port 8080 is free"
```

If starting it fails with **`OSError: [Errno 98] Address already in use`**, an
earlier copy is still running and holding the port. It is serving the *old* code,
so the console will look out of date until it is replaced:

```bash
sudo ss -ltnp | grep ':8080'      # shows which process owns the port
pkill -f "amr.main"               # stop every copy of the stack
sudo ss -ltnp | grep ':8080' || echo "port 8080 is free"
cd ~/amr && ./tools/pi_quickstart.sh
```

If you pick up new code with `git pull`, always stop the old process first —
otherwise the port is still taken and the new code never starts.

To pick up new code before starting, pull first:

```bash
cd ~/amr
rm -f .git/index.lock          # only if a previous pull was interrupted
git pull
./tools/pi_quickstart.sh
```

Then, from another machine on the same network:

| Want | Use | Why |
| --- | --- | --- |
| Drive/monitor from a phone | the **Android APK** | native apps are not subject to browser CORS |
| Use it from a computer | the Pi's own console: `http://<pi-ip>:8080/command-center` | served by the Pi itself, so no cross-origin issue |
| Preview the app UI | `dist/amr-controller-web/` | **cannot** drive the robot — the server sends no CORS headers |

Enter the Pi's IP and port `8080` in the app's setup wizard.

### What mock mode means

`--mock` runs the controller in-process. Commands are accepted and telemetry is
generated, but **nothing is sent to hardware**. That is exactly what you want
while the robot is unbuilt: it proves the app, the network and the camera work
before any wiring is involved.

It also means the **camera** is simulated — `--mock` picks the simulated source,
so the Camera panel shows a generated test pattern, not your lens. That is
deliberate, but the two halves of the stack are built at different times, so it
is often wrong.

### Using the real camera while the controller is still mocked

If the Pi camera is mounted and working but the Arduino is still in its box, ask
for the real camera explicitly:

```bash
cd ~/amr/raspberry_pi
python3 -m amr.main --mock --web --camera real
```

`--camera real` uses the hardware camera under `--mock`; `--camera sim` forces
the test pattern; `--camera auto` (the default) follows `--mock`. The panel's
status still reports honestly what answered — `LIVE` for real frames,
`UNAVAILABLE` with a reason if nothing did.

Before blaming the software, prove the hardware directly:

```bash
rpicam-hello --list-cameras                 # is the sensor even seen?
rpicam-still -n -t 500 -o /tmp/test.jpg     # does it capture?
```

If `--list-cameras` prints nothing, it is physical: the ribbon (the Pi 5 uses a
**22-pin mini-CSI** connector, so a Pi 4 ribbon will not fit), the latch, or the
connector. No software change will help.

### Only install what you need

The stack's **only** dependency for mock mode is **PyYAML**, which Raspberry Pi
OS already ships as `python3-yaml`. `pyserial` is needed only once the Arduino
is attached (`pip install -e ".[serial]"` in a venv) — running without `--mock`
requires it, and also requires a controller that actually answers.

It does **not** use FastAPI, uvicorn, websockets or starlette. Installing those
system-wide with `pip install --break-system-packages` is unnecessary and
pollutes the system Python on Raspberry Pi OS.

---

## Part A — Raspberry Pi

### A1. Prepare the Pi

1. Flash **Raspberry Pi OS (64-bit, Bookworm)** with Raspberry Pi Imager. In the  
   Imager's settings, enable **SSH** and set your **Wi-Fi**.
2. Boot it, then update and reboot:
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo reboot
   ```
3. Note the Pi's address — you will need it for everything else:
   ```bash
   hostname -I          # e.g. 192.168.1.42
   ```

Full detail: [`setup_raspberry_pi.md`](setup_raspberry_pi.md) §1.

### A2. Get the code onto the Pi  ← the step people miss

The stack needs **two folders side by side**: `raspberry_pi/` and `config/`  
(the config loader resolves `config/` from the repository root, so they must  
stay siblings). `tools/` is optional but useful.

**Option 1 — copy from your computer (recommended).** On your **computer**, from  
the project root:

```bash
# put the Pi's address here
PI=pi@192.168.1.42

ssh "$PI" 'mkdir -p ~/amr'
rsync -av --exclude '.venv' --exclude '__pycache__' \
      raspberry_pi/ "$PI":~/amr/raspberry_pi/
rsync -av --exclude '.venv' --exclude '__pycache__' \
      config/       "$PI":~/amr/config/
rsync -av tools/       "$PI":~/amr/tools/     # optional: health_check.sh
```

If you do not have `rsync`, `scp` works the same way:

```bash
scp -r raspberry_pi config tools "$PI":~/amr/
```

> Exclude `.venv` (it was built for a different machine) and `__pycache__`.

**Option 2 — `git clone` on the Pi.**

```bash
git clone https://github.com/abhijeet1267/amr.git ~/amr
```

> ⚠️ **This only gives you *committed* code.** If you have local changes that  
> are not pushed, they will **not** be on the Pi. Use Option 1 for those.

**Option 3 — USB stick.** Copy `raspberry_pi/`, `config/` and `tools/` onto a  
USB stick, plug it into the Pi, and copy them into `~/amr/`.

**Validation** — on the Pi:

```bash
ls ~/amr                # expect: config  raspberry_pi  tools
ls ~/amr/raspberry_pi   # expect: amr  pyproject.toml  tests
```

### A3. Install the Python environment

```bash
cd ~/amr/raspberry_pi
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[serial]"     # runtime + pyserial (needed for the real link)
```

**Validation:**

```bash
python -c "import serial, yaml; print('pyserial', serial.__version__)"
```

If `import serial` fails, you installed the core extras only — re-run with  
`".[serial]"`.

### A4. Find the serial port and fix permissions

Plug the Arduino into the Pi over USB, then:

```bash
ls /dev/ttyACM* /dev/ttyUSB*     # which one appeared?
sudo usermod -aG dialout "$USER" # then log out and back in
```

If the port vanishes a few seconds after you open it, `ModemManager` is  
grabbing it — the udev rule is in  
[`setup_raspberry_pi.md`](setup_raspberry_pi.md) §3.3.

### A5. Camera (optional)

```bash
sudo apt install -y libcamera-tools python3-picamera2
libcamera-still -n -t 200 -o /tmp/frame.jpg && file /tmp/frame.jpg
```

If that produces a JPEG, the camera is good. The app works without one.

### A6. Run the control stack

```bash
cd ~/amr/raspberry_pi
source .venv/bin/activate
python -m amr.main --web --port 8080
```

It prints `AMR web control: http://0.0.0.0:8080`. Leave it running.

**Validation:**

```bash
curl -s http://localhost:8080/health     # 200 + JSON
curl -s http://localhost:8080/status     # "connected": true when the Arduino is on
```

### A7. Start it on boot (optional)

A ready-made `systemd` unit is in  
[`setup_raspberry_pi.md`](setup_raspberry_pi.md) §5.

---

## Part B — Arduino UNO

1. Install the toolchain (Arduino IDE 2.x, or `arduino-cli` + `arduino:avr`).
2. Open `firmware/arduino/amr_controller/`, select board **Arduino Uno** and the  
   right port, then **Upload**.
3. Verify over the serial monitor at **9600 baud**:
   | Type      | Expect                        |
   | --------- | ----------------------------- |
   | `PING`    | `PONG`                        |
   | `VERSION` | `VERSION 1.0`                 |
   | `STATUS`  | `STATUS L=0 R=0 MODE=STOPPED` |

Full detail: [`setup_arduino.md`](setup_arduino.md).

---

## Part C — Wiring

Wire power, motors, ultrasonic sensors and the camera following  
[`hardware.md`](hardware.md) §4. **Two things to fix before wiring:**

- the rear ultrasonic pins (`D4`/`D5`) **collide** with the left motor pins —  
  move them, and
- `ENB = D8` is **not** a PWM pin on the UNO — move it if you want speed control.

Both are explained, with a clean suggested pin map, in  
[`hardware.md`](hardware.md) §5.

**Non-negotiable:** motors run from the **external battery pack**, never the Pi's  
or the Arduino's 5 V rail, with a **common ground**.

---

## Part D — Verify

1. Run the one-shot health check on the Pi:
   ```bash
   cd ~/amr && ./tools/health_check.sh
   ```
   It checks the serial port, the firmware link (`PING`/`VERSION`/`STATUS`/  
   `SENSOR`), the camera, and the running web stack.
2. Then work through the staged bring-up in  
   [`hardware.md`](hardware.md) §7 — Stage 0 to Stage 7 — with the **wheels off  
   the ground** until the end.

---

## Part E — Use the app

| You want to…                 | Use                                                            | Why                                                                         |
| ---------------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------- |
| Drive the robot from a phone | the **Android APK** (`dist/amr-controller-android.apk`)        | native apps are not subject to browser CORS                                 |
| Drive it from a computer     | the Pi's **own console**: `http://<pi-ip>:8080/command-center` | served by the Pi itself, so no cross-origin issue                           |
| Just preview the app UI      | `dist/amr-controller-web/` in a browser                        | the web build **cannot** drive the robot (the server sends no CORS headers) |

**In the app:** it opens on the setup wizard. Enter the Pi's IP and port `8080`,  
run the connection test, and it will tell you exactly what is wrong if anything  
is. Never use `localhost` on a phone — that means the phone itself.

---

## Part F — Safety rules

1. Motors on the **external pack**; common ground with the Pi and Arduino.
2. First runs **wheels off the ground**, always.
3. Test the E-STOP path before trusting the robot with the wheels down.
4. The web panel has **no authentication** — keep it on your LAN, never expose  
   the port to the internet.
5. Do not enable autonomous missions until the geometry and stop distances are  
   measured ([`hardware.md`](hardware.md) §10).

---

## The whole thing, in order

```
A1  prepare the Pi (OS, SSH, Wi-Fi)              → hostname -I
A2  copy raspberry_pi/ + config/ + tools/ to ~/amr/    ← the step people miss
A3  python3 -m venv .venv && pip install -e ".[serial]"
A4  find /dev/ttyACM* + add yourself to dialout
A5  camera: libcamera-still test                  (optional)
B   flash the Arduino firmware                    → PING → PONG
C   wire power / motors / ultrasonic / camera     → fix the 2 pin conflicts
D   ./tools/health_check.sh  + hardware.md §7 staged bring-up
A6  python -m amr.main --web --port 8080
E   open the app / the Pi console, enter the Pi's IP, connect
F   safety rules
```

**See also:** [`WIRING_CHECK.md`](WIRING_CHECK.md) (photos to take + what to
check before powering up) ·  
[`hardware.md`](hardware.md) (wiring + bring-up) ·  
[`setup_arduino.md`](setup_arduino.md) · [`setup_raspberry_pi.md`](setup_raspberry_pi.md) ·  
[`../tools/health_check.sh`](../tools/health_check.sh)
