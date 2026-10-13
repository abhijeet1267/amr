# C15c — AMR Command Center

The Command Center is the project's operator console: one browser page that
brings the robot, the warehouse, the camera, the mission, safety, telemetry and
historical replay into a single view.

It is a **view, not a robot**. Everything it shows is read from the existing
authoritative backend, and nothing it does can move the robot.

## Running it

```bash
cd raspberry_pi

# the console, fully mocked (no serial, no motors, no camera)
python -m amr.main --mock --web
# then open http://localhost:8080/command-center

# drive a real mission while watching it (mock-only by design)
python -m amr.main --mock --web --mission-demo
```

`--mission-demo` commands autonomous motion, so it is **refused without
`--mock`** rather than silently starting a mission against real hardware.

To take screenshots, open the URL in a browser and use the OS screenshot tool.
No browser-automation stack is added: the console is plain HTML/CSS/JS served by
the Python process, so there is nothing to build or bundle first.

## Architecture

```
AMR runtime (authoritative)
      │  existing collectors; no new state model
      ▼
GET /dashboard/state  ── one request per second
      ├── robot / navigation / safety / mission / battery / sensors / camera
      ├── map       (C9 MapSnapshot)
      ├── twin      (C10 DigitalTwinState)
      ├── history   (C15c bounded series + event stream)
      ├── recording (C14c)
      └── replay    (C14b)
      ▼
Command Center (read-only)
      ├── 3D twin      raw WebGL
      ├── 2D map       SVG
      ├── camera       <img> + overlay
      ├── charts       2D canvas
      └── event log    DOM
```

The console adds **no** backend state. `history` is a _projection_: it is filled
inside the existing control loop from the very same telemetry snapshot the rest
of the dashboard already reads, so charts and the rest of the page cannot
disagree.

## What is new in C15c

Only two things genuinely did not exist before:

1. **`amr/telemetry/series.py`** — a bounded time-series buffer and an event
   stream. Every earlier dashboard showed _current_ values only; an operator
   needs to see how something is moving and one ordered feed of what happened.
2. **`amr/web/static/command_center.{html,css,js}`** — the console itself, kept
   as real files rather than embedded Python strings.

Everything else is C7–C15b work, consumed rather than reimplemented.

## Bounded, server-side history

History lives **on the server**, in fixed-length deques (150 samples, 200
events by default). A robot left running for days must not grow its heap, and
the browser re-fetches a window instead of accumulating. Keeping the past in one
place also means the charts and the event log cannot tell different stories.

The event stream emits on **change**, not on every poll. Without that a 1 Hz tick
would log "mission: PICK" sixty times a minute and the log would be useless.
Categories (`MISSION`, `SAFETY`, `HAZARD`, `VISION`, `NAVIGATION`, `CAMERA`,
`SYSTEM`) and levels (`CRITICAL`, `WARNING`, `INFO`) are declared in the payload,
so the UI's filter buttons cannot drift from the server.

## Honesty rules (enforced by tests, not just convention)

| Rule                                  | How it is enforced                                                                                                               |
| ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| A missing value is never `0`          | `extract_metrics` keeps `None`; a test asserts `0` never appears                                                                 |
| `None` is not a number                | booleans, `NaN` and `inf` are rejected by `_is_num`                                                                              |
| No timestamp, no sample               | skipped rather than backdated (same rule as C14)                                                                                 |
| No image-to-world conversion          | only `MapSnapshot.hazards` reaches map/twin; the panel says "image-space only"                                                   |
| No invented warehouse                 | the map draws the data extent and labels it as such                                                                              |
| `SIMULATION` is never shown as `LIVE` | a banner appears whenever the backend is mock-backed                                                                             |
| Replay never overwrites live          | replay status is a separate field; `/telemetry` keeps serving live                                                               |
| A missing camera is not a detection   | `has_frame: false` shows "camera unavailable" and no detections                                                                  |
| A real reading is never hidden        | each ultrasonic face is its own row with its own cm value; a per-face reading suppresses the generic `NOT CONNECTED` placeholder |
| Charts are counts, never scores       | the health bars tally the scorecard rows; no percentage or grade is produced                                                     |

### The health bars and the risk histogram

Two charts sit in the **Robot Health** card. Both are built from counts, because
the project defines no weighting between subsystems and a percentage would
therefore be an invented number:

- **Health bars** — how many subsystems sit in each state (`HEALTHY`,
  `DEGRADED`, `WARNING`, `FAULT`). Every state gets a bar even at zero, so the
  chart cannot silently change shape, and each bar prints its own figure so the
  bar is never the only carrier of the number. The bars sum to the number of
  rows in the table beside them, which an operator can count for themselves.
