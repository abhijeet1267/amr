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

The console adds **no** backend state. `history` is a *projection*: it is filled
inside the existing control loop from the very same telemetry snapshot the rest
of the dashboard already reads, so charts and the rest of the page cannot
disagree.

## What is new in C15c

Only two things genuinely did not exist before:

1. **`amr/telemetry/series.py`** — a bounded time-series buffer and an event
   stream. Every earlier dashboard showed *current* values only; an operator
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

| Rule | How it is enforced |
|---|---|
| A missing value is never `0` | `extract_metrics` keeps `None`; a test asserts `0` never appears |
| `None` is not a number | booleans, `NaN` and `inf` are rejected by `_is_num` |
| No timestamp, no sample | skipped rather than backdated (same rule as C14) |
| No image-to-world conversion | only `MapSnapshot.hazards` reaches map/twin; the panel says "image-space only" |
| No invented warehouse | the map draws the data extent and labels it as such |
| `SIMULATION` is never shown as `LIVE` | a banner appears whenever the backend is mock-backed |
| Replay never overwrites live | replay status is a separate field; `/telemetry` keeps serving live |
| A missing camera is not a detection | `has_frame: false` shows "camera unavailable" and no detections |

## Safety

* The console **never** calls `POST /command`. Its only write is
  `POST /replay/control`, which is display-only on the server.
* `amr/telemetry/series.py` imports no hardware module and is checked at the
  source level for `gpio` / `RPi` / `serial` / `estop`.
* Every console read is exercised inside the existing `NoActuation` guard, which
  fails the test if an actuator verb reaches the transport.
* `command_center.js` is source-checked for `estop(`, `forward(`,
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
shows anything useful. C5d verified the console by *watching* it, which found
two defects that no existing test could see.

### 1. The camera panel could never light up

The panel requested `/camera/frame` only when telemetry reported
`has_frame` — but `has_frame` only becomes true *after* something reads a
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

| | before | after |
|---|---|---|
| in-leg direction reversals | 3 | **0** |
| steady-state step | erratic 0.06–0.45 m | **0.50 m** |
| total path length | — | 7.12 m |
| final pose | oscillating | (−0.008, 0.048) ≈ dock, phase `COMPLETED` |

### Verification actually performed

* All eleven endpoints over real HTTP — `/command-center`, both static assets,
  `/dashboard/state`, `/replay/status`, `/map`, `/digital-twin`, `/telemetry`,
  `/health`, `/camera/status`, `/camera/frame` (→ `image/png`).
* Every render function executed against a **real** `/dashboard/state` payload
  through a small DOM shim: 15 render paths OK, no `TypeError`.
* Confirmed in the rendered output: `hw-text = SIMULATION` (never claims
  hardware), `r-batt = n/a` (no fabricated value), map SVG carrying real
  geometry, a 4-wheel twin model with camera and sensor, the camera overlay
  labelled `1 (image-space)`, and 12 event-log rows.

### Two measurement traps worth recording

* **"Sign of `dx`" is not an oscillation test.** The AMR drives diagonally, so
  its x-component legitimately changes sign as the heading arc curves. The
  first version of this check reported `OSCILLATING` on a perfectly smooth run.
  A valid test measures per-step *speed* consistency and backtracking, not the
  sign of a single axis.
* **A static grep cannot confirm a runtime-filled badge.** The
  `SIMULATION` badge is populated by JavaScript from live state, so it does
  not appear in the served HTML. It has to be checked after render.


