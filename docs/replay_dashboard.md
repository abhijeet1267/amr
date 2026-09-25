# C14b — Dashboard replay controls

C14b wires the C14 replay engine into the existing dashboard: a recording list,
a load action, PLAY / PAUSE / RESTART, and 0.5x / 1x / 2x speed. It adds a
**Historical Replay** card to `/dashboard` and a small set of read-only routes.

## Architecture — one tick, no new loop

```
AMR runtime ──► live telemetry ─────────────────────┐
                                                    │
config/replay.yaml ──► RecordingStore ──► ReplayController
   (recordings_dir)      (read-only        (owns a ReplayPlayer,
                          discovery)        no clock, no thread)
                                                    │
             existing _control_loop (already running)
                    mgr.tick()
                    replay.tick(interval)  ◄── C14b's only hook
                                                    │
                           GET /replay/status ◄──────┘
                                    │
                        existing browser 1 Hz poll()
                                    │
                          Historical Replay card
```

**The server advances replay, not the browser.** The web app already runs a
control loop; `replay.tick(interval)` was added to it. The browser only *reads*
where the playback has reached, from the same `poll()` it already used. A test
asserts the dashboard page still contains **exactly one** `setInterval`, and
that the C14 engine's no-thread / no-clock rules are untouched.

The C14 engine itself was **not modified** — C14b only consumes
`ReplayPlayer`.

## API

| Route | Method | Purpose |
|---|---|---|
| `/replay/recordings` | GET | Available recordings + current status |
| `/replay/status` | GET | Replay status + the current frame |
| `/replay/load` | POST | `{"recording_id": "run.jsonl"}` |
| `/replay/play` | POST | Start advancing |
| `/replay/pause` | POST | Freeze, keep the frame |
| `/replay/restart` | POST | Back to frame 0, paused |
| `/replay/speed` | POST | `{"speed": 0.5 \| 1 \| 2}` |
| `/replay/unload` | POST | Back to live |

`/replay/recordings` is fetched when the panel opens, **not** on every 1 Hz
tick — discovery is a directory listing, and a large directory should not be
rescanned once a second.

## Security — ids, never paths

A client never supplies a filesystem path. It supplies a `recording_id`, which
`is_valid_recording_id()` accepts only if it is a plain filename ending in
`.jsonl`. Rejected: `../`, absolute paths, any separator, `..`, `.`, hidden
names, NUL bytes, over-long names and non-strings. The joined path is then
required to sit directly inside the configured directory, so a crafted id
cannot read anything else off disk.

## Configuration

```yaml
# config/replay.yaml
replay:
  enabled: true
  recordings_dir: null      # null = replay off
```

`recordings_dir: null` mirrors `hazard.yaml`'s `event_log_path: null`
convention: the panel stays visible and honestly reports *"no recordings
directory configured"* instead of pretending the feature is broken. A relative
path resolves against the config directory, so the same config works in the
repo and on a Pi.

## Replay state

`NO_RECORDING → READY → PLAYING ⇄ PAUSED → FINISHED`, plus `ERROR` for a bad
id, a missing recording or an unconfigured directory. `active` is true for
everything except `NO_RECORDING` and `ERROR`, and drives the LIVE/REPLAY badge.

Transport decisions inherited from the C14 engine: **PAUSE keeps the current
frame and does not unload**; **RESTART returns to the start paused**; reaching
the end **finishes and holds the last frame** rather than looping; a
non-positive speed is **refused** rather than silently rewinding.

## Live / replay separation

The `Data source` field shows `LIVE` or `REPLAY` explicitly, and the panel
notes *"Showing a recorded run. The live robot is unaffected"*. Replay data is
never written back over live telemetry: `GET /replay/status` carries its own
`frame`, separate from `/dashboard/state`. "Back to live" unloads and the badge
returns to `LIVE`.

## Safety

- **Display-only.** The replay POST branch returns before the `/command` path
  and never calls `dispatch()`.
- **Zero actuator writes**, verified end-to-end over real HTTP against the
  mock transport.
- Source-level tests assert the controller imports no `serial`, `RPi`, `gpio`,
  `socket` or `threading`.
- A regression test re-asserts the pre-existing C9 invariant that
  `DASHBOARD_HTML` contains no actuator-endpoint reference at all.

### A regression this milestone caught

Two pre-existing tests (`test_map.py`, `test_web_server.py`) assert the
dashboard HTML never mentions the actuator endpoint. C14b's first draft broke
both — not with a real call, but with the words *"never reach /command"* in an
explanatory comment. The tests were right and the prose was wrong, so the
comment was reworded. The invariant is now asserted three times, because a
comment can break it as easily as a fetch can.