- **Risk frequency** — a plain histogram of real `SAFETY` events over a
  10-minute window, from the same event stream the safety history list uses.
  Nothing is extrapolated into a rate. A bucket with no events still draws a
  2px stub, so an empty window is a _drawn zero_ rather than a gap that could be
  read as a rendering fault, and the note says in words when the log is empty —
  "no events occurred" and "the feed is broken" must not look alike.

## Safety

- The console **never** calls `POST /command`. Its only write is
  `POST /replay/control`, which is display-only on the server.
- `amr/telemetry/series.py` imports no hardware module and is checked at the
  source level for `gpio` / `RPi` / `serial` / `estop`.
- Every console read is exercised inside the existing `NoActuation` guard, which
  fails the test if an actuator verb reaches the transport.
- `command_center.js` is source-checked for `estop(`, `forward(`,
  `rotate_left(`, `.dispatch(` and `"/command"`.

## Static asset safety

`/static/*` resolves through a **whitelist**, not a directory join, so
`/static/../../../../etc/passwd` resolves to nothing and returns `404`. Tests
cover that, URL-encoded traversal, and a non-allowlisted filename.

## Accessibility

Landmarks and headings, a skip link, `aria-live="polite"` on the safety banner
and the event log, `aria-pressed` on every toggle, `aria-label` on every canvas,
a labelled `role="img"` map, visible focus rings (never `outline: none`), and —
importantly — **status text alongside every colour**, so safety state is never
communicated by hue alone. `prefers-reduced-motion` is respected.

## Performance

One `setInterval` drives telemetry at 1 Hz; a second, slower one refreshes the
recording list. The camera frame is fetched only when `has_frame` is true. The
3D view rebuilds a small triangle buffer per tick, and a test pins the timer
count so a future change cannot quietly introduce a polling storm.

## Zero added dependencies

No npm, no CDN, no build step, no framework. The 3D view is hand-written WebGL
and the charts are 2D canvas, both built into every browser. The whole console
ships as three files inside the Python package, so it runs on a Raspberry Pi
with no network access.

## Hardware status

**Hardware / firmware: NOT TESTED.** The console has been verified only against
mock-backed and simulated data. No physical robot, camera, sensor or motor
controller was involved, and the existing C15b caveat still applies: the Pi
Camera V2 needs a 15-pin to 22-pin adapter for the Raspberry Pi 5 before any
real frame can be captured. The legacy `/dashboard` page remains available and
unchanged; the Command Center is an additional view, not a replacement.

## C5d — visual verification, and two defects it caught

A route returning 200 proves the server responded. It does not prove the page
shows anything useful. C5d verified the console by _watching_ it, which found
two defects that no existing test could see.

### 1. The camera panel could never light up

The panel requested `/camera/frame` only when telemetry reported
`has_frame` — but `has_frame` only becomes true _after_ something reads a
frame. Nothing read one, so nothing ever lit up: a self-blocked panel.

The frame is now requested whenever the camera is not
`UNAVAILABLE`/`ERROR`, and `onerror` collapses back to the notice, so a dead
camera still reads as dead rather than as a broken image. The panel is now a
real visual area with an honest empty state, not a text card.

### 2. The AMR oscillated instead of driving

`run_web` ran its own 1 Hz loop:

```python
while True:
    time.sleep(1.0)
    mgr.tick()
    mission.process(dt=1.0)
```

while the server's `_control_loop` was already calling `mgr.tick()` at
`tick_hz` (5–10 Hz by default). Two things went wrong at once:

- the robot was integrated **twice** per second, and
- the planner's clock ran 5–10× too fast, so the goal outran the robot.

The visible symptom was the robot reversing back and forth along its route
(`x: -0.2 → -0.32 → 0.17 → 0.41`) rather than tracking the path.

The fix follows the precedent already set by C14b/C14c/C15c: the mission is
stepped by the **existing** `_tick_once`, using that loop's own `interval`,
and `run_web` now only keeps the process alive. `AMRWebApp._run_warehouse` had
been set and never read — a dead flag, which is why `--mission-demo` did
nothing inside the server — and is now backed by a real `self._warehouse`
reference.

|                            | before              | after                                     |
| -------------------------- | ------------------- | ----------------------------------------- |
| in-leg direction reversals | 3                   | **0**                                     |
| steady-state step          | erratic 0.06–0.45 m | **0.50 m**                                |
| total path length          | —                   | 7.12 m                                    |
| final pose                 | oscillating         | (−0.008, 0.048) ≈ dock, phase `COMPLETED` |

### Verification actually performed

