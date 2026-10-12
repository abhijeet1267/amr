# Camera monitoring (C8)

> **REAL CAMERA HARDWARE TESTED: YES (2026-10-13).**
> Verified on the real robot: Raspberry Pi 5 + Camera Module v2 (`imx219`),
> picamera2 0.3.37. `GET /camera/frame` returned a live **1280×720 PNG**
> (0.8–1.2 MB) with `status: LIVE`, `backend: picamera2`, no error.
> Image quality, latency and frame rate are still **not** measured — only that
> frames are acquired and served.
>
> Getting there fixed three real defects that had never been caught because no
> test could see them (see §2a).

C8 adds the camera layer beneath C5's vision pipeline. It deliberately does
**not** replace `amr/camera/camera_manager.py`, the C5 vision contract, or the
C7 web server — it supplies a stable frame abstraction those can sit on.

---

## 1. Architecture

```
CameraSource (protocol)                    amr/camera/frame.py
    │
    ├── SimulatedCameraSource      deterministic PNG, stdlib only
    ├── RaspberryPiCameraSource    picamera2 → libcamera-still → V4L2
    └── CameraManager / MockCamera (pre-existing, unchanged contract)
                    ↓
              CameraFrame  (frozen dataclass)
                    ↓
         AMR runtime / telemetry collector
                    ↓
    GET /camera/status   GET /camera/frame   GET /telemetry
                    ↓
              /dashboard camera panel
```

The camera is a **sensor**, not an actuator. It reads frames and publishes
metadata; it never writes to the controller, changes robot mode, or influences
safety, navigation, or hazards.

## 1a. Three defects found only on real hardware

All three produced the same misleading symptom — _"capture failed … failed to
acquire camera"_ — on a camera that was working perfectly. `rpicam-still` alone
captured a 744 KB JPEG, and no other process held the device.

| #   | Defect                                          | Effect                                                                                                                                                                                                             |
| --- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | `configure(main={...})` was passed to picamera2 | `Picamera2.configure` takes a single `camera_config` argument and has **no** `main=` keyword. Every start raised `TypeError`, so picamera2 never opened and the code silently fell through to the CLI.             |
| 2   | The failure path called `library.close()`       | `library` is the Picamera2 **class**, not the instance. It neither released the device nor raised, so the half-open handle kept the ISP pipeline and the CLI fallback then failed with `failed to acquire camera`. |
| 3   | picamera2 was invisible to the venv             | `picamera2` ships as an apt package in **system** python; the project venv is isolated (`include-system-site-packages = false`), so the app's interpreter could not import it at all.                              |

The fix: build the config with `create_still_configuration(main=...)`, close the
**instance** on failure, and set `include-system-site-packages = true` in
`raspberry_pi/.venv/pyvenv.cfg` so the venv sees the apt-provided `picamera2`.

**Why the suite missed it:** the test double's `configure(**kwargs)` accepted
`main=`, so a call that is a `TypeError` on real hardware passed every test. The
double now mirrors the real signature.

### Serial startup (same class of bug)

Opening the port toggles DTR, which **resets an Arduino UNO**. The board spends
~2 s in its bootloader, so a `PING` sent immediately after opening got no reply
and the app aborted with _"controller not responding to PING"_. Measured on the
UNO: immediate PING → nothing; after a 2 s settle → `PONG`. The transport now
settles after opening and `RobotManager.start()` retries the ping
(`serial.startup_ping_attempts` / `startup_ping_interval_s`).

---

## 2. The `CameraFrame` contract

`amr.camera.frame.CameraFrame` is a frozen dataclass — immutable and hashable,
so it can be shared across threads without defensive copying.

| Field              | Type            | Notes                                           |
| ------------------ | --------------- | ----------------------------------------------- |
| `timestamp`        | `float \| None` | Capture time; `None` when unknown               |
| `source`           | `str`           | e.g. `SimulatedCamera`, `RaspberryPiCamera`     |
| `width` / `height` | `int \| None`   | `None` unless genuinely known                   |
| `format`           | `str \| None`   | `png`, `jpeg`, …                                |
| `frame_id`         | `int`           | Monotonic per source; `0` = none yet            |
| `data`             | `bytes \| None` | Encoded bytes, or `None` for status-only frames |
| `status`           | `CameraStatus`  | `LIVE` / `SIMULATION` / `UNAVAILABLE` / `ERROR` |
| `metadata`         | `dict`          | Backend name, reason, device, free-form extras  |

Validation is defensive: non-positive dimensions, malformed timestamps, and
unknown formats are normalised to `None` rather than raising or being clamped
to a plausible-looking number. A broken detector must not be able to invent a
resolution by failing.

`to_dict()` returns **metadata only** — encoded pixels are deliberately never
serialised into telemetry.

## 3. `CameraStatus` and honesty rules

| Status        | Meaning                                       |
| ------------- | --------------------------------------------- |
| `LIVE`        | Real hardware is producing frames             |
| `SIMULATION`  | A simulated / mock source is configured       |
| `UNAVAILABLE` | No camera, not started, or no backend present |
| `ERROR`       | A configured camera failed                    |

The rule the whole layer exists to enforce: **a simulated frame is never
reported as a live Raspberry Pi frame.** A deliberately-configured simulated
camera reports `SIMULATION` even while stopped — `UNAVAILABLE` would hide the
fact that simulation was chosen. `ERROR` is reserved for genuine failures.