## Automatic recording (C14c)

The recording half of the chain is automatic. `amr/telemetry/auto_record.py`
wraps C14's `TelemetryRecorder` in a small lifecycle: `start()` opens a run,
`record(snapshot)` appends one throttled frame, `stop()` closes it.

The web runtime calls it from the **control loop that already exists**:

```
AMRWebApp._control_loop(interval)          <- one loop, one lock, pre-existing
    |
    +--> mgr.tick()                       <- robot control (unchanged)
    +--> self._replay.tick(interval)      <- C14b playback (unchanged)
    +--> self._auto.record(
    |        self.telemetry.snapshot())   <- C15: the SAME snapshot the
    |                                        dashboard reads
    +--> sleep via _stop_evt.wait(interval)
```

`self.telemetry.snapshot()` is the C7 collector the live dashboard already
consumes, so there is **one snapshot, two consumers** — not a second
collection path and not a second loop.

### Lifecycle

| Event | What happens |
|---|---|
| `app.start()` | `AutoRecorder.start()` — opens `run-<YYYYmmdd-HHMMSS>.jsonl` |
| each tick | `record(snapshot)` — throttled by `replay.min_interval_s` |
| `app.stop()` | `stop()` → summary, file closed and complete |

A run that recorded nothing writes no file. A name that already exists gets a
suffix rather than overwriting a previous run, so two runs both stay
discoverable. Source-level tests assert the server still contains exactly one
`def _control_loop` and one `self._stop_evt.wait(interval)`.

### Timestamps

C14's rule is preserved exactly: **a snapshot with no usable timestamp is
skipped, not recorded at a guessed moment.** The recorder never manufactures a
timestamp to increase the frame count.

### Failure isolation

`record()` is wrapped in `try/except` inside the loop. A recorder that raises
(e.g. `OSError: disk full`) is logged and the control loop continues — recording
is an optional observer, never a dependency of the control path. This is
covered by a test that swaps in a recorder which always raises.

### Configuration

```yaml
# config/replay.yaml
replay:
  enabled: true
  auto_record: true
  recordings_dir: null     # null => records nothing (the shipped default)
```

Both `auto_record` and a non-null `recordings_dir` are required, so the default
configuration records nothing. Set `recordings_dir` (relative paths resolve
against the config directory) to start recording.

### Complete lifecycle

```
LIVE robot / mock
   -> telemetry snapshot
   -> TelemetryRecorder            (C14, automatic)
   -> JSONL in replay.recordings_dir
   -> RecordingStore               (C14b discovery, same directory)
   -> GET /replay/recordings       (dashboard selector)
   -> ReplayPlayer                 (C14, unchanged)
   -> Historical Replay card       (C14b, PLAY/PAUSE/RESTART/0.5x/1x/2x)
```

C14/C14b/C14c recordings need **no conversion step** — the format is unchanged.

### Safety

Recording is read-only. It never commands motors, publishes velocity, invokes
`/command`, writes serial/GPIO, triggers navigation or replanning, or alters
mission or hazard state. The only side effect is a local JSONL file. A test
asserts zero actuator writes across control-loop ticks with recording active.

### Hardware status

Software and mock only. **No hardware or firmware validation was performed** —
no physical robot, Raspberry Pi, camera, or Arduino was exercised.

## C15 — the unified demo

One deterministic, offline run that exercises the whole stack **through its real
interfaces** — no subsystem is re-implemented for the demo:

```
mission (WarehouseTaskManager)
  -> navigation (LocalNavigator)
     -> simulated vision (ScriptedVisionDetector -> VisionDetection)
        -> hazard (HazardManager + VisionHazardSource)
           -> safety (SafetyManager, then the C6 AvoidancePolicy)
              -> navigation changes (TURN)
                 -> mission continues -> completion
                    -> automatic recording (AutoRecorder)
                       -> discovery (RecordingStore)
                          -> replay (ReplayPlayer)
```

Run it:

```bash
cd raspberry_pi
python -m amr.demo                       # temporary recording dir
python -m amr.demo --recordings-dir /tmp/r
```

It prints a deterministic report and exits non-zero if any stage did not happen.

### What the scenario actually does

The AMR starts at the dock and runs the standard warehouse mission
(`pick shelf_a` → `place station` → `return_to_dock`). At step 30 a **simulated**
detector reports `OBSTACLE` at confidence **0.70** with a **pixel** bounding box
`[250, 300, 140, 90]` from `camera_front`; it clears at step 42.

The confidence is deliberately inside the WARNING band (0.5–0.8). A CRITICAL
reading would make the hazard layer *block* motion, and the C6 policy would never
be consulted — WARNING is exactly the case the avoidance gate exists for.

