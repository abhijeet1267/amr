# Multi-Hazard Safety Layer

A **context-aware** safety layer that aggregates many hazard inputs — gas/smoke
sensors, camera vision, fire/human detection, robot state, navigation state and
robot location — into a single deterministic state:

```
NORMAL  ->  WARNING  ->  SLOW  ->  STOP  ->  EMERGENCY
```

> **Status of the thresholds:** `config/hazard.yaml` is `status: NOT_VERIFIED`
> and `enabled: false`. Every threshold is a *configurable test value*, and the
> example zone is a *placeholder*, not a surveyed layout. Nothing here may be
> treated as a life-safety limit until it has been validated on real sensors in
> the real warehouse and `status` has been set to `VERIFIED`.

---

## Where this fits

The repository already ships three safety layers (see [safety.md](safety.md)).
This is an additional, independent input that sits **alongside Layer 3**:

```
Layer 1  Arduino hardware stop    watchdog + proximity stop      (firmware)
Layer 2  Pi-side state            RobotState                      (amr.robot)
Layer 3  Pi-side policy           SafetyManager: PROCEED/WAIT/STOP (amr.safety)
Layer 3.5 Multi-hazard layer      HazardManager: NORMAL/.../EMERGENCY  <-- this
```

Layer 3 answers *"is the path clear right now?"* from the ultrasonic ring. The
hazard layer answers the wider question *"is the environment safe to operate in
at all?"* — which depends on more than proximity: air quality, a person in the
aisle, a fire, or simply **where the robot is**.

---

## Hard rules

These are load-bearing. Do not weaken them.

1. **Escalate only.** The hazard layer can *tighten* the outcome; it can never
   relax a Layer-3 decision. `RobotManager` takes the worst of both. A hazard
   verdict of `NORMAL` never clears a proximity `STOP`.
2. **Never drive.** It returns a verdict and nothing else. Only `RobotManager`
   may command motion, so all existing gating still applies.
3. **Fail safe.** A source that raises, or that reports no data, produces a
   `WARNING` reading rather than silence. On a safety layer, "the gas sensor is
   not answering" is not the same as "the air is clean".
4. **Deterministic.** No heuristics, no randomness: the same readings always
   produce the same state. This mirrors the Layer-3 design promise.

---

## The five states

| State | Meaning | Motion | Speed |
|---|---|---|---|
| `NORMAL` | No hazard observed | allowed | full |
| `WARNING` | Hazard present, below its stop threshold | allowed | full |
| `SLOW` | Hazard requires reduced speed | allowed | `slow_speed_scale` (default 0.5) |
| `STOP` | Hazard requires an immediate stop | **vetoed** | 0 |
| `EMERGENCY` | Life-safety hazard | **vetoed + latched** | 0 |

`WARNING` is informational: the operator is told, behaviour does not change.
`SLOW` is the "caution" band. `STOP` and `EMERGENCY` both veto motion;
`EMERGENCY` additionally **latches** and needs an operator to clear it.

### How readings map to states

Decision is worst-wins and depends only on `(kind, severity)`:

| Reading | Resulting state |
|---|---|
| any `CRITICAL` reading whose kind is in `emergency_kinds` | `EMERGENCY` (latches) |
| any other `CRITICAL` reading | `STOP` |
| a `WARNING` reading whose kind is in `slow_kinds` | `SLOW` |
| any other `WARNING` reading | `WARNING` |
| only `INFO` readings, or none | `NORMAL` |

Defaults: `emergency_kinds = [FIRE, GAS, SMOKE]`,
`slow_kinds = [GAS, SMOKE, HUMAN, ZONE_BREACH]`. Both are configurable, and an
explicit empty list in YAML deliberately **disables** that band (so `CRITICAL`
then yields `STOP` rather than a latched `EMERGENCY`).

---

## Sources

Every source is a small adapter satisfying one protocol:

```python
class HazardSource(Protocol):
    name: str
    def read(self) -> Tuple[HazardReading, ...]: ...
```