> This fixed a real C7 bug: the telemetry collector inferred the source from
> `describe()` keys that the camera never emitted, so a `MockCamera` was
> reported as `source: "LIVE"`.

## 4. Lifecycle

Every source implements `start()` / `read()` / `stop()`.

- **Idempotent** — repeated `start()` or `stop()` is safe and does nothing.
- **Lazy** — no camera package is imported at module import. Verified:
  importing `amr.camera`, `amr.telemetry`, `amr.web`, and `amr.main` pulls in
  **no** `picamera2`, `cv2`, `numpy`, or `RPi`.
- **Non-blocking** — a background thread is never started. `read()` is a
  bounded, on-demand call, so the camera cannot stall the control loop.
- **Fail-safe** — a missing library, missing device, or init error yields
  `UNAVAILABLE`/`ERROR` with a reason in `metadata`; the runtime keeps running.

## 5. Simulation

`SimulatedCameraSource` generates a real, correctly-sized PNG using only the
standard library (`zlib` + `struct`) — no OpenCV, no NumPy, no Pillow.

- Deterministic: the same `frame_id` and size always produce byte-identical
  output, so tests never flake.
- Advertised dimensions are real. A `640x480` source produces a genuine
  `640x480` image, not a 1×1 upscaled placeholder.
- The frame is a **test pattern** — a grid, a centre crosshair, corner ticks and
  a marker that steps across with the frame counter — not a flat colour. A solid
  frame is indistinguishable from a preview that failed to load, so an operator
  could not tell a working simulated feed from a broken panel. Consecutive
  frames are always visibly different, which is what shows the feed is live.
  It is still not a camera, and the status stays `SIMULATION`.

## 6. Raspberry Pi backend

`RaspberryPiCameraSource` probes in preference order:

1. **`picamera2`** — the modern `rpicam` stack on current Raspberry Pi OS.
2. **`libcamera-still`** — the legacy `libcamera` CLI.
3. **V4L2** — a `/dev/video*` fallback.

Each import is attempted lazily inside a guarded block. Any failure downgrades
to the next candidate and records the reason. Nothing is initialised until
`start()` is called.

> **On the venv:** `picamera2` is an **apt** package (libcamera bindings), not a
> pip one — it cannot be installed into an isolated venv. `pi_quickstart.sh`
> runs the stack from `raspberry_pi/.venv`, so that venv must have
> `include-system-site-packages = true` for picamera2 to be importable. Without
> it the source silently falls back to the CLI, whose 5 s timeout then reports a
> capture failure. Verified on the Pi: with the flag set, `backend` is
> `picamera2` and `GET /camera/frame` returns a 1280×720 PNG.

## 7. HTTP surface (read-only)

| Route                | Returns                                          |
| -------------------- | ------------------------------------------------ |
| `GET /camera/status` | JSON status/metadata — never pixels              |
| `GET /camera/frame`  | The latest encoded frame, `503` when unavailable |
| `GET /image`         | The same frame, for the legacy dashboard preview |
| `GET /telemetry`     | The C7 snapshot including a `camera` section     |
| `GET /dashboard`     | The dashboard with the camera panel              |

Both frame routes serve the **same** cached frame through the same code path,
and each sends the content type that matches the bytes — the C8 sources emit
PNG, the legacy `CameraManager` emits JPEG. `/image` used to call
`capture_jpeg()` directly, which C8 sources do not implement: it raised
`AttributeError` and returned an empty reply (not even a `503`) for the
simulated source and for a real Pi camera alike.

These are `GET`-only. There is no `POST` path from the browser to camera
hardware, GPIO, or motors. A missing or broken camera yields `503` or an
`ERROR` status while `/telemetry`, `/health`, and `/dashboard` keep serving.

## 8. Performance

- **Latest frame only.** No history buffer, so repeated polling cannot grow
  memory.
- **Small telemetry.** A snapshot carries status and dimensions, never encoded
  pixels.
- **No capture in the collector.** Telemetry reads _status_; it never triggers
  a capture, so a slow camera cannot delay the control loop.
- Streaming (MJPEG) is intentionally deferred — a polling dashboard plus the
  single-frame endpoint meets the current need without a background thread or
  a media server.

## 9. Known limitations

- **Camera acquisition IS validated** on a Pi 5 + imx219 (2026-10-13): frames
  are acquired via picamera2 and served as 1280×720 PNG. What is **not**
  measured is image quality, latency, frame rate, or long-run stability.
- No continuous video stream; single-frame retrieval only. Each `read()` calls
  `capture_array()`, so the served frame rate is whatever the polling gives.
- **The DHT11 does not read** (`ENV T=-1 H=-1`). A bare 4-pin sensor needs a
  ~10 kΩ pull-up between VCC and DATA; the internal pull-up is usually too
  weak. Telemetry-only, so nothing is blocked.
- No C5 `VisionDetector` is attached to real frames yet — that integration
  (and any ML model) is a later milestone.
- Bounding-box overlays are supported by the metadata shape but not rendered;
  that is C13.

---

**Source:** `raspberry_pi/amr/camera/frame.py` ·
**Tests:** `raspberry_pi/tests/test_camera_frame.py` (60), camera cases in
`test_telemetry.py` and `test_web_server.py`
