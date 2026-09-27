# Application Ecosystem Audit

Phase A of the unified-application work. Every row below was read out of the
source, not out of a document: the route table came from `do_GET` /
`do_POST` in `amr/web/server.py`, the view list came from `VIEW_SECTIONS` in
`command_center.js`, and the launch commands from `argparse` in `amr/main.py`.
Nothing here is a proposed URL — **invented URLs are the failure mode this
audit exists to prevent.**

Date of audit: against commit `1191bfd`, branch `main`, 1307 tests passing.

## What the system actually is

One Python process, one `ThreadingHTTPServer`, **stdlib only** (`http.server`,
no Flask/FastAPI, no build step, no CDN). Three HTML pages, ~18 JSON/binary
endpoints, one SPA.

```
python -m amr.main --mock --web   →  one server, every interface
```

This is the most important finding, because it constrains every later phase:
**there is no per-application backend to duplicate.** Any new client is a
consumer of endpoints that already exist. The suggested
`amr/web/command_center/`, `amr/web/map/`, `amr/web/dashboard/` directory
split from the brief does **not** match reality and was deliberately not
created — map, twin, camera, hazards, missions and replay are *views inside
one SPA*, not separately-served applications. Creating those directories would
have meant either fake empty packages or a second copy of the frontend.

## Existing pages (HTML)

| Application | URL | Entry point | Platform | Purpose | Reuse | Modify | Missing |
|---|---|---|---|---|---|---|---|
| Web control panel | `/` | `INDEX_HTML` in `server.py` | web | Original Phase-10 panel; the only page that sends motion commands | yes | minimal | — |
| Telemetry dashboard | `/dashboard` | `DASHBOARD_HTML` in `server.py` | web | Legacy C7/C11 3-panel console | yes | none | — |
| **AMR Command Center** | `/command-center` | `COMMAND_CENTER_HTML` + `amr/web/static/command_center.{html,css,js}` | web | Primary operator console, 12 views, read-only | yes | extend in place | — |

Only three HTML documents exist. Every other "application" in the request is
either a view of the Command Center or a JSON API.

## Command Center views (12)

From `VIEW_SECTIONS` / `VIEW_KEYS` in `command_center.js`. Each is deep-linkable
via URL hash (`/command-center#twin`) through `initViews()` → `fromHash()`, so
**cross-linking needs no new mechanism.**

`overview` · `twin` · `camera` · `map` · `mission` · `telemetry` · `safety` ·

## JSON / binary API

| Method | Route | Returns | Notes |
|---|---|---|---|
| GET | `/status` | JSON | full robot snapshot |
| GET | `/sensor` | JSON | one sensor poll + safety decision |
| GET | `/telemetry` | JSON | C7 telemetry document |
| GET | `/dashboard/state` | JSON | **the single consolidated feed** — telemetry + health + map + twin + events + `ops` (C5e) |
| GET | `/hazard` | JSON | pure read; never evaluates or clears |
| GET | `/map` | JSON | read-only map projection, world coords |
| GET | `/map.svg` | SVG | server-rendered map, `width`/`height`/`zoom` params |
| GET | `/digital-twin` | JSON | 3D twin derived from the same snapshot |
| GET | `/camera`, `/camera/status` | JSON | camera state; `{"available": false}` when none |
| GET | `/camera/frame`, `/image` | JPEG | single frame, 503 when no camera |
| GET | `/camera/overlay` | JSON | image-space overlay description |
| GET | `/replay/recordings`, `/replay/status` | JSON | replay listing / position |
| GET | `/health` | JSON | liveness + degradation summary |
| GET | `/static/<file>` | CSS/JS | strictly limited to the 3 known files (no path traversal) |
| POST | `/command` | JSON | **motion**: estop, stop, mode, forward, backward, rotate, turn |
| POST | `/hazard/acknowledge` | JSON | step 1 of two-step latch release; does not clear `SAFETY_STOP` |
| POST | `/replay/load` | JSON | load a recording |

No WebSocket and no SSE. The Command Center polls `/dashboard/state` at 1 Hz.
The brief's "do not introduce WebSockets for appearance" is honoured by leaving
this exactly as it is.

Note the one real asymmetry in the whole system: the Command Center is
read-only (it only ever issues `GET`), while the legacy `/` control panel is
the only client that posts motion. That distinction is the safety property the
rest of this work must not blur.

## Launch commands (real, from `argparse`)

| Command | Effect |
|---|---|
| `python -m amr.main --mock` | headless tick loop, no hardware |
| `python -m amr.main --mock --web` | web server + mock robot |
| `python -m amr.main --mock --web --mission-demo` | + live warehouse mission (**refused without `--mock`**) |
| `python -m amr.main --demo` | scripted sequence, exits |
| `--host` (default `0.0.0.0`), `--port` (default `8080`), `--config-dir` | bind + config |

## Documentation inventory

14 files in `docs/` (2,986 lines): `web_control`, `command_center`,
`dashboard_console`, `telemetry`, `digital_twin`, `map`, `camera`,
`camera_overlay`, `hazard`, `safety`, `mission_monitoring`, `replay`,
`replay_dashboard`, `serial_protocol`. Naming is **lowercase snake_case** —
new docs follow that, not the `UPPERCASE.md` names suggested in the brief.

## Configuration

`config/`: `robot.yaml`, `safety.yaml`, `serial.yaml`, `hazard.yaml`,
`warehouse.yaml`, `replay.yaml`, loaded by dataclasses in
`amr/utils/config.py`. **No `applications.yaml` exists** — Phase B adds it.

## Verified absent

Searched for `*.swift`, `*.kt`, `*.tsx`, `package.json`, `tauri*`, `*.apk`,
and for `mobile/ desktop/ app/ ios/ android/ apps/` directories: **none
exist.** There is no mobile client, no desktop client, no application registry,
no applications hub and no cross-application navigation. These are genuinely
new, not hidden.

## Toolchain actually installed (checked, not assumed)

| Tool | Present | Consequence |
|---|---|---|
| `node` / `npm` | yes | JS bundlers possible, but none needed |
| `cargo` / `rustc` | **no** | **Tauri cannot be built or verified here** |
| `adb` | **no** | no Android device/emulator path |
| `xcodebuild` | yes | iOS-capable, but needs a signing identity |

Any claim of a built `.app`, `.msi` or `.apk` would therefore be false. Desktop
binaries are reported as `BUILD NOT AVAILABLE`, which the brief explicitly
permits, rather than as working downloads.

## Consequences for later phases

1. **Registry** is derived from the route table above so it cannot drift, and a
   test asserts every registry URL is a route the server really serves.
2. **Applications hub** is a 4th HTML page on the same server, deep-linking into
   existing views rather than re-implementing them.
3. **Mobile / desktop** are consumers of `/dashboard/state`. No new business
   logic, no second data model.
4. **Safety**: the ecosystem must not weaken the one real distinction in this
   codebase — the Command Center is read-only, and motion lives solely on
   `POST /command`, behind the `RobotManager` → `SafetyManager` gates.
5. **Status honesty**: camera is `HARDWARE REQUIRED` until real hardware is
   attached; nothing is shown as operational merely because a route exists.

`sensors` · `hazards` · `replay` · `events` · `diagnostics`
