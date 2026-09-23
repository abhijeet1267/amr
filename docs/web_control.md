# Web Remote Control & Camera (Phases 10–11)

A small **stdlib-only** HTTP control panel for the AMR, plus the camera/vision
manager that feeds it. The web layer adds **no new capabilities**: every
command funnels through the gated `RobotManager` API, so a safety veto, an
illegal mode transition, or a disconnected link all surface as `HTTP 400` —
the robot never moves when the gate says no (see [safety.md](safety.md)).

---

## Running it

```bash
# Fully offline: mock Arduino + mock camera, no hardware, no pyserial
python -m amr.main --mock --web

# Against the real robot (camera optional, degrades gracefully)
python -m amr.main --web
python -m amr.main --web --host 0.0.0.0 --port 8090   # LAN access
```

The server prints the URL on start; `Ctrl-C` stops the robot and the server.
By default it binds `0.0.0.0` (Pi on the LAN). The panel polls `/status`
every 500 ms and the camera view every 2 s.

> **Access control:** there is **no authentication** — this is a LAN tool for
> a single operator. Do not expose the port to the internet (no port-forward,
> no DMZ). The E-STOP button is the primary remote safety action.

---

## HTTP API

| Method | Path       | Description                                        |
|--------|------------|----------------------------------------------------|
| GET    | `/`        | Self-contained control panel (no external assets)  |
| GET    | `/status`  | Full robot snapshot (JSON)                         |
| GET    | `/sensor`  | One sensor poll + safety decision (JSON)           |
| GET    | `/camera`  | Camera status (JSON)                               |
| GET    | `/image`   | One JPEG frame (`image/jpeg`, or 503 unavailable)  |
| GET    | `/hazard`  | Hazard layer status (JSON, see below)              |
| POST   | `/command` | Execute one command (JSON in, JSON out)            |
| POST   | `/hazard/acknowledge` | Release a latched hazard `EMERGENCY` (step 1 of the two-step release) |

### Commands (`POST /command`)

| Command                      | Payload                                |
|------------------------------|----------------------------------------|
| Emergency stop               | `{"cmd": "estop"}`                     |
| Motion stop (never gated)    | `{"cmd": "stop"}`                      |
| Mode transition              | `{"cmd": "mode", "mode": "manual"}`    |
| Drive (speed 1–255, default per command) | `{"cmd": "forward", "speed": 120}` |
|                              | `backward`, `rotate_left`, `rotate_right`, `turn_left`, `turn_right` |

`mode` accepts `idle`, `manual`, `autonomous` (case-insensitive) and is
subject to the Phase 9 mode state machine. `estop` and `stop` are **never**
gated — you must always be able to stop the robot.

**HTTP status codes**

| Code | Meaning                                                    |
|------|------------------------------------------------------------|
| 200  | Command executed / data served                             |
| 400  | Rejected: safety veto, illegal mode transition, bad payload, speed out of range, disconnected |
| 503  | `/image` — camera unavailable                              |
| 500  | Internal error (logged)                                    |

Rejections carry a human-readable reason: `{"ok": false, "error": "..."}`.

---

## Hazard layer (C2)

The web layer is the operator-facing surface of the Layer-3.5 hazard
system ([hazard.md](hazard.md)). It is wired in `amr/main.py` **only when
`config.hazard.enabled` is `true`** (the default is `false`, so an unopted
deployment behaves exactly as before).

### `GET /hazard`

A **pure read** — it never evaluates or clears anything. The body is
`HazardManager.snapshot()` (the established JSON contract) extended with a few
derived operator keys:

| Key | Type | Meaning |
|---|---|---|
| `attached` | bool | `false` when no hazard layer is wired (stable shape, honest nulls — same convention as `/camera`) |
| `state` | `"NORMAL" \| "WARNING" \| "SLOW" \| "STOP" \| "EMERGENCY"` or `null` | current verdict |
| `severity` | `"NONE" \| "WARNING" \| "CRITICAL"` | floor of the state, raised by active events — a latched `EMERGENCY` stays `CRITICAL` even after its evidence clears |
| `active` | bool | unresolved hazard evidence exists *right now* |
| `latched` | bool | the `EMERGENCY` latch is held |
| `hazard` | object or `null` | worst active hazard: `kind`, `severity`, `source`, `message`, `location`, `raised_at`, plus `value` / `unit` / `confidence` from the matching current reading (`confidence` is set when `unit == "confidence"`, i.e. vision detections) |
| `latest_event` | object or `null` | most recently recorded audit event |
| … | | `blocks_motion`, `speed_scale`, `reasons`, `location`, `active_events`, `recent_events`, `events_recorded`, `counts_by_kind`, `sources`, `updated_at`, `enabled`, `status` — all verbatim from `snapshot()` |

