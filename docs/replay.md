# C14 — Telemetry recording and replay (offline engine)

C14 records a run so it can be replayed later. This milestone ships the
**engine only** — the recorder and the replay player, plus tests. The dashboard
replay controls are a deliberate follow-up, so no route and no UI control is
added here.

## Data flow

```
AMR runtime (unchanged)
        │  TelemetrySnapshot / snapshot() dict  (C7)
        ▼
TelemetryRecorder.record()            bounded ring buffer + optional JSONL
        ▼
ReplayFrame  (pose, navigation, safety, hazards, mission)
        ▼
ReplayPlayer  play() / pause() / restart() / seek() / speed
        ▼
(dashboard controls — follow-up)
```

Nothing here reads the robot. The recorder is handed snapshots; the player
holds dicts. Neither has a reference to a manager, navigator, motor driver or
serial port, and a test enforces that by inspecting their imports.

## Recorder

```python
rec = TelemetryRecorder(capacity=900, path="run.jsonl", min_interval_s=0.5)
rec.record(collector.snapshot())      # -> ReplayFrame, or None if filtered
```

Three properties, borrowed from the existing `HazardEventLog` so the project
has one convention rather than two:

* **Bounded** — a fixed-capacity ring buffer, so a long run cannot grow memory
  without limit.
* **JSONL** — one JSON object per line, readable without this Python package.
* **Best effort** — an unwritable path warns and keeps recording in memory; a
  logging failure must never stop a run.

`min_interval_s` (default 0.5 s) drops samples that arrive too close together,
so a fast poll cannot fill the buffer with near-duplicates. `dropped` reports
how many were skipped.

### Honesty rules

* A snapshot with **no usable timestamp is skipped**, not recorded — a frame
  with no time cannot be placed on a timeline, and guessing would replay it at
  the wrong moment.
* An **unknown pose stays `None`**, never smoothed to `0.0`. A replay must not
  invent a position the robot never reported.
* Only the fields a replay needs are stored (pose, navigation, safety, hazards,
  mission). The full hazard **event log** from C3 remains the audit record.

## Replay player

```python
player = ReplayPlayer(read_recording("run.jsonl"))
player.speed = 2.0          # any positive float; 0.5/1.0/2.0 are the UI presets
player.play()
while True:
    frame = player.advance(dt)   # dt = seconds since the last call
```

### Why it is caller-driven

The player has **no thread, no `sleep` and no internal clock**. You hand it
elapsed time and it tells you which frame should be on screen. This is the whole
design:

* the same `advance` sequence always yields the same frames, so a demo is
  reproducible;
* the tests finish in milliseconds with no real time passing;
* a browser loop already owns a timer, so the future dashboard can drive this
  directly instead of starting a second one.

A source-level test fails if `time.time`, `time.sleep` or `Thread` ever appear
in the module.

### Transport semantics

| Action | Behaviour |
|---|---|
| `play()` | Start advancing. At the end, restarts from the beginning. |
| `pause()` | Freeze; the current frame stays on screen. |
| `restart()` | Back to frame 0, **paused** — playback does not auto-resume. |
| `seek(i)` / `seek_seconds(t)` | Clamped jump; a pure lookup, no time passes. |
| `advance(dt)` | Move the virtual clock by `dt × speed`. |

Deliberate choices:

* **Reaching the end stops and holds the last frame** rather than wrapping. A
  replay that silently loops is surprising.
* **A negative or unparseable `dt` is ignored** — a clock glitch is not a
  rewind request.
* **A non-positive speed is refused** with a `ValueError`, so `play()` can never
  quietly mean "rewind".
* A frame is on screen *at* its timestamp and stays until the clock passes it
  (exact tie-breaking), which is what makes playback reproducible.

## Recording format

JSONL, one frame per line, schema `"1.0"`:

```json
{"schema_version": "1.0", "timestamp": 1700000000.0, "offset_s": 0.0,
 "pose": {"x": 1.2, "y": 0.4, "z": 0.0, "yaw": 0.0},
 "navigation": {"state": "MOVING", "goal": "shelf_a", "route_points": 2},
 "safety": {"state": "NORMAL", "action": "PROCEED", "emergency_stop": false},
 "hazards": [{"kind": "FIRE", "severity": "CRITICAL", "confidence": 0.9,
              "source": "cam", "x": 2.0, "y": 3.0}],
 "hazard_state": "EMERGENCY",
 "mission": {"mission_id": "web-run", "current_task": "t1",
             "current_task_type": "PICK", "current_task_status": "RUNNING",
             "completed_tasks": 0}}
```

`read_recording()` skips a corrupt line rather than aborting, so a truncated
final line — common when a run is interrupted — does not make the whole
recording unplayable.

## Safety

- Display/record only. **No new HTTP route**, and `POST /command` remains the
  only actuator path.
- Source-level tests assert neither module imports `serial`, `RPi`, `gpio`,
  `socket` or `threading`, and that the recorder contains no actuator vocabulary.
- A test records a **real mock run** and asserts the transport sees no writes
  beyond what the run itself did.

## Limitations

- **Hardware tested: no.** Software/mock only.
- Dashboard controls are a follow-up; this milestone is library + tests.
- Recordings are in-memory bounded and JSONL on disk; there is no database, no
  index, and no multi-run query.
- Replay renders what was recorded — it does not re-simulate, so it cannot
  answer "what would happen if…".
- No interpolation between frames: playback shows recorded samples as-is.