- All eleven endpoints over real HTTP — `/command-center`, both static assets,
  `/dashboard/state`, `/replay/status`, `/map`, `/digital-twin`, `/telemetry`,
  `/health`, `/camera/status`, `/camera/frame` (→ `image/png`).
- Every render function executed against a **real** `/dashboard/state` payload
  through a small DOM shim: 15 render paths OK, no `TypeError`.
- Confirmed in the rendered output: `hw-text = SIMULATION` (never claims
  hardware), `r-batt = n/a` (no fabricated value), map SVG carrying real
  geometry, a 4-wheel twin model with camera and sensor, the camera overlay
  labelled `1 (image-space)`, and 12 event-log rows.

### Two measurement traps worth recording

- **"Sign of `dx`" is not an oscillation test.** The AMR drives diagonally, so
  its x-component legitimately changes sign as the heading arc curves. The
  first version of this check reported `OSCILLATING` on a perfectly smooth run.
  A valid test measures per-step _speed_ consistency and backtracking, not the
  sign of a single axis.
- **A static grep cannot confirm a runtime-filled badge.** The
  `SIMULATION` badge is populated by JavaScript from live state, so it does
  not appear in the served HTML. It has to be checked after render.

---

---

# Advanced Command Center upgrade (2026-10-13)

This section records the advanced upgrade layered on top of the C15c console:
a hardware status grid, live ultrasonic monitor, command execution history, an
LCD display mirror, an I/O panel, and a warning/fault center. It is the source
of truth for how those work.

> **Honesty rule.** Where something is simulated, not connected, or not verified
> on hardware, this says so. Nothing here upgrades a mock reading into a physical
> one.

## Architecture

The advanced panels extend the existing single-read-only-poll design. They add
**no request and no timer** — each reads a new block from the same
`/dashboard/state` payload:

```
   GET /dashboard/state  (one request, 1 Hz)
     existing: telemetry, map, twin, heatmap, ops, history, replay, recording
     new:      hardware, commands, alerts, lcd, io
```

- One poll. The page still uses exactly two `setInterval`s (one poll, one
  file-list) — a tested invariant.
- Read-only console. Submission stays on the control panel (`/`), the sole
  actuator path. A test fails if the console JS calls `forward(`, `estop(`,
  `"/command"`, `pwm`, or `gpio`.
- Modular renderers: `renderHardware`, `renderUsMonitor`, `renderCommandHistory`,
  `renderLcd`, `renderIo`, `renderAlertCenter` — each reads only its own block.
- New views are navigable via top tabs, sidebar, and deep links:
  `/command-center#hardware`, `#commands`, `#io`, `#alerts`.

## API (advanced)

| Route                      | Method | Purpose                                                                             |
| -------------------------- | ------ | ----------------------------------------------------------------------------------- |
| `GET /dashboard/state`     | GET    | Now carries `hardware`, `commands`, `alerts`, `lcd`, `io`.                          |
| `POST /alerts/acknowledge` | POST   | `{"alert_id": "..."}`. Flags an alert acknowledged. **Never resolves it.** 200/404. |

`/alerts/acknowledge` is the only new write; it is a flag, not a command, and
cannot move the robot or clear a physical fault.

### `hardware`

`{components:[{id,name,kind,status,source,value,unit,detail,last_update,age_s,
classification,simulated}], controller_connected, backend_online, state}`.
Component `status`: `CONNECTED`, `FAULTY`, `CONFIGURED`, `SIMULATED`,
`UNAVAILABLE`, `UNKNOWN`. Overall `state`: `ONLINE`, `SIMULATION`, `DEGRADED`,
`DISCONNECTED`. `value` is present only when measured; `None` is never a zero.

### `commands`

`{commands:[{command,params,state,command_id,created_at,acknowledged_at,
completed_at,response,error,executed,environment,robot_mode_after,duration_ms}],
counts, total}`. `state`: `CREATED`, `VALIDATED`, `ACCEPTED`, `SUCCEEDED`,
`REJECTED`, `FAILED`, `TIMED_OUT`, `UNKNOWN`. `executed` is `true` only when the
robot's own state confirms motion began; `null` (unknown) otherwise — never
assumed from an HTTP 200.

### `alerts`

`{active:[{alert_id,source,severity,description,first_seen,last_updated,status,
acknowledged,clearable_by_user,suggestion}], resolved, active_count,
critical_count, warning_count, unacknowledged_count}`. `severity`: `INFO`,
`WARNING`, `ERROR`, `CRITICAL`.

### `lcd`

`{rows[2],columns:16,rows_count:2,connected,content_confirmed:false,address,
note}`. `content_confirmed` is always `false` (the LCD is write-only, no
read-back); the preview is labelled intended, not the physical screen.