Example (latched emergency, evidence still present):

```json
{
  "attached": true, "state": "EMERGENCY", "severity": "CRITICAL",
  "active": true, "latched": true, "blocks_motion": true, "speed_scale": 0.0,
  "hazard": {"kind": "FIRE", "source": "cam", "confidence": 0.95, "...": "..."},
  "reasons": ["flame detected (confidence 0.95)"], "...": "..."
}
```

### `POST /hazard/acknowledge`

Body optional (`{}` or empty). Performs **step 1 of the two-step release**
only — it calls `HazardManager.acknowledge()`:

* **It does:** clear the `EMERGENCY` latch and re-evaluate the layer. Evidence
  that is still present **re-latches immediately**, so acknowledging can never
  bypass an active hazard.
* **It does not:** reset the robot's `SAFETY_STOP` mode, start the motors, or
  delete audit events (`HazardManager.reset()` is deliberately not exposed).

Response: `{"ok": true, "acknowledged": true, "was_latched": …, "latched": …,
"state": …, "hazard": {…}}`. Rejected with `400` when no layer is attached or
the payload is not a JSON object.

Releasing an emergency therefore always takes both steps:

```
POST /hazard/acknowledge            → hazard latch released (if evidence gone)
POST /command {"cmd":"mode", ...}   → robot leaves SAFETY_STOP (unchanged path)
```

The panel shows a header badge (`HAZARD <state>`, blinking red when
`STOP`/`EMERGENCY`), a hazard card (state, severity, active, kind,
confidence, source, location, reason, timestamp) and an **Acknowledge** button
that appears only while `latched` is `true`.

---

## Threading model

* One background **control-loop** thread calls `mgr.tick()` at a fixed rate
  (default 5 Hz) — sensor polling, Pi-side watchdog, and STOP enforcement.
* HTTP handlers run on `ThreadingHTTPServer` worker threads.
* A single lock serialises `tick()`, command dispatch, and snapshot reads so a
  single-operator console always sees consistent state. (The warehouse task
  manager in a later phase uses the same lock discipline.)

Note: a manager that has **never** connected does not lock the mode to
`SAFETY_STOP` on its own — motion is blocked by the gate (`not connected to
controller`) instead. A real in-flight link loss still forces `SAFETY_STOP`
via the watchdog path.

---

## Camera / vision manager (Phase 11)

`amr/camera/camera_manager.py` is a thin facade over one of two backends:

| Backend  | Config `device` | Produces                          |
|----------|-----------------|-----------------------------------|
| libcamera (Raspberry Pi) | `"pi"` | JPEG bytes (`libcamera-still`) |
| V4L2 / OpenCV          | `"v4l2"` or index | `cv2` frames, encoded to JPEG on demand |

`MockCamera` (used by `--mock` and tests) produces deterministic JPEG frames
so the whole panel — including the live view — works with no hardware.

* `GET /camera` → `{"enabled", "available", "status", "device", "resolution",
  ...}`; `status` is `NOT_VERIFIED`/`ONLINE`/`OFFLINE`/`NOT_CONFIGURED`.
* `GET /image` → one frame as `image/jpeg`; **503** when the camera is absent
  or a capture fails.
* Every camera operation **degrades gracefully**: no camera, missing
  `libcamera-still`, or a failed capture never crashes the server — the panel
  simply shows a "camera unavailable" placeholder.

The manager is the single owner of the device; vision processing (markers,
QR codes, shelf recognition) will build on `capture()` / `capture_jpeg()` in
a later phase without touching the web layer.

---

## Tests

* `tests/test_web_server.py` — runs a real `ThreadingHTTPServer` on an
  ephemeral port against the full mock stack: mode gating, safety rejection,
  speed bounds, E-STOP, camera endpoints, and the C2 hazard contract
  (`GET /hazard` shapes, latched `EMERGENCY`, acknowledge **cannot** clear an
  active hazard, the two-step release, 400s for a missing layer / bad payload).
* `tests/test_camera_manager.py` — backends, `capture_jpeg` normalisation,
  graceful degradation.
