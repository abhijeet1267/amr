# Telemetry & Dashboard (C7)

> **C8 adds a camera panel.** See the [Camera monitoring (C8)](#camera-monitoring-c8)
> section at the end of this document for the `CameraFrame` contract, the
> simulated and Raspberry Pi backends, and `/camera/status` / `/camera/frame`.

Status: **Implemented, unit-tested, opt-in.** Read-only. No hardware required.

C7 adds a **telemetry layer** over the existing AMR runtime plus a read-only
HTTP API and a minimal dashboard. It is a *visualisation* layer: it observes
the runtime, it never drives it.

```
AMR Runtime (existing subsystems)
   RobotManager / SafetyManager / HazardManager / Navigator / Warehouse / Camera
        ↓  (pure reads — no tick(), no writes, no new command path)
TelemetryCollector  →  TelemetrySnapshot  (frozen dataclasses)
        ↓
GET /telemetry   GET /health   GET /dashboard
        ↓
Web UI (single self-contained HTML page, stdlib only)
```

## Safety boundary (the important part)

The dashboard has **no path to the actuators.** Specifically:

* `TelemetryCollector` only *reads* public attributes of existing managers.
  It never calls `tick()`, `request_mode()`, `send()`, or any write method.
  This is asserted by a test that spies on both `tick()` and the serial
  transport's written bytes.
* The collector holds no Arduino / GPIO / PWM handle and imports no hardware
  driver.
* The pre-existing C2 `/command` endpoint remains the **only** control path, and
  it is unchanged by C7. Any future command feature must be a separate,
  authenticated, safety-reviewed layer — never a field on a telemetry snapshot.

## Reuse, not duplication

Every value in a snapshot comes from an existing source; the collector defines
no shadow copy of runtime state.

| Telemetry field | Source of truth |
|---|---|
| `position`, `orientation`, `velocity`, `mode`, `emergency_stop` | `RobotState.to_dict()` |
| `safety.action/state/reasons` | `SafetyManager.last_decision` |
| `hazards.*` | `HazardManager.snapshot()` (C2) |
| `navigation.*` | `Navigator` (state, current goal, plan) |
| `mission.*` | `WarehouseTaskManager.status()` |
| `camera.*` | `CameraManager.describe()` |
| `sensors.*` | ultrasonic readings already present in `RobotState` |
| `system.*` | collector start time, `amr.main` version string |

## Honesty rule: source, not a fabricated number

Every section carries a `source` tag, and the snapshot carries a top-level
`simulated` boolean:

| `DataSource` | Meaning |
|---|---|
| `LIVE` | read from a real, running subsystem |
| `SIMULATION` | read from a mock / simulated subsystem |
| `UNAVAILABLE` | no such measurement exists in this build |

If a measurement does not exist, the field is `null` and the section's source
is `UNAVAILABLE`. The collector **never invents** a value:

* no battery pack is wired up, so `battery.percentage` is `null`, not `78`.
* no LiDAR, so there is no LiDAR field at all.
* no capture pipeline, so `camera.fps` is `null` (a comment in the code notes
  that FPS is not measurable without one).
* `battery.voltage` and `battery.charging` are `null` unless a source provides
  them.

This is why the dashboard prints `NOT AVAILABLE` / `SIMULATION` badges rather
than a number for those rows.

## The contract

`amr/telemetry/types.py` defines frozen dataclasses; `schema_version` is part of
every snapshot so a consumer can detect a breaking change.

| Class | Purpose |
|---|---|
| `DataSource` | the `LIVE` / `SIMULATION` / `UNAVAILABLE` enum |
| `Vector3` | `x`, `y`, `z` (odometry gives `x`,`y`; `z` is `null`) |
| `Orientation` | `yaw` |
| `Velocity` | `linear`, `angular` |
| `NavigationTelemetry` | `state`, `current_goal`, `route`, `progress`, `avoidance` |
| `SafetyTelemetry` | `action`, `state`, `emergency_stop`, `reasons`, hazard overlay |
| `HazardTelemetry` | `state`, `latched`, `active`, `recent`, `events_recorded` |
| `BatteryTelemetry` | `percentage`, `voltage`, `charging` (all nullable) |
| `SensorTelemetry` | ultrasonic `front/left/right/rear_cm` |
| `MissionTelemetry` | `mission_id`, current task, queued/completed/failed |
| `CameraTelemetry` | `status`, `source_name`, `device`, `resolution`, `fps` |
| `SystemTelemetry` | `uptime`, `software_version`, `schema_version`, `robot_id` |
| `TelemetrySnapshot` | the whole document, `timestamp` + `simulated` at top |
| `HealthReport` | liveness/degradation summary for `/health` |

All are `to_dict()`-able and JSON-serialisable; optional fields simply
serialise as `null` rather than being omitted.

## API

Added to the **existing** `AMRWebApp` (C2) — no second HTTP server was created.

| Route | Method | Purpose |
|---|---|---|
| `/telemetry` | GET | full `TelemetrySnapshot` |
| `/health` | GET | `HealthReport` — OK / DEGRADED / OFFLINE, plus per-subsystem detail |
| `/dashboard` | GET | the self-contained dashboard HTML page |

`/telemetry` is safe to poll; each request takes a fresh read-only snapshot.

## Files

| Path | Change |
|---|---|
| `amr/telemetry/types.py` | **new** — the frozen telemetry contract |
| `amr/telemetry/collector.py` | **new** — read-only `TelemetryCollector` |
| `amr/telemetry/__init__.py` | **new** — package exports |
| `amr/web/server.py` | `TelemetryCollector` wiring + the 3 routes + dashboard HTML |
| `amr/main.py` | constructs the collector, passes `simulated=args.mock` |

## Tests

* `tests/test_telemetry.py` — 46 tests: schema, missing optional fields,
  serialisation, deterministic snapshots, and the read-only guarantee.
* `tests/test_web_server.py` — 9 added tests for the three new routes.

Full suite after C7: **592 passed, 2 skipped, 0 failed** (537 baseline + 55 new).

## Not in C7 (later milestones)

No live camera stream (C8), no interactive 2D map (C9), no 3D twin (C10), no
mission/hazard panels beyond plain JSON (C11–C13), no recording/replay (C14).
The dashboard here is a deliberately minimal status page, not the full
control-centre UI.

## Reproduce

```bash
cd raspberry_pi
python -m pytest tests/test_telemetry.py tests/test_web_server.py -q
# live smoke, simulation mode, then open the printed URL:
python -m amr.main --mock --web
```

---

# Camera monitoring (C8)

The camera subsystem is **read-only evidence**. It never commands a motor, never
writes to the controller, and never lets a browser reach camera hardware
directly. The only path is:

```
CameraSource ─► CameraFrame ─► TelemetrySnapshot ─► GET /camera/status
    │                                                    │
    └──► VisionDetector (C5) ─► VisionDetection           └──► GET /camera/frame
            └─► VisionHazardSource ─► HazardManager              (visualisation only)
```

> **REAL CAMERA HARDWARE TESTED: NO.** No Raspberry Pi camera, GPIO, libcamera,
> or `picamera2` was used. Every claim below is verified against the mock /
> simulated backends and against a deliberately absent camera stack. The real
> adapter's *unavailable* paths are tested; its *capture* path is not.

## Architecture

One contract, three implementations, in `amr/camera/frame.py`:

| Class | Purpose | Status it reports |
|---|---|---|
| `SimulatedCameraSource` | Deterministic placeholder PNG, stdlib only | `SIMULATION` |
| `RaspberryPiCameraSource` | Real hardware via `picamera2` (lazy import) | `LIVE` / `UNAVAILABLE` / `ERROR` |
| `UnavailableCameraSource` | Explicit "no camera" placeholder | `UNAVAILABLE` |

`CameraStatus` is the honest-state enum: `LIVE`, `SIMULATION`, `UNAVAILABLE`,
`ERROR`. A simulated frame is **never** reported as `LIVE` — the status travels
on the frame itself and is propagated into telemetry, so mislabelling would take
a deliberate code change.

This module is additive. The pre-existing `CameraManager` / `MockCamera` /
`PiCameraBackend` stack is untouched and still works; `frame.py` is the new,
explicit contract for consumers that want frames rather than JPEGs.

## The `CameraFrame` contract

Frozen dataclass. Every optional field is honestly `None` when unknown — never a
fabricated `0` or a default resolution.

| Field | Meaning |
|---|---|
| `timestamp` | Capture time (wall clock) |
| `source` | Backend identity, e.g. `SimulatedCamera` |
| `width` / `height` | Advertised pixel dimensions |
| `format` | `png` / `jpeg` / … |
| `frame_id` | Monotonic counter, increments per capture |
| `data` | Encoded bytes, or `None` when unavailable |
| `status` | `CameraStatus` |
| `metadata` | Free-form, non-safety context (e.g. `"simulated": true`) |

`to_dict()` is the telemetry/web projection and **excludes `data`** — raw pixels
never bloat a snapshot or the `/telemetry` payload. Frames are delivered only via
`GET /camera/frame`.

## Lifecycle

`start()` / `read()` / `stop()`, all idempotent and safe to call repeatedly.
`stop()` releases the underlying camera handle; calling it twice is a no-op. No
camera object is constructed at import time, so `import amr.camera` works on a
machine with no camera stack at all.

## Degradation

A missing camera must never take down the runtime:

| Situation | Reported | Effect on other subsystems |
|---|---|---|
| No `picamera2` installed | `UNAVAILABLE` | None |
| Library present, no hardware | `UNAVAILABLE` | None |
| Camera init raises | `ERROR` | None |
| No camera configured | `UNAVAILABLE` | None |
| Broken camera object | `ERROR` | `/telemetry`, `/health`, `/dashboard` still `200` |

The `picamera2` import is lazy and guarded, so its absence is a normal
condition, not an exception.

## HTTP surface

| Route | Method | Returns |
|---|---|---|
| `/camera/status` | GET | Metadata JSON — status, source, dimensions, `has_frame` |
| `/camera/frame` | GET | Latest encoded image bytes, or `503` |
| `/telemetry` | GET | `camera` section of the snapshot (metadata only) |
| `/dashboard` | GET | Camera panel rendering status + the single frame |

Both camera routes are **GET-only**; there is no `POST` path to camera
hardware. The dashboard fetches the frame with `cache: "no-store"` and handles
capture failure independently, so a broken camera cannot blank the dashboard.

## Telemetry

```json
{"status": "SIMULATION", "source": "SIMULATION", "source_name": "SimulatedCamera",
 "width": 640, "height": 480, "format": "png", "frame_id": 7,
 "timestamp": 1790276821.375524, "has_frame": true, "error": null}
```

With no camera, `width` / `height` / `format` are `null` and `status` is
`UNAVAILABLE`. No hardware measurement is ever invented.

### Honesty bug fixed

The C7 collector read `mock` / `backend` / `source` keys that
`CameraManager.describe()` never emitted, so a `MockCamera` was tagged
`"source": "LIVE"` and claimed `1280x720` for a 1×1 frame. The camera projection
now derives status from the frame's own `CameraStatus`, and a regression test
asserts a mock camera is never reported as `LIVE`.

## Performance

- **Latest frame only.** No history buffer; repeated polling cannot grow memory.
- **No background threads.** Capture is pull-based on request, so the camera
  cannot delay the control loop.
- **Bounded work.** Telemetry carries metadata, never pixels.
- **No extra dependencies.** The simulated camera uses only `zlib` / `struct`
  from the standard library — no OpenCV, NumPy, or Pi libraries are imported.

## Known limitations

- The `RaspberryPiCameraSource` capture path is **untested on hardware** (see the
  banner above). It prefers `picamera2`; the older `libcamera-still` / V4L2 path
  remains in `PiCameraBackend` for existing callers.
- Single-frame retrieval only. Continuous MJPEG streaming is deliberately out of
  scope for C8 and would need its own performance budget on a Pi.
- No ML in C8. `CameraFrame` carries the fields a C5 `VisionDetector` needs, but
  no real model is wired; the simulated detector is still the only source of
  `VisionDetection`s.
- Overlay rendering is not implemented. The `bbox` / `class` / `confidence`
  fields a future overlay needs already exist on C5's `VisionDetection`.

## Tests

`tests/test_camera_frame.py` (46) covers the contract, serialization, missing
optional fields, simulation determinism, the hardware adapter's
missing-library / no-hardware / init-failure paths, and lifecycle idempotence.
`tests/test_web_server.py::TestCameraMonitoringRoutes` (11) and `tests/test_telemetry.py::TestCameraTelemetry*` (17) covers the routes
over real HTTP. No test requires a Pi, camera hardware, GPIO, or libcamera.

Full suite after C8: **660 passed, 2 skipped, 0 failed** (592 at C7 + 68 new).

