# Raspberry Pi setup — OS, serial link, camera, and running the stack

Everything the Pi side needs: from a fresh OS to the control stack talking to a  
real Arduino and camera. This is Stage 4–5 of [`hardware.md`](hardware.md), and  
it fills in the "prefer discovery" note in `config/serial.yaml`.

> **No part of this has been run against real hardware by this repository.**  
> The commands below are the documented, standard ones; the validation steps tell  
> you how to confirm each actually worked on *your* Pi.

---

## 1. Base OS

1. Flash **Raspberry Pi OS (64-bit, Bookworm)** with Raspberry Pi Imager.  
   In the Imager's settings, enable SSH and set your Wi-Fi — headless is easier.
2. Boot, then update:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

1. Confirm Python and the header tooling:

```bash
python3 --version          # 3.10–3.12 matches the CI matrix
```

---

## 2. The Python environment

> **The code must be on the Pi first.** This section assumes `raspberry_pi/` and  
> `config/` are already there. To copy them from your computer (they must stay  
> sibling folders), see [`DEPLOY.md`](DEPLOY.md) §A2.

The stack needs `PyYAML` always and `pyserial` for the real link.

```bash
cd raspberry_pi
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[serial]"     # runtime + pyserial
# or, to also get pytest/ruff for the test suite:
pip install -e ".[dev]"
```

**Validation:**

```bash
python -c "import serial, yaml; print('pyserial', serial.__version__)"
python -m pytest               # the mock suite must still be green
```

If `import serial` fails you installed the core extras only — re-run with  
`".[serial]"` or `".[dev]"`.

---

## 3. The serial link to the Arduino

### 3.1 Discover the port (do not hard-code it)

The device node can change between boots and machines (`/dev/ttyACM0` today,  
`/dev/ttyUSB0` tomorrow). The shipped `config/serial.yaml` keeps  
`/dev/ttyACM0` only as a **fallback** — prefer discovery:

```bash
# What is attached?
ls -l /dev/serial/by-id/ 2>/dev/null
ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null

# Which one is the Arduino? (unplug, list, replug, list again — the new one)
```

The repo's own helper does this and more:

```bash
tools/health_check.sh            # from the repository root
```

If your port differs, set it in `config/serial.yaml`:

```yaml
serial:
  port: "/dev/ttyACM0"   # change to your discovered port
  baudrate: 9600
```

### 3.2 Permissions

Serial ports are owned by `dialout`. If you see **`Permission denied`**:

```bash
sudo usermod -aG dialout "$USER"
# then log out and back in (or: newgrp dialout)
groups | grep dialout
```

### 3.3 Stop ModemManager from grabbing the port (common gotcha)

On many distros `ModemManager` probes every new serial device, which can make the  
port **vanish a few seconds after you open it**. Give the Arduino a stable,  
ignored identity with a udev rule:

```bash
sudo tee /etc/udev/rules.d/99-amr-arduino.rules >/dev/null <<'EOF'
# Arduino UNO / USB-serial: stable symlink + keep ModemManager away
SUBSYSTEM=="tty", ATTRS{idVendor}=="2341", SYMLINK+="amr_arduino", ENV{ID_MM_DEVICE_IGNORE}="1"
EOF

sudo udevadm control --reload-rules && sudo udevadm trigger
```

Now `/dev/amr_arduino` is a stable name you can put in `serial.yaml`. (The  
`idVendor` for a genuine UNO is `2341`; clone boards use `1a86` (CH340) or  
`0403` (FTDI) — check with `lsusb` and use yours.)

**Validation:** open the port, wait 5 s, and confirm it is still there:

```bash
python - <<'PY'
import serial, time
s = serial.Serial("/dev/amr_arduino", 9600, timeout=1)
time.sleep(2); s.reset_input_buffer()
s.write(b"PING\n")
print(s.readline().decode(errors="replace").strip())   # expect: PONG
s.close()
PY
```

---

## 4. The camera

The camera is a **CSI** device, not USB. Two backends exist in the code:

- `device: "pi"` → `RaspberryPiCameraSource` prefers **`picamera2`**, then  
  **`libcamera-still`**.
- `device: "v4l2"` → OpenCV on `/dev/video0` (needs `opencv-python` + `numpy`).

The shipped `config/robot.yaml` uses `device: "pi"`, `resolution: "1280x720"`.

### 4.1 Enable and test the camera

```bash
# Bookworm: libcamera is the default stack. Install the tools + Python bindings:
sudo apt install -y libcamera-tools python3-picamera2

# One-shot capture to prove the hardware works
libcamera-still -n -t 200 -o /tmp/frame.jpg
file /tmp/frame.jpg          # expect: JPEG image data, 1280x720 (or similar)
```

If the tools are missing or the camera is not detected:

```bash
# Older images only — Bookworm enables libcamera by default
sudo raspi-config           # Interface Options → Camera → Enable, then reboot
rpicam-hello --list-cameras # newer name for the detection tool
```

### 4.2 Tell the stack which backend

```yaml
# config/robot.yaml
camera:
  enabled: true
  device: "pi"          # "pi" (libcamera/picamera2) or "v4l2" (OpenCV)
  resolution: "1280x720"
```

