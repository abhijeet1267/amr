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