They are **dependency-injected**: none of them touch hardware, a bus or a camera
directly. Each wraps a *callable* supplied by the caller (a GPIO read, a vision
detector, a state getter), which is what makes the whole layer testable with no
robot attached — the same philosophy as `amr/mocks`.

| Source | Input (injected callable) | Kinds |
|---|---|---|
| `GasSensorSource` | `reader() -> float \| None` — concentration in `unit` | `GAS` (or `SMOKE`) |
| `VisionHazardSource` | `detector() -> [(kind, confidence) \| HazardReading]` | `FIRE`, `HUMAN`, … |
| `RobotStateSource` | `state_provider()`, `nav_provider()` | `ROBOT_FAULT` |
| `RestrictedZoneSource` | `pose_provider()` + configured rectangles | `ZONE_BREACH` |

Sources are duck-typed where they read other modules: `RobotStateSource` reads
`connected` / `last_error` / `status` attributes without importing `amr.robot`
or `amr.navigation`, which keeps `amr.hazard` free of import cycles (it is
imported by the robot manager).

`RobotStateSource` reports a lost controller link as `CRITICAL` (motion must
stop), and a stale robot error or a failed/cancelled navigation attempt as
`WARNING`.

### Zones (robot location as context)

`RestrictedZoneSource` raises a reading while the robot is inside a configured
rectangle. This is what makes the layer *context-aware*: the same air reading
means different things in a battery-charging bay than in an open aisle. With no
pose available the source stays silent — **a missing location never invents a
hazard**.

---

## Hazard events (the audit trail)

Every reading above `INFO` is recorded as a `HazardEvent` in a bounded ring
buffer (`max_events`):

* keyed by `kind:source`, so one ongoing gas leak is **one** event that
  *escalates in place* (`WARNING -> CRITICAL`) rather than a new event every
  control-loop tick;
* tagged with the robot's location when one is available (`HazardLocation`:
  `x`, `y`, `theta`, optional `zone`);
* resolved when the reading disappears, recording `cleared_at` / `duration_s`;
* exportable as **JSONL** (one JSON object per line) via `event_log_path`, for a
  future dashboard and spatial hazard visualisation. `read_events(path)` is the
  tolerant read side. Export is best-effort: an unwritable path logs a warning
  and never raises, because a logging failure must not stop the safety loop.

Latching is independent of event resolution: clearing a fire reading resolves the
event, but the `EMERGENCY` latch persists until acknowledged.

---

## Configuration

`config/hazard.yaml`, loaded by `amr/utils/config.py` as `AppConfig.hazard`.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | **Deployment switch.** Wiring checks it; the layer stays inert until an operator opts in. |
| `status` | `NOT_VERIFIED` | Set to `VERIFIED` only after physical validation. |
| `slow_speed_scale` | `0.5` | Speed multiplier in `SLOW` (must be in `(0, 1]`). |
| `max_events` | `256` | Event ring-buffer size (memory is never unbounded). |
| `event_log_path` | `null` | Optional JSONL export path. |
| `gas_warn_at` / `gas_critical_at` / `gas_unit` | `300` / `1000` / `ppm` | Gas thresholds. `gas_critical_at: 0` disables the critical band. |
| `human_warn_at` / `human_critical_at` | `0.5` / `0.8` | Vision confidence thresholds (0..1). |
| `emergency_kinds` | `[FIRE, GAS, SMOKE]` | Kinds that latch `EMERGENCY`. |
| `slow_kinds` | `[GAS, SMOKE, HUMAN, ZONE_BREACH]` | Kinds that reduce speed at `WARNING`. |
| `zones` | one placeholder | `{name, x_min, x_max, y_min, y_max, severity?, kind?}` rectangles. |

Invalid values fail fast with `ConfigError` (see `_validate_hazard`).

---

## Wiring it into the robot

Opt-in, additive, and one call:

```python
from amr.hazard import GasSensorSource, HazardManager, VisionHazardSource
from amr.robot import RobotManager

mgr, _ = RobotManager.create_mock(config)
mgr.start()

hazard = HazardManager(
    config.hazard,
    sources=[
        GasSensorSource(read_mq2_ppm, name="mq2",
                        warn_at=config.hazard.gas_warn_at,
                        critical_at=config.hazard.gas_critical_at),
        VisionHazardSource(camera.detect_hazards, name="cam"),
    ],
)
mgr.attach_hazard(hazard, pose_provider=lambda: nav.pose)
```