### `io`

`{outputs,sensors,comms,motors,note,simulated}`. Configuration + logical state
only — the Pi does not own these pins, so nothing is probed or toggled. Motor
values are _requested_, not measured.

## Component inventory (real state, not hardcoded)

| Component              | Source of state                        | Verified on hardware?             |
| ---------------------- | -------------------------------------- | --------------------------------- |
| Raspberry Pi (backend) | always, when serving                   | n/a (the server)                  |
| Arduino UNO            | `telemetry.connected`                  | Yes — `PONG`/`VERSION`/`STATUS`   |
| Motors (L298N)         | `is_moving`, `left/right_speed`        | **No** — never commanded          |
| Ultrasonic ×4          | `sensors.front_cm`…`rear_cm`           | Yes — live cm                     |
| DHT11                  | `sensors.temperature_c`/`humidity_pct` | **No** — not reading              |
| MQ gas                 | `sensors.gas_raw`                      | **No** — no pin, unmeasured       |
| I2C LCD                | config `lcd_i2c_address`               | **No** — write-only               |
| Buzzer                 | config `buzzer_pin`                    | **No** — command-driven           |
| Camera                 | `telemetry.camera`                     | Yes — live 1280×720               |
| Battery                | `telemetry.battery`                    | **No** — no sensor, `UNAVAILABLE` |

## Ultrasonic monitor

Four HC-SR04, pins per the applied chart (verified): front `D2/D3`, left
`D4/D5`, right `D6/D7`, rear `D8/D9`, in cm. Per face: live distance (or `n/a`
when no echo — never 0), a **display-only** classification using the safety
thresholds (`CLEAR`→`CAUTION`→`OBSTACLE`→`TOO_CLOSE`, plus `OUT_OF_RANGE`,
`NO_ECHO`, `STALE`), and a bounded 60-sample sparkline. The classification does
**not** drive the robot — stop logic stays in the firmware Layer-1 and the Pi
`SafetyManager`.

## Command lifecycle

`dispatch()` records every command in a bounded `CommandLog` (200 entries):
`CREATED → VALIDATED → (ACCEPTED → SUCCEEDED | REJECTED | FAILED | TIMED_OUT)`.
A 200/ACK is `SUCCEEDED` (accepted). For motion, `executed` comes from the robot
state after the command, not the HTTP result. The console shows the history but
submits nothing.

## Alert rules

`AlertEngine` derives the alert set from the snapshot each tick and reconciles
it: firing rules create/refresh, stopped rules resolve (kept in history),
acknowledge is a flag not a cure, and a physical safety alert
(`clearable_by_user: false`) only resolves when its condition clears. Rules:
controller/backend disconnected, telemetry stale, per-face sensor invalid,
camera error, hazard active/critical, task failed, nav failed, DHT11 absent
(INFO), gas unassigned (INFO). Duplicate conditions yield one alert, not many.

## Mapping / spatial hash

The project models the warehouse as named waypoints + a bounded path history.
There is **no occupancy grid and no spatial hash** in this repository, so no
fake grid/hash diagnostic was added (per the brief). If a real occupancy grid is
added later, that diagnostic belongs here.

## Simulation mode

`--mock` runs the whole robot in-process. The dashboard runs fully offline:
simulated values carry `SIM` tags, the header shows `SIMULATION` with a banner,
the command log records `environment: SIMULATION`, and a mock command can never
reach a physical actuator (the mock transport has no real device, and the
console submits nothing).

## Testing

```bash
cd raspberry_pi && python -m pytest
python -m pytest tests/test_advanced_command_center.py   # new projection tests
python -m pytest tests/test_command_center.py            # structure + safety invariants
```

New tests cover hardware inventory (states, absent≠0, classification, sim
labels), the command log (acceptance≠execution, rejection, bounding), the alert
engine (recovery, ack-is-not-cure, safety not user-clearable, dedup, stale), and
LCD state (row fitting, never-confirmed, safety-over-command, virtual label).

## Remaining hardware verification

Software is complete and tested; these are honest gaps to verify when the robot
is powered on:

- **Motors have never been commanded** — direction, polarity, PWM speed, real
  stop distances. Test first, wheels off the ground.
- **DHT11** — confirm it reads (likely needs the 10 kΩ pull-up).
- **MQ gas** — free an analog pin before it can report.
- **LCD** — confirm the physical display matches the panel.
- **Buzzer** — confirm it tones on `BUZZ` and stops on `BUZZ 0`.
- **Safety thresholds** — still `NOT_VERIFIED`; measure before trusting speed.
- **Robot geometry** — `wheel_track_m` / `wheel_diameter_m` still `null`.