### Components used

| Concern | Real object |
|---|---|
| robot control + safety | `RobotManager` over `MockSerialTransport` |
| Layer 3.5 hazard layer | `HazardManager` + `VisionHazardSource` |
| vision evidence | `VisionDetection` (the C5 contract) |
| C6 avoidance | `AvoidancePolicy` via `LocalNavigator` |
| mission | `WarehouseTaskManager` |
| telemetry | `TelemetryCollector` (the C7 collector) |
| runtime tick + recording | `AMRWebApp._tick_once` / `AutoRecorder` |
| discovery / replay | `RecordingStore` + `ReplayPlayer` |

Only two things are demo adapters, and both are labelled SIMULATION in the code
and in the report:

* `ScriptedVisionDetector` — a step-indexed script, because the existing
  `SimulatedVisionDetector` returns a *fixed* scenario and cannot express "an
  obstacle appears part-way through a run". It emits the existing C5
  `VisionDetection` contract; nothing downstream can tell the difference.
* `SimulatedClearance` — a constant open-side feed, because the project has no
  calibrated clearance source (a documented C6 gap). Without it the policy would
  correctly escalate to REPLAN instead of guessing a heading.

### Determinism

The scenario is driven by a **step counter** with a fixed `dt` and a virtual
clock; there is no randomness. Two runs produce identical timelines, hazard
event ids, avoidance actions, frame counts and an identical CLI report.

Two things are run-unique by design and are *not* compared: the recording
filename (wall-clock derived) and `mission.current_task` (its id comes from
`Task`'s process-global counter, so a second run in the same process gets a
higher number). The task type, status and completion must still match exactly.

**One loop only.** The demo deliberately does *not* call `app.start()`, because
that also spawns the background control-loop thread, which would tick the robot
concurrently and make the run non-deterministic. Instead it drives the very same
`AMRWebApp._tick_once` that the background thread calls. To make that possible
the loop body was extracted into `_tick_once`; there is still exactly one
`_control_loop` and one `_stop_evt.wait(interval)`, and a source-level test
pins that.

### Coordinate honesty (C13 rule)

The detection carries a pixel bounding box and **no** world pose, so:

* the box survives only as event metadata, and
* the hazard is **not** placed on the warehouse map.

The report prints both facts explicitly, and a test asserts them.

### Actuation honesty

The mission genuinely drives the mock robot, so the mock transport records wheel
commands — that is how a simulated mission moves. "0 actuator writes" would be a
misleading claim, so the report separates the numbers:

| Field | Meaning |
|---|---|
| `TRANSPORT WRITES` | all lines to the mock transport |
| `WHEEL COMMANDS` | lines that were `MOVE`/`D` commands |
| `VIA MANAGER GATE` | wheel commands, all of which went through `mgr.move` |
| `PHYSICAL WRITES` | **0** — the demo only ever builds a mock stack |
| `DEMO DIRECT COMMANDS` | **0** — the scenario code never calls a motor API |

`POST /command` remains the only actuator path, and the demo never touches it.

### A pre-existing bug this milestone found

`TelemetryCollector._hazard()` gated on `snap.get("attached")`, but
`HazardManager.snapshot()` has never emitted an `attached` key — that is a C2
*web payload* field. The condition was therefore always false, so the hazard
section of **every** telemetry snapshot (and of every recording) silently
reported `UNAVAILABLE`: the hazard was invisible in `/telemetry` and in replay.
This is the same class of mistake as the C12 mission-section defects. C15 fixed
it and the demo now proves the hazard reaches telemetry and the recording.

### Limitations

* Simulated detector, simulated clearance, mock transport. No camera, no
  ultrasonic, no Arduino, no Raspberry Pi.
* The vision band (0.5 / 0.8) and every avoidance threshold remain **software
  defaults**; `config/safety.yaml` is still `NOT_VERIFIED`.
* The route is straight-line waypoint following; there is no path planner, so
  "REPLAN" means "re-aim at the goal", not "search a new path".
* The demo does not start the web server, so it is not observable live in a
  browser; it prints the same values the dashboard panels would show.

**Hardware / firmware: NOT TESTED.**

## Limitations

- **Hardware tested: no.** Software/mock only.
- Only the latest loaded recording is held in memory; there is no playlist.
- The card is a compact control panel, not a timeline — no scrubbing, no
  per-frame scrubbing or editing.
- Recording itself is still driven by a caller feeding snapshots to
  `TelemetryRecorder`; the web runtime does not yet auto-record.
- Only the frames that were captured can be replayed; there is no
  re-simulation.

## Next step

Wiring `TelemetryRecorder` into the running web app so a deployment records
automatically would complete the loop: record → discover → replay.
