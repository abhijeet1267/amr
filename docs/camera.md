# Camera monitoring (C8)

> **REAL CAMERA HARDWARE TESTED: NO.**
> No Raspberry Pi camera was available when this was written. Every claim below
> is backed by the deterministic simulated camera or by fault-injected tests
> that stand in for missing hardware. Nothing here is a measurement of real
> camera performance, latency, or image quality.

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

## 2. The `CameraFrame` contract

`amr.camera.frame.CameraFrame` is a frozen dataclass — immutable and hashable,
so it can be shared across threads without defensive copying.

| Field | Type | Notes |
|---|---|---|
| `timestamp` | `float \| None` | Capture time; `None` when unknown |
| `source` | `str` | e.g. `SimulatedCamera`, `RaspberryPiCamera` |
| `width` / `height` | `int \| None` | `None` unless genuinely known |
| `format` | `str \| None` | `png`, `jpeg`, … |
| `frame_id` | `int` | Monotonic per source; `0` = none yet |
| `data` | `bytes \| None` | Encoded bytes, or `None` for status-only frames |
| `status` | `CameraStatus` | `LIVE` / `SIMULATION` / `UNAVAILABLE` / `ERROR` |
| `metadata` | `dict` | Backend name, reason, device, free-form extras |

Validation is defensive: non-positive dimensions, malformed timestamps, and
unknown formats are normalised to `None` rather than raising or being clamped
to a plausible-looking number. A broken detector must not be able to invent a
resolution by failing.

`to_dict()` returns **metadata only** — encoded pixels are deliberately never
serialised into telemetry.

## 3. `CameraStatus` and honesty rules

| Status | Meaning |
|---|---|
| `LIVE` | Real hardware is producing frames |
| `SIMULATION` | A simulated / mock source is configured |
| `UNAVAILABLE` | No camera, not started, or no backend present |
| `ERROR` | A configured camera failed |

The rule the whole layer exists to enforce: **a simulated frame is never
reported as a live Raspberry Pi frame.** A deliberately-configured simulated
camera reports `SIMULATION` even while stopped — `UNAVAILABLE` would hide the
fact that simulation was chosen. `ERROR` is reserved for genuine failures.

> This fixed a real C7 bug: the telemetry collector inferred the source from
> `describe()` keys that the camera never emitted, so a `MockCamera` was
> reported as `source: "LIVE"`.

## 4. Lifecycle

Every source implements `start()` / `read()` / `stop()`.

* **Idempotent** — repeated `start()` or `stop()` is safe and does nothing.
* **Lazy** — no camera package is imported at module import. Verified:
  importing `amr.camera`, `amr.telemetry`, `amr.web`, and `amr.main` pulls in
  **no** `picamera2`, `cv2`, `numpy`, or `RPi`.
* **Non-blocking** — a background thread is never started. `read()` is a
  bounded, on-demand call, so the camera cannot stall the control loop.
* **Fail-safe** — a missing library, missing device, or init error yields
  `UNAVAILABLE`/`ERROR` with a reason in `metadata`; the runtime keeps running.

## 5. Simulation

`SimulatedCameraSource` generates a real, correctly-sized PNG using only the
standard library (`zlib` + `struct`) — no OpenCV, no NumPy, no Pillow.

* Deterministic: the same configuration always produces byte-identical output,
  so tests never flake.
* Advertised dimensions are real. A `640x480` source produces a genuine
  `640x480` image, not a 1×1 upscaled placeholder.


## 6. Raspberry Pi backend

`RaspberryPiCameraSource` probes in preference order:

1. **`picamera2`** — the modern `rpicam` stack on current Raspberry Pi OS.
2. **`libcamera-still`** — the legacy `libcamera` CLI.
3. **V4L2** — a `/dev/video*` fallback.

Each import is attempted lazily inside a guarded block. Any failure downgrades
to the next candidate and records the reason. Nothing is initialised until
`start()` is called.

## 7. HTTP surface (read-only)

| Route | Returns |
|---|---|
| `GET /camera/status` | JSON status/metadata — never pixels |
| `GET /camera/frame` | The latest encoded frame, `503` when unavailable |
| `GET /telemetry` | The C7 snapshot including a `camera` section |
| `GET /dashboard` | The dashboard with the camera panel |

These are `GET`-only. There is no `POST` path from the browser to camera
hardware, GPIO, or motors. A missing or broken camera yields `503` or an
`ERROR` status while `/telemetry`, `/health`, and `/dashboard` keep serving.

## 8. Performance

* **Latest frame only.** No history buffer, so repeated polling cannot grow
  memory.
* **Small telemetry.** A snapshot carries status and dimensions, never encoded
  pixels.
* **No capture in the collector.** Telemetry reads *status*; it never triggers
  a capture, so a slow camera cannot delay the control loop.
* Streaming (MJPEG) is intentionally deferred — a polling dashboard plus the
  single-frame endpoint meets the current need without a background thread or
  a media server.

## 9. Known limitations

* **No real hardware validation.** The Pi backend is written against the
  documented APIs but has never been run on a Pi.
* No continuous video stream; single-frame retrieval only.
* No C5 `VisionDetector` is attached to real frames yet — that integration
  (and any ML model) is a later milestone.
* Bounding-box overlays are supported by the metadata shape but not rendered;
  that is C13.

---

**Source:** `raspberry_pi/amr/camera/frame.py` ·
**Tests:** `raspberry_pi/tests/test_camera_frame.py` (46), camera cases in
`test_telemetry.py` and `test_web_server.py`
