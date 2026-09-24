# Telemetry & Dashboard (C7)

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