**Validation:** start the stack (below) and check the camera reports itself  
honestly:

```bash
curl -s http://localhost:8080/camera/status
# status must be "LIVE" for real hardware — "SIMULATION" means you ran with --mock,
# "UNAVAILABLE" means the backend found no device.
```

> The camera layer's rule is that **a simulated frame is never reported as  
> live**. If you see `SIMULATION`, you passed `--mock`. If you see `UNAVAILABLE`,  
> the backend found no device — re-seat the ribbon and re-test with  
> `libcamera-still`.

---

## 5. Run the stack against real hardware

```bash
cd raspberry_pi && source .venv/bin/activate

# Headless (no camera, no web):
python -m amr.main

# Web control panel + JSON API on the real serial link (NO --mock):
python -m amr.main --web --port 8080
```

The banner prints the URL, e.g. `AMR web control: http://0.0.0.0:8080`.

> `--mission-demo` is **refused without `--mock`** — it commands autonomous  
> motion, so the runtime will not silently start a mission on real hardware.

### Validation

```bash
curl -s http://localhost:8080/health     | head
curl -s http://localhost:8080/status     | head
curl -s http://localhost:8080/telemetry  | head
```

**Pass:** `/health` is 200, `/status` shows `connected: true`, and `/telemetry`  
carries live numbers (not the mock ones). `/camera/status` shows `LIVE` when the  
camera works.

### Run it as a service (optional)

```ini
# /etc/systemd/system/amr.service
[Unit]
Description=AMR control stack
After=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/amr/raspberry_pi
ExecStart=/home/pi/amr/raspberry_pi/.venv/bin/python -m amr.main --web --port 8080
Restart=on-failure
Environment=AMR_LOG_DIR=/var/log/amr

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now amr.service
systemctl status amr.service
journalctl -u amr.service -f
```

> The panel has **no authentication**. Keep it on the LAN; never port-forward it.

---

## 6. Integrating the app (Flutter client)

The client speaks the same HTTP contract as the console. To point it at the real  
robot:

1. Build/run it:

```bash
cd amr_controller
flutter pub get
flutter run -d macos        # or a connected Android device
```

1. On the **Connection** screen, enter the Pi's **IP address** and port:

```
Host: 192.168.1.42      (the Pi's LAN IP — NOT localhost)
Port: 8080
```

1. Tap **Ping**. The badge turns **Connected**; the Dashboard, Map, Camera,  
   Sensors, Telemetry and Heat-map screens then populate from the live robot.

Find the Pi's IP with `hostname -I` on the Pi.

**Validation:** drive from the Teleop screen **with the wheels off the ground**  
the first time; the E-STOP must be reachable (long-press to arm).

> The browser-based console cannot reach the robot **cross-origin**, and that is  
> deliberate: the Python server sends no CORS headers, because granting  
> `Access-Control-Allow-Origin` would let any website an operator visits `POST
> /command` and move the robot. The Flutter client connects directly (not via a  
> browser origin), so it is unaffected.

---

## 7. Logs

The stack writes to `raspberry_pi/logs/amr.log` (5 MB, three rotated backups).  
On a Pi, redirect it off the SD card:

```bash
AMR_LOG_DIR=/var/log/amr python -m amr.main --web
tail -f /var/log/amr/amr.log
```

Motion commands appear as greppable lines:

```
11:49:18 INFO  [amr.robot] COMMAND FORWARD L=100 R=100
```

`GET /health` reports whether logging is actually active — `"active": false`  
means output is being discarded, which is a fault, not a style choice.

---

## 8. Common issues

| Symptom                                          | Cause / fix                                                                     |
| ------------------------------------------------ | ------------------------------------------------------------------------------- |
| `ModuleNotFoundError: No module named 'serial'`  | Core extras only. `pip install -e ".[serial]"` inside the venv.                 |
| `ModuleNotFoundError: No module named 'yaml'`    | The venv is not active, or deps not installed.                                  |
| `Permission denied: '/dev/ttyACM0'`              | Add user to `dialout` (§3.2) and re-login.                                      |
| Port vanishes seconds after opening              | ModemManager — add the udev rule (§3.3).                                        |
| `/status` shows `connected: false`               | Wrong port/baud, or the Arduino is not flashed. Re-run `tools/health_check.sh`. |
| `/camera/status` = `UNAVAILABLE`                 | Ribbon not seated, wrong ribbon, or camera not enabled (§4).                    |
| `/camera/status` = `SIMULATION`                  | You started with `--mock`. Drop the flag.                                       |
| `libcamera-still: not found`                     | `sudo apt install libcamera-tools` (or switch to `device: "v4l2"`).             |
| Undervoltage warnings (`vcgencmd get_throttled`) | Weak PSU. Undervoltage corrupts serial timing — use the official supply.        |
| Can't reach the panel from another device        | Wrong IP, or firewall. Confirm `hostname -I` and that you are on the same LAN.  |

---


**See also:** [`hardware.md`](hardware.md) (wiring + bring-up order) ·  
[`setup_arduino.md`](setup_arduino.md) · [`camera.md`](camera.md) ·  
[`serial_protocol.md`](serial_protocol.md) · [`../tools/health_check.sh`](../tools/health_check.sh)