Until `attach_hazard` is called, `RobotManager` behaves **exactly** as before:
`robot.snapshot()` has no `hazard` key, speed scaling is the identity function,
and no hazard code runs in the control loop.

Once attached:

* `RobotManager.tick()` evaluates the layer after Layer 3 and calls the existing
  `_enforce_stop` path when the verdict blocks motion — the robot ends in
  `SAFETY_STOP` with the motors at zero;
* `_gate()` additionally raises `RobotCommandError("hazard veto: ...")` on a
  blocking verdict, so motion cannot slip through between ticks;
* gated drive commands are capped by `speed_scale` (identity unless `SLOW`);
* `robot.snapshot()["hazard"]` carries the full `HazardManager.snapshot()`.

`HazardManager.from_config(...)` is the convenience constructor: it adds a
`RestrictedZoneSource` automatically when `zones` are configured.

### Run the offline demo

```bash
cd raspberry_pi
python -m amr.hazard   # scripted gas/vision scenario, no hardware, exit 0 on success
```

It walks `clean air -> gas rising (SLOW) -> human in aisle (SLOW) -> flame
(EMERGENCY)` against a mocked robot and asserts both the hazard state **and** the
robot's response to it.

---

## Operator acknowledgement is two steps

Releasing an `EMERGENCY` is deliberately explicit:

```python
hazard.acknowledge()                # 1. clear the hazard latch
robot.request_mode(RobotMode.IDLE)  # 2. acknowledge the robot's SAFETY_STOP
```

Clearing the latch does **not** return the robot to a moving mode, and resetting
the mode does not clear the latch. The safety model never auto-releases: if the
hazard is still present, the very next evaluation latches `EMERGENCY` again.

Both steps are now reachable by an operator **without a Python REPL** (see
[web_control.md](web_control.md)):

```
POST /hazard/acknowledge            → step 1 (hazard latch)
POST /command {"cmd":"mode", ...}   → step 2 (robot mode, unchanged path)
```

The web endpoint calls exactly `HazardManager.acknowledge()` under the same
lock as the control loop — no separate reset logic exists, and the maintenance
`reset()` (which drops the event audit trail) is deliberately not exposed over
HTTP. The layer is attached in `amr/main.py` only when
`config.hazard.enabled` is `true` (default `false`).

---

## Limitations / not done yet

* **No physical sensors are wired.** `config/robot.yaml` still has
  `TODO_VERIFY` ultrasonic pins and there are no gas/fire sensor pins at all.
  Nothing in this layer has run against real hardware — it is
  **hardware-dependent at the integration boundary and not tested there**.
* The gas thresholds are sensor-specific and unvalidated (an MQ-2 is calibrated
  against one reference gas and its ppm output is approximate).
* The example zone in `config/hazard.yaml` is a placeholder that happens to
  overlap `shelf_c`; it is not a surveyed layout.
* No spatial visualisation yet — events carry locations and export as JSONL, but
  nothing renders them.
* `VisionHazardSource` provides only the *seam* for fire/human detection; no
  detector model is implemented.
* The layer is **wired into `amr/web`** (`GET /hazard` + `POST
  /hazard/acknowledge`, opt-in via `config.hazard.enabled`) but **not into
  `amr/warehouse`** — task scheduling does not consult the hazard verdict yet.
* `amr/main.py` attaches the layer **without sensor sources**: no gas/vision
  hardware exists, and `RobotStateSource` is intentionally not auto-wired
  because `RobotState.last_error` is sticky (it would pin `WARNING` forever
  after the first E-STOP). Sources are added later via `hazard.add_source(...)`.

### What this is **not**

The novelty is the *aggregation*: many heterogeneous inputs, one deterministic
escalation ladder, a latched life-safety state, and an auditable location-tagged
event history. Proximity stop, obstacle avoidance, RFID, camera streaming and
navigation on their own are **not** novel and are not claimed as such.
