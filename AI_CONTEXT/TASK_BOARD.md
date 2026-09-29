# TASK_BOARD — shared work queue

**Legend:** `[ ]` available (unassigned) · `[~]` IN PROGRESS (do not take unless
assigned to you) · `[x]` done · `[!]` blocked (needs hardware or a decision)

**Rules**
1. Find an unassigned `[ ]` task whose **Touches** paths do not overlap another
   `[~]` task, and mark it `[~]` with your agent name + date **in the same commit
   that starts the work**.
2. Keep changes inside the listed paths. If you must touch shared code, note it
   in `HANDOFF.md`.
3. `TASK_BOARD.md` and `HANDOFF.md` are **shared** — edit them in your own
   commit, and re-read them before you commit (another agent may have pushed).

---

## A. Baseline — delivered before the hazard work

* `[x]` Phase 1–2 — serial protocol + Arduino firmware (watchdog, proximity stop)
* `[x]` Phase 3–5 — motor control, differential drive, safety manager (Layer 3)
* `[x]` Phase 6–7 — ultrasonic sensors + validation
* `[x]` Phase 8–9 — `RobotManager` gate, `RobotState`, mode state machine
* `[x]` Phase 10–11 — camera manager + stdlib web panel / JSON API
* `[x]` Phase 12–15 — navigation (odometry, waypoints)
* `[x]` Phase 16 — warehouse tasks, map, manipulator seam
* `[x]` Logging, typed YAML config + fail-fast validation, mocks, CI

## B. Delivered by the hazard session (see `HANDOFF.md` for the commit)

* `[x]` **Bootstrap `AI_CONTEXT/`** — this directory did not exist; all five
  documents are new and derived from verified repository inspection.
* `[x]` **Context-aware multi-hazard safety layer** — `amr/hazard/`
  (`types`, `sources`, `event_log`, `manager`, `__main__`), `config/hazard.yaml`,
  `HazardConfig` + validation, additive `RobotManager.attach_hazard()`,
  `tests/test_hazard.py` (48 tests), `docs/hazard.md`, offline demo.
  *Owner: cline · Status: code complete, unit-tested, hardware-independent.*

---

## C. Available tasks

### C1 — Verify hardware geometry and safety thresholds `[!]` blocked
**Touches:** `config/robot.yaml`, `config/safety.yaml`, `docs/safety.md`
Measure `wheel_track_m` / `wheel_diameter_m`; validate `watchdog_timeout_ms` and
the four stop distances; fill the `TODO_VERIFY` ultrasonic pins; flip `status` to
`VERIFIED` and record who/when/where.
**Blocked by:** physical robot access. Nothing else may claim autonomous
operation as trustworthy until this is done.

### C2 — Wire the hazard layer into the web panel and telemetry `[x]`
**Owner: Laptop 1 (Cline) · Started and completed: 2026-09-23**
**Touches:** `raspberry_pi/amr/web/server.py`, `raspberry_pi/amr/web/__init__.py`,
`raspberry_pi/tests/test_web_server.py`, `docs/web_control.md`,
`raspberry_pi/amr/main.py` (only to attach the layer when `hazard.enabled`)
Expose `GET /hazard` returning `HazardManager.snapshot()`, show the hazard state
in the panel's status area, and add an acknowledge endpoint that performs **only
step 1** of the two-step release (the mode reset stays separate). Do not bypass
`RobotManager`.
**Depends on:** B (done). **Risk:** low — additive endpoints.
**Done:** `GET /hazard` (snapshot + derived `attached`/`severity`/`active`/
`hazard`/`latest_event`), `POST /hazard/acknowledge` (latch release only, 400
when no layer), panel badge + hazard card + conditional Acknowledge button,
`attach_hazard_layer()` in `main.py` gated on `config.hazard.enabled`,
10 new tests (25 in `test_web_server.py`), suite **343 passed, 2 skipped**.

### C3 — Spatial hazard visualisation `[x]`
**Touches:** new `raspberry_pi/amr/hazard/` module or a small viewer script,
`docs/hazard.md`
Render recorded events (`read_events(path)` / `HazardManager.snapshot()`) onto the
warehouse map from `config/warehouse.yaml` (`assets/warehouse-map.svg` shows the
style). Pure read-side; must not touch the control loop.
**Done:** new `amr/hazard/visualisation.py` — `render_map_svg()` (deterministic
SVG: y-up projection, `STATE_COLORS` markers, dimmed resolved, emergency ring,
cluster fan-out, dashed zones, waypoint labels, XML escaping, side panel for
unlocated events) + `events_from_snapshot()` (active copies win, sorted) + CLI
`python -m amr.hazard.visualisation --events X.jsonl --out map.svg|-`; lazy
PEP 562 re-exports in `amr.hazard` (no runpy `RuntimeWarning`); 23 new tests,
suite **366 passed, 2 skipped**.

### C4 — Real gas / smoke sensor driver `[!]` blocked
**Touches:** `config/robot.yaml` (pins), new `raspberry_pi/amr/sensors/` module,
`config/hazard.yaml` thresholds
`GasSensorSource` already accepts any `reader()` callable; this task supplies the
real one and the wiring. **Blocked by:** sensor hardware + pin assignment.
Do not invent pins.

### C5 — Vision detector → VisionHazardSource → hazard event `[x]` (2026-09-24)
**Touches:** `raspberry_pi/amr/hazard/vision.py` (new), `types.py`, `sources.py`,
`manager.py`, `amr/utils/config.py`, `config/hazard.yaml`, `tests/test_vision.py` (new),
docs
Implemented a framework-independent vision→hazard pipeline:
`CameraFrame/VisionDetector` protocol → `VisionDetection` (validated contract) →
`VisionHazardSource` → existing `HazardManager` → `HazardEventLog` → C3 SVG → C2 web API.
Supported classes: PERSON/HUMAN, FIRE, SMOKE, OBSTACLE (mapped via one canonical
table; unknown classes are ignored, not invented). A deterministic
`SimulatedVisionDetector` (12 named scenarios) and a `python -m amr.hazard.vision`
demo ship for offline use. **No camera, ML model, or accuracy measurement is
claimed** — the detector is simulated input only. +95 tests (461 total).

### C6 — Activate obstacle avoidance (`TURN` / `REPLAN`) `[x]` (2026-09-24)
**Touches:** new `raspberry_pi/amr/safety/avoidance.py`,
`amr/navigation/navigator.py`, `amr/safety/safety_manager.py`,
`amr/utils/config.py`, `config/safety.yaml`, `tests/test_avoidance.py` (new),
`docs/safety.md`
Promoted the reserved `SafetyAction.TURN` / `REPLAN` to active policy via a pure,
config-driven `AvoidancePolicy` and an avoidance gate in `LocalNavigator`.
**No existing stop test was changed** — the pre-existing deterministic-stop
suite is untouched and still green. The safety argument rests on ordering: the
Layer-3 verdict is evaluated first and `STOP`/`WAIT` are returned unchanged
(TURN/REPLAN are never considered), a *critical* obstacle still blocks motion
through the pre-existing hazard → `RobotManager` path, and only a non-blocking
`WARNING` obstacle is avoidable. All manoeuvre commands still leave through the
single existing `command()` → `RobotManager` gate, so no second motor path
exists. Turns require a *proven clear* side (roomier side wins; no clearance
data ⇒ REPLAN rather than a guessed heading) and a per-episode `max_replans`
budget escalates to `NavStatus.FAILED`, so a persistent obstacle cannot loop.
Every hook defaults to `None`, so pre-C6 behaviour is unchanged when unwired.
**Software/simulation only** — no robot, camera, ultrasonic hardware or Arduino
was used; all `safety.avoidance` thresholds are NOT_VERIFIED and avoidance is
`enabled: false` by default. +76 tests (537 total).

### C7 — Digital-twin / monitoring foundation (telemetry + read-only dashboard) `[x]` (2026-09-24)
**Touches:** new `raspberry_pi/amr/telemetry/` package, `amr/web/server.py`,
`amr/main.py`, `tests/test_telemetry.py` (new), `tests/test_web_server.py`,
`docs/telemetry.md` (new), `docs/web_control.md`, `README.md`
New **read-only** `amr/telemetry/` package: a frozen `TelemetrySnapshot` contract
(schema-versioned) plus a `TelemetryCollector` that only *reads* existing public
state. Every section carries a `source` tag (`LIVE` / `SIMULATION` /
`UNAVAILABLE`) and **absent measurements serialise as `null` — never a
fabricated number** (no battery pack ⇒ `battery.percentage` is `null`, not 78).
Reuses the existing sources (`RobotState.to_dict()`, `HazardManager.snapshot()`,
`Navigator`, `WarehouseTaskManager`, `CameraManager.describe()`) instead of
shadowing them. Exposed as `GET /telemetry`, `GET /health`, `GET /dashboard` on
the **existing** `AMRWebApp` — no second HTTP server. **No motor path:** the
collector never calls `tick()` or any write method (asserted by tests spying on
`tick()` and the serial writes), and `POST /command` remains the sole control
path. +55 tests (592 total). All values simulated; no hardware used.

### C8 — Raspberry Pi camera monitor `[x]` complete (2026-09-24)
**Outcome:** camera abstraction shipped in `raspberry_pi/amr/camera/frame.py` —
frozen `CameraFrame` contract, `CameraStatus` (`LIVE` / `SIMULATION` /
`UNAVAILABLE` / `ERROR`), deterministic stdlib-PNG `SimulatedCameraSource`, and
a lazy-import `RaspberryPiCameraSource` (picamera2 → libcamera-still → V4L2).
Wired into C7 telemetry (`GET /camera/status`, `GET /camera/frame`) plus a
dashboard camera panel. **68 new tests; full suite 660 passed, 2 skipped.**
Also fixed a C7 honesty bug: a `MockCamera` was reported as `source: LIVE`.
**REAL CAMERA HARDWARE TESTED: NO** — no Pi camera was available; all coverage
is simulated or fault-injected. See `docs/camera.md`.
**Touches:** `amr/camera/`, `amr/web/server.py`, new streaming route, tests
A `CameraSource` → `CameraFrame` abstraction supporting both the SIMULATED and
REAL Pi camera without changing the dashboard. Show status/timestamp/source/
resolution; show `SIMULATION` or `CAMERA OFFLINE` when no real camera exists.
Tests must use a deterministic fake source — **no Pi camera required to run
the suite**.

### C9 — Live 2D warehouse map `[x]` complete (2026-09-25)
**Outcome:** shipped in `raspberry_pi/amr/map/` — `snapshot.py` (presentation-
independent `MapSnapshot`), `transform.py` (the single world→screen conversion
plus bounded `PathHistory`), `service.py` (`MapService` + deterministic SVG
renderer). Wired into the existing `AMRWebApp` as **`GET /map`** and
**`GET /map.svg`**, plus a live map card on `GET /dashboard` (scroll-zoom, drag-
pan, follow-robot, reset, label toggle — all read-only, riding the existing 1 Hz
poll). **111 new tests; full suite 771 passed, 2 skipped.**
Reuses the existing warehouse/navigation frame (metres, y-up, radians) and its
objects (`WarehouseMap`, `HazardZone`, `Navigator`, `HazardManager`,
telemetry) — no second navigation engine or coordinate system. The C5 hazard
placement rule is preserved: a hazard is placed only with a real world location;
image-space bboxes are listed under `unlocated` and never given coordinates.
**The project models no shelf/rack/obstacle/boundary geometry**, so the map
reports those as UNAVAILABLE with a visible note and fits its viewport to real
data instead of drawing an invented floor plan.
**REAL ROBOT / RASPBERRY PI / NAVIGATION HARDWARE: NOT TESTED** — software only.
See `docs/map.md`.

### C10 — 3D Digital Twin `[x]` (complete, C10)
**Touches:** new browser-based 3D view, reuses the C9 `MapSnapshot`
Browser 3D of the warehouse + AMR (chassis, wheels, sensors, camera). Robot
transform derives from `telemetry.position` / `telemetry.orientation`. **Purely
a visualisation layer — the 3D model must never control the robot.** C9's
`MapSnapshot` is presentation-independent precisely so this can consume it
directly instead of re-deriving map state.

**Delivered:** `amr/map/twin.py` derives `DigitalTwinState` from the C9
`MapSnapshot`; `GET /digital-twin` and a "3D Digital Twin" dashboard card
render it with raw WebGL (no Three.js, no npm, no build step, no new
dependency). World→3D conversion is centralised in Python and unit tested.
Read-only: no POST route, no actuation controls, and a source-level test
proves the twin module references no control or communication code. See
`docs/digital_twin.md`.

### C11 — Telemetry panel `[x]` (complete, C11)
**Touches:** dashboard frontend
Robot / navigation / safety / battery / sensor panels. Display only sensors that
actually exist; show `NOT AVAILABLE` rather than a fabricated value.

**Delivered:** `amr/telemetry/console.py` assembles the existing C7 telemetry +
C9 map + C10 twin + C7 health into one read-only `GET /dashboard/state`, and the
dashboard gains a global operations status bar plus robot / mission / goal+route /
safety / battery / sensors / system-health panels. No new telemetry schema and no
second state engine: the `map` and `twin` keys are the untouched C9/C10 payloads,
asserted equal to their standalone endpoints. The 1 Hz poll is preserved and now
issues one request per tick instead of four. C11 also made the JavaScript syntax
check permanent (`node --check` on the served scripts) after the C10 dashboard-wide
break. See `docs/dashboard_console.md`.

### C12 — Mission monitoring `[x]` (complete, C12)
**Touches:** telemetry collector, `ManagerStatus`, dashboard mission panel
Mission → PICKUP → NAVIGATE → AVOID → ARRIVE → DROP → RETURN, with mission id,
current task, destination, progress, completed and failed counts. Integrates
with the existing warehouse simulation.

**Delivered:** the headline finding is that the mission telemetry section had
**never worked**. Three defects in `TelemetryCollector._mission()` meant it
always reported `UNAVAILABLE`: it tested `isinstance(status(), dict)` while
`WarehouseTaskManager.status()` returns a `ManagerStatus` object; it read
`current_task` when the real key is `current`; and it read a `mission_id` that
no runtime produced. All three are fixed, and the reader accepts either an
object or a plain dict so hand-rolled doubles keep working.

`ManagerStatus` gained three additive, display-only fields (`mission_id`,
`destination`, `total_tasks`) supplied by the caller — never invented — and
`MissionTelemetry` gained `destination`, `total_tasks`, `mission_progress`
(completed/submitted) and `task_progress` (reusing the single existing
`_goal_progress` helper). `mission_phase()` derives the roadmap's phase
narrative from the real task type plus real travel progress, and is overridden
by safety: TURN/REPLAN show `AVOID`, STOP/WAIT show `HELD`, E-stop shows
`EMERGENCY`. Unknown progress is never read as arrival. A mock-only
`--mission-demo` flag lets the panel show a live mission. Display only: no
actuation endpoint, and a test proves mission reads write nothing to the
transport. See `docs/mission_monitoring.md`.

### C13 — Hazard visualisation in the dashboard `[x]` (complete, C13)
**Touches:** dashboard frontend, reuses C5/C3 hazard pipeline
Show PERSON / FIRE / SMOKE / OBSTACLE on the 2D map with class, confidence,
severity, source, timestamp and location **only when actually supplied**. An
image-space bbox must NOT be converted to world coordinates — bboxes stay in
the camera view (with class + confidence overlay), never on the map.

**Delivered:** `amr/camera/overlay.py` (display-only) turns the bbox C5 already
stores in hazard metadata into `GET /camera/overlay`, which the dashboard draws
as SVG rects 1:1 over the camera image. It reuses the existing validated
`VisionBoundingBox` — no second box type — and `OverlayBox` has no world field
at all. The payload declares `space: "image"`, `units: "pixels"` and
`world_transform: null`, because the project stores no camera calibration.
Events sort into four distinct buckets: drawable `boxes`, `world_located` (map,
never image), `without_bbox`, and `other_source`.

Two real findings: (1) C5's named scenarios had **no bbox at all**, so four
deterministic bbox scenarios were added without altering the original twelve;
(2) a **pre-existing config bug** — `config/robot.yaml` puts `camera:` as a
sibling of `robot:`, but the loader read only `robot.camera`, so every shipped
camera setting had always been silently ignored. Fixed, with a regression test.

Camera identity is explicit (`CameraConfig.camera_id`) because a frame's
`source` is a backend name while a detection's `source` is a camera identity;
painting one camera's detections onto another's image would be a lie, so a
mismatch is recorded rather than drawn. Read-only: no POST route, and a
source-level test proves the overlay imports no serial/GPIO/threading code.
Tests: 973 passed, 2 skipped, 0 failed (910 at C12 + 63). Hardware NOT tested.
See `docs/camera_overlay.md`.

### C14b — Dashboard replay controls `[x]` (complete, C14b)
**Touches:** dashboard frontend, replay routes, config
Record timestamp, pose, navigation/safety state, hazards and mission; replay a
previous run with PLAY / PAUSE / RESTART and 0.5x / 1x / 2x speed. Very useful
for demonstrations. Playback sequence must be deterministic.

**Delivered:** `amr/telemetry/replay_control.py` adds `RecordingStore`
(read-only discovery + validated loading) and `ReplayController` (replay state:
NO_RECORDING / READY / PLAYING / PAUSED / FINISHED / ERROR). The C14 engine was
**not modified** — C14b only consumes `ReplayPlayer`.

**Single tick honoured:** replay is advanced inside the web app's *existing*
`_control_loop` via `replay.tick(interval)`; the browser only reads where
playback reached, from the same `poll()` it already used. A test asserts the
dashboard page still has **exactly one** `setInterval`, and the C14
no-thread/no-clock rules are untouched.

**Security:** a client sends a `recording_id`, never a path. Separators, `..`,
absolute paths, hidden names, NUL and non-strings are refused, and the joined
path must sit inside the configured directory. New `config/replay.yaml` with
`recordings_dir: null` mirrors the `event_log_path: null` convention — the panel
stays visible and reports "no recordings directory configured" instead of
pretending to be broken.

**A regression this milestone caught:** two pre-existing C9 tests assert the
dashboard HTML never mentions the actuator endpoint; my first draft broke both
with the words "never reach /command" in a *comment*. The tests were right, so
the prose was reworded and the invariant is now asserted a third time.

Routes (all display-only, replay branch returns before `/command`): GET
`/replay/recordings`, `/replay/status`; POST `/replay/load|play|pause|restart|
speed|unload`. Zero actuator writes verified end to end over real HTTP.
Tests: 1100 passed, 2 skipped, 0 failed (1032 at C14 + 68). Hardware NOT
tested. See `docs/replay_dashboard.md`.

### C14c — Automatic telemetry recording `[x]` (complete, C15 session)
**Touches:** `amr/telemetry/auto_record.py`, `amr/web/server.py`, `config/replay.yaml`

> **Naming note:** the C15 *session brief* called this "C15 — auto-recording",
> but `C15` was already taken on this board by the unified demo (below). It is
> recorded here as **C14c** because it completes the C14 recording chain and
> depends on it. The unified demo keeps the C15 slot.

Closes the recording loop. `AMRWebApp._control_loop` — the loop that already
ticked the robot and already advanced C14b replay — now also feeds the
authoritative C7 telemetry snapshot to `AutoRecorder`. That completes the
lifecycle: LIVE → RECORD → DISCOVER → LOAD → REPLAY.

- **One snapshot, two consumers:** the *same* `TelemetryCollector.snapshot()`
  feeds the live dashboard and the recorder. No second collection path.
- **Lifecycle:** started in `app.start()`, finalised in `app.stop()` — no
  truncated file on shutdown, verified line-by-line.
- **Storage:** the same directory `RecordingStore` reads, so an auto recording
  is discoverable by `GET /replay/recordings` with **no conversion step**.
- **Naming:** `run-<YYYYmmdd-HHMMSS>.jsonl`; a collision suffix is added rather
  than overwriting a previous run.
- **Timestamps:** C14's rule is preserved — a snapshot with no usable timestamp
  is skipped, never back-dated to inflate the frame count.
- **Failure isolation:** a recorder that raises (e.g. `OSError: disk full`) is
  logged and the control loop keeps running; a test proves the loop survives.
- **Config:** `replay.auto_record` + `replay.recordings_dir`, both shipped so the
  **default records nothing** (`recordings_dir: null`).
- **Safety:** read-only. Zero actuator writes (asserted with `NoActuation`).

Deliberately **not** added: no recording thread, no second loop, no second
timer, no queue/async pipeline. Source-level tests assert exactly one
`_control_loop` and one `_stop_evt.wait(interval)` in the server.

Tests: 1127 passed, 2 skipped, 0 failed (1100 at C14b + 27). Hardware NOT
tested. See `docs/replay_dashboard.md`.

### C15b — Real camera backend `[x]` (complete)
**Touches:** `raspberry_pi/amr/camera/detector.py` (new),
`raspberry_pi/amr/camera/frame.py`, `amr/camera/__init__.py`,
`amr/hazard/sources.py`, `amr/hazard/vision.py`, `amr/main.py`,
`raspberry_pi/tests/test_camera_backend.py` (new)

Stage A of the vision work: **real camera acquisition** behind the existing
`VisionDetector` protocol, with object-detection inference deliberately left
unwired.

    camera backend -> CameraFrame -> VisionDetector -> VisionDetection
                   -> VisionHazardSource -> HazardManager -> safety/nav

Delivered:

* `CameraFrameDetector` — a `VisionDetector` that pulls a frame from any
  `CameraSource` and maps an optional `inference(frame)` callable onto the
  existing C5 `VisionDetection` contract. **No ML dependency added**: with no
  callable it reports `inference_configured: false` and yields no detections,
  which is honest rather than pretending to see.
* `VisionHazardSource(frame_provider=...)` — accepts a frame-based detector
  alongside the pre-existing zero-arg callback and pre-materialised sequence
  forms, so no second class was needed.
* `build_camera()` / `build_frame_detector()` in `amr/main.py`.

**Bugs found and fixed while integrating:**

1. `build_camera` read `cam_cfg.width` / `cam_cfg.height`, which
   `CameraConfig` does not have — it stores `resolution` as `"1280x720"`. The
   configured resolution was silently discarded and every camera opened at the
   640x480 fallback. `parse_resolution()` now parses it and is unit tested,
   including malformed input.
2. `RaspberryPiCameraSource.describe()` reported `UNAVAILABLE` with **no reason**
   until someone called `start()`, so the dashboard could not explain itself.
   It now probes (a cached import attempt) when reporting an unavailable state.
3. A `VisionDetector` **object** is not callable, so an object detector was
   being treated as an iterable of detections. The source now honours the
   protocol's `.detect` method.

**Tests:** 47 in `tests/test_camera_backend.py`. Full suite **1204 passed, 2
skipped, 0 failed** (1157 → +47).

**Hardware: NOT TESTED.** No `picamera2` on the development machine; the Pi
backend degrades to `UNAVAILABLE` with reason `picamera2 unavailable: No module
named 'picamera2'`, verified live. The Pi Camera V2 8MP also needs a 15-pin →
22-pin adapter for the Raspberry Pi 5's smaller connector, and that has not been
done. No inference model is bundled or benchmarked.

---

### C15 — Unified demo `[x]` (complete)
**Touches:** `raspberry_pi/amr/demo.py`, `amr/main.py`, `amr/web/server.py`,
`amr/robot/robot_manager.py`, `amr/telemetry/collector.py`,
`raspberry_pi/tests/test_unified_demo.py`

One deterministic, offline demonstration that exercises the completed stack
through its **real** interfaces — nothing is re-implemented for the demo:

    mission -> navigation -> simulated vision -> hazard -> safety
            -> navigation change (TURN) -> mission continues -> completion
            -> automatic recording -> discovery -> replay

Entry point: `python -m amr.demo` (exits non-zero if any stage did not happen).
The existing `--mock` / `--demo` flags of `amr.main` are untouched; the demo is a
separate module because it owns its recording directory and its own pacing.

**Components:** `WarehouseTaskManager`, `LocalNavigator`, `HazardManager` +
`VisionHazardSource`, `VisionDetection`, `AvoidancePolicy`, `TelemetryCollector`,
`AMRWebApp._tick_once`, `AutoRecorder`, `RecordingStore`, `ReplayPlayer`.

**Only two demo adapters** (both labelled SIMULATION): `ScriptedVisionDetector`
(a step-indexed script, because the existing `SimulatedVisionDetector` returns a
*fixed* scenario and cannot express "appears part-way through") and
`SimulatedClearance` (a constant open-side feed, for a source the project does
not have yet).

**Determinism:** driven by a step counter, fixed `dt` and a virtual clock; no
randomness. Two runs give identical timelines, hazard event ids, avoidance
actions, frame counts and a byte-identical CLI report. The demo deliberately does
*not* call `app.start()` (which would spawn the background loop thread and break
determinism); it drives the same `AMRWebApp._tick_once` the thread calls, which is
why the loop body was extracted into that method. Still exactly one
`_control_loop` and one `_stop_evt.wait(interval)`.

**Coordinates (C13 rule preserved):** the detection carries a pixel bbox and no
world pose, so the box stays in event metadata and the hazard is never placed on
the map. Both facts are printed and asserted.

**Actuation:** the mission genuinely drives the *mock* robot, so the transport
records wheel commands. Rather than claim a misleading "0 writes", the report
separates: physical writes **0**, demo direct actuator calls **0**, and every
wheel command through the single `RobotManager` gate. `POST /command` untouched.

### C15 bug found: hazard telemetry was silently always UNAVAILABLE
`TelemetryCollector._hazard()` gated on `snap.get("attached")`, but
`HazardManager.snapshot()` has never emitted an `attached` key — that is a C2
*web payload* field. The condition was always false, so the hazard section of
every telemetry snapshot **and every recording** reported `UNAVAILABLE`: hazards
were invisible in `/telemetry` and in replay. Same class of mistake as the C12
mission-section defects. Fixed; the demo now proves the hazard reaches telemetry
and the recording. No existing test pinned the buggy behaviour.

Tests: 1157 passed, 2 skipped, 0 failed (1127 at C14c + 30). Hardware and
firmware NOT tested. See `docs/replay_dashboard.md` (C15 section).

### C16 — Real manipulator (gripper / arm) `[ ]`
**Touches:** `raspberry_pi/amr/warehouse/tasks.py` (implement `Manipulator`),
`config/warehouse.yaml` (`manipulator` backend name)
Replace the `mock` backend. Keep `MockManipulator` for tests.

### C17 — RFID `[ ]`
**Touches:** new module + `config/`, tests
Not started anywhere in the repo. Define a reader interface, integrate with the
warehouse task manager for shelf/payload identification.

### C18 — ROS 2 bridge `[ ]`
**Touches:** new `ros2/` package, docs
**Not present today.** Must be optional: the core stack must keep importing with
no ROS installed. Publish `RobotState` / `HazardStatus`, subscribe to goals.
A natural consumer of the C7 telemetry snapshot, but it must not become a
control path of its own.

### C19 — Housekeeping `[x]` (done by the hazard session)
* Fix the stale `docs/architecture.md` link in `docs/safety.md` — **done**, now
  points at `AI_CONTEXT/ARCHITECTURE.md`. The same stale reference in
  `raspberry_pi/amr/logging/logger.py` was fixed too.
* `README.md` row/mention for `amr/hazard`, `config/hazard.yaml`,
  `docs/hazard.md`, `AI_CONTEXT/`, and a new roadmap item (6) — **done**.
* README badge / test counts — **done**: `333 passed, 2 skipped` (superseded by
  C2: now `343 passed, 2 skipped`).

---

### C15c — AMR Command Center `[x]` (complete)
**Touches:** `raspberry_pi/amr/web/static/` (new, 3 files),
`raspberry_pi/amr/telemetry/series.py` (new), `amr/web/server.py`,
`tests/test_command_center.py` (new), `tests/conftest.py`,
`tests/test_web_server.py`, `docs/command_center.md`, `README.md`

A real browser operator console at `GET /command-center`: 3D twin, live camera,
2D map, robot status, safety, mission, telemetry charts, filterable event log
and record/replay — a **view** over the existing backend, not a second robot.

Two things genuinely did not exist before:

1. **Bounded history** (`amr/telemetry/series.py`) — a fixed-length time-series
   buffer and a change-driven event stream, filled inside the *existing* control
   loop from the same telemetry snapshot everything else reads. Server-side on
   purpose, so a long-running Pi never grows its heap and the charts and event
   log cannot disagree.
2. **Real static files** — the console is HTML/CSS/JS on disk instead of Python
   strings, served through a whitelist so `/static/../../etc/passwd` 404s.

No new dependency, no framework, no build step: the 3D view is hand-written
WebGL and the charts are 2D canvas, both built into every browser.

**Honesty properties tested, not just documented:** a missing value is never
`0`; `NaN`/`inf`/bool are not numbers; no timestamp means no sample; a camera
bbox stays image-space and is labelled as such in the UI; a missing camera
produces no detections; `SIMULATION` is never shown as `LIVE`; replay never
overwrites live telemetry.

**Tests:** 53 new in `tests/test_command_center.py`. Full suite **1257 passed,
2 skipped, 0 failed** (1204 before). The `web` / `web_no_camera` fixtures moved
to `conftest.py` so both suites drive the *same* running app.

**Hardware / firmware: NOT TESTED.** Mock and simulated data only; no physical
robot, camera, sensor or motor controller.

---

## C5d — [x] Command Center visual verification + hardware-ready UI

**Goal:** make the Command Center visibly *work* — robot that drives, camera
panel that lights up, map/twin/mission/telemetry/replay all updating live — and
verify it by looking at it rather than trusting a 200.

**Two real defects were found by watching the demo** (neither was visible to
any existing test):

1. **Camera-panel deadlock.** The panel only requested `/camera/frame` when
   telemetry said `has_frame`, but `has_frame` only becomes true *after*
   something reads a frame — so the panel could never light up. The frame is now
   requested whenever the camera is not `UNAVAILABLE`/`ERROR`, with `onerror`
   collapsing back to an honest empty state.

2. **The AMR oscillated instead of driving.** `run_web` ran its own 1 Hz loop
   calling `mgr.tick()` and `mission.process(dt=1.0)` while the server's
   `_control_loop` was already ticking at 5–10 Hz. The robot was integrated
   twice and the planner's clock ran 5–10× too fast, so the goal outran the
   robot (`x: -0.2 → -0.32 → 0.17 → 0.41`). Fixed by stepping the mission from
   the **existing** `_tick_once` with the loop's own `interval`; `run_web` now
   only keeps the process alive. `AMRWebApp._run_warehouse` was a dead flag
   (set, never read) and is now backed by a real reference.

   Measured after: **0** in-leg direction reversals, steady 0.50 m step,
   7.12 m round trip, arrives at the dock, phase `COMPLETED`.

**Verification performed:** all 11 endpoints over real HTTP (200, correct
content types, `/camera/frame` → `image/png`), then every render function
executed against a real `/dashboard/state` payload via a DOM shim — 15 render
paths OK, no `TypeError`. Confirmed: `hw-text = SIMULATION`, `r-batt = n/a`,
map SVG carries real geometry, twin model has 4 wheels + camera + sensor, the
camera overlay draws a bbox labelled `1 (image-space)`, 12 event-log rows.

**Tests:** 4 new (`TestMissionRidesTheControlLoop`). Full suite **1261 passed,
2 skipped, 0 failed** (1257 before).

**Safety:** unchanged. `/command` remains the only actuator path; the console
issues only GETs plus the pre-existing replay routes; `read_only: true`.

**Hardware / firmware / camera: NOT TESTED.** The Pi Camera V2 8MP still needs a
15-pin → 22-pin adapter for a Pi 5.

---

## Phase C — Applications Hub wired into the server `[x]` (complete, 2026-09-27)

**Goal:** make the Phase-B registry *reachable*. Expose it over HTTP and put it
in front of an operator, without widening the one real safety boundary in this
codebase — `POST /command` stays the sole actuator path and everything else
reads.

**Delivered**

* `GET /applications` — a 4th HTML page on the same server
  (`amr/web/static/applications.{html,css,js}`), read once at import and served
  from the same whitelist as the console's assets. It renders
  `GET /applications/state` and deep-links into existing views instead of
  re-implementing them.
* `GET /applications/state` — `ApplicationRegistry.payload(RuntimeContext)`,
  where the context is derived from the running process: `mock_mode` from the
  existing C7 `simulated` flag, `camera_available` from a single
  `is_available()` probe (a camera that raises answers "unavailable" rather
  than 500-ing the hub), `server_running` from whether this app is serving.
* `AMRWebApp(applications=...)` — injectable, loaded once at construction. A
  missing `applications.yaml` yields an empty hub, not a boot failure.
* Command Center integration: a topbar icon link and a sidebar link to
  `/applications`, as plain anchors (leaving the console is not a `setView()`
  transition).
* `config/applications.yaml` gains the hub's own card (`applications_hub`,
  `reference`, `AVAILABLE`) — deliberately the one entry that stays AVAILABLE in
  mock mode, because the page makes no claim about the robot.

**Verification performed — live HTTP against the mock stack**

| Observation | Result |
|---|---|
| `GET /applications` | 200 `text/html`, 4108 B, contains `Applications Hub` |
| `GET /applications/state` | 200 `application/json`, `count: 16`, 8 categories |
| `GET /static/applications.{css,js}` | 200 `text/css` 6156 B · `application/javascript` 12347 B |
| `/command-center` | 200, two links to `/applications` (topbar + sidebar) |
| Mock robot, no camera | `command_center → MOCK / mock-robot`; `camera_monitor → HARDWARE REQUIRED / no-camera` |
| **Mock camera attached** | `camera_monitor` still **HARDWARE REQUIRED** (reason becomes `declared`) — statuses are never promoted |
| Clients | `mobile_client → NOT INSTALLED`, `desktop_client → BUILD NOT AVAILABLE`, both `url: null` → rendered as “API — no interface”, never as dead links |

**Tests:** `tests/test_applications_hub.py` (25 new) + one in
`tests/test_app_registry.py`. Full suite **1359 passed,
2 skipped, 0 failed** (1333 at Phase B).

**Follow-up fix — the hub was invisible from the pages people open.** The only
link to `/applications` was on the Command Center. The two surfaces a session
actually starts on — `/` (the legacy control panel) and `/dashboard` (the older
read-only monitor) — had none, so from either one the directory could not be
found. All four HTML pages now link it:

| Page | Link to the hub |
|---|---|
| `/` | header nav pill (alongside a Command Center pill) |
| `/dashboard` | header nav pill **and** a footer line |
| `/command-center` | topbar icon + sidebar link (already there) |
| `/applications` | footer nav: console, `/dashboard`, `/`, raw JSON |

The nav links are **anchors, not fetches**: `/` and `/dashboard` never request
`/applications/state`. `/dashboard` deliberately gets **no** console link, because
that page keeps the invariant that the actuator endpoint's path never appears in
its source and the console route begins with that substring — a constraint that
already caught the explanatory comment written alongside it.

Live check against the mock stack: all four pages 200, `dead links: none`.
Covered by `test_every_page_links_to_the_hub`,
`test_the_hub_links_back_to_the_other_pages`,
`test_nav_links_are_anchors_not_fetches` and
`test_every_link_on_the_hub_actually_resolves`.

**Links that resolve but land in the wrong place.** The route test strips the
fragment and checks the path, because the server never sees a hash. The browser
does, and `fromHash()` silently falls back to `overview` for a name it does not
recognise — so a typo'd `#mapp` would be a link that opens the console on the
wrong view with no error anywhere. `test_every_fragment_is_a_view_the_console_
actually_has` now checks every fragment against `VIEW_KEYS` read out of the
*served* console script (a restated list would be a second thing able to go
stale). Verified by mutation: changing `#map` to `#mapp` fails the test with the
known view list in the message. Following all 13 openable cards the way a
browser does: every one lands correctly, `silent-wrong deep links: none`.

**Safety:** unchanged. The hub issues exactly one GET; a source-level test
asserts the page has no `POST`, no `<form>` and no `/command` path and that
every link on it points at a read-only destination, and
`test_hub_reads_never_actuate` proves over the mock transport that neither route
writes an actuator line.

**Doc debt found:** `AI_CONTEXT/CURRENT_STATUS.md` still records the 1261-test
C15c snapshot and section 5 still claims there is "no live dashboard" — it is
stale and queued for a refresh.

**Hardware / firmware / camera: NOT TESTED.** Everything above is mock and
simulated data.

---

## Full-project health pass `[x]` (2026-09-28)

A whole-project audit rather than another feature: baseline, wiring, and a real
boot of the application (not a test fixture).

**Method.** Full suite; `compileall` over `amr/`; orphan scan (every module
imported by production code or tests — **none**); `python -m amr.main --mock
--mission-demo --web` booted as a subprocess and all 20 routes exercised live.

**Two real defects found and fixed.**

1. **Logging was silently dead.** `main.py` called `setup_logging(console=False)`
   with no `log_dir`, so `if log_dir:` never ran and `console=False` skipped the
   other branch — installing **zero** handlers. A logger with no handlers
   discards every record without complaint. `_default_log_dir()` existed,
   honoured `AMR_LOG_DIR`, and was **never called by anything**. Proven by
   running the real app before the fix: no `logs/` directory was ever created.
   Fixed by making `log_dir=None` mean *the default directory* (opt out
   explicitly with `log_dir=False`), and by having `main.py` report a failure to
   stderr instead of swallowing it.
2. **Rotated logs were not git-ignored.** `*.log` does not match `amr.log.1`, so
   now that logging actually writes, a robot left running would commit its own
   logs. `.gitignore` now excludes `logs/`.

**Two features added where a gap was demonstrated, not invented.**

3. **`GET /health` now reports logging state** —
   `{"active", "file", "writable", "level", "detail"?}`. A fix nobody can observe
   is a fix that can silently regress. `active: false` means output is being
   discarded, and `detail` explains an unwritable file (observed for real when a
   log directory was deleted under a running process).
4. **`log_event` is now actually used.** It is documented in `ARCHITECTURE.md`
   with the format `COMMAND MOVE L=150 R=150`, but no production code called it,
   so that format appeared in no log at all. `RobotManager._apply` — the single
   choke point for every motion command — now emits it, tagged per action, with
   the **commanded** speed (what the controller was sent, after hazard scaling)
   rather than the requested one.

**Also documented:** README gained a *Logs* section (where the log is,
`AMR_LOG_DIR`, the grep format, and the `/health` check). It had none before.

**Suite: 1370 passed, 2 skipped, 0 failed.** Live e2e: all 20 routes 200, hub
count 16, no dead links, no deep link landing on the wrong view.

**Hardware / firmware / camera: still NOT TESTED.** `hazard.enabled: false` in
`config/hazard.yaml` is deliberate and stays false; `/hazard` reporting
`attached: false` is honest, not a defect.

---

## Web UI: light mode was decorative, not functional `[x]` (2026-09-28)

Asked for "a better frontend". The design system was already good — tokens,
focus rings, skip links, a reduced-motion guard, and a written rule that colour
is never the only signal. So this did **not** rewrite it. Inspecting the shipped
CSS instead found the real problem: **the light theme was broken**, and no test
looked at the CSS at all.

### Defects found by inspecting, not by reading

1. **Light mode rendered dark panels on a white page.** `body.light` set only
   `--bg/--panel/--text/--dim/--line`. `--card`, `--card-2`, `--bg-2` and
   `--muted` kept their dark values, so every card and chip stayed near-black
   over a near-white background. Fixed by overriding **all 27** colour tokens.
2. **`--panel` was a typo'd token** — referenced twice as
   `var(--panel, #0f1622)` and declared nowhere. The fallback is why it never
   looked broken: a wrong token renders as if it worked. Now `--card-2`.
3. **Status colours ignored the theme.** `.st-HEALTHY`/`timeline`/`alerts` carried
   their own literals (`#34d399`, `#e8a33d`, `#38bdf8`) that matched the old
   `--ok`/`--warn` but did not follow them.
4. **`st-NOT_TESTED` shared a colour with `st-CRITICAL`.** "Not verified" and
   "broken" are opposites, and the file's own header says every colour means one
   thing. `NOT_TESTED`/`IDLE` now read as attention-needed, not as quiet neutral.
5. **Canvas and SVG cannot use `var()`.** The charts, the 2D map and the camera
   badge were drawn with literal hexes, so they kept the dark palette after a
   switch. Added a cached `token()` reader, invalidated per theme change.
6. **A theme switch only repainted the 3D twin** — charts and map kept the old
   colours until a full reload. `applyTheme()` now resets the token cache and
   repaints all three.
7. **Neither page consulted `prefers-color-scheme`,** so the OS setting was
   ignored entirely and a phone in light mode opened a dark console. Both pages
   now follow the OS when no explicit choice is stored, and still honour one.

### Also

* Light-mode status colours darkened to clear **WCAG AA (4.5:1)**. The dark
  palette's `#2fbf71` on white is ~2.1:1 — unreadable as text, and these are read
  as text by an operator.
* `TestTheming` (5 tests) makes all of the above structural: both palettes must
  declare the same colours, no `var()` may reference an undefined token, no
  component rule may hardcode a colour, drawn colours must come from `token()`,
  and both pages must follow the OS. **Each was verified to fail** when the
  original bug is reintroduced — a test that cannot fail is not a test.

**Suite: 1376 passed, 2 skipped, 0 failed.** Live e2e unchanged: 20/20 routes
200, hub 16, no dead links. **Rendering was not verified in a real browser** —
no engine is available here (`playwright` absent), so the checks are structural
plus a live HTTP fetch of the assets. That is a real limitation, stated plainly.

---

## Applications: Wi-Fi / Bluetooth connectivity `[x]` (2026-09-28)

Three new hub cards and a real read-only probe behind them. The design question
was not "how do we draw a Wi-Fi card" but **"what can we honestly say is
connected?"** — and the answer had to survive a machine with no radio at all.

### The central distinction

These report the radio of the **host running the process**, not of the robot.
The AMR has no radio of its own in this codebase, so a card implying "the
robot's Wi-Fi" would be fiction. What can honestly be said is whether the
machine the operator is talking to is reachable — which is exactly what makes
the console stop working. So `requires_robot: false` on all three, and a test
pins that.

### What it actually measures

`amr/net/connectivity.py` reads `/sys/class/net` (Linux, where the Pi runs),
with a portable `socket` fallback elsewhere. **stdlib only** — a test greps the
module to assert it never imports `subprocess` or names `nmcli`/`bluetoothctl`,
because shelling out would add an external, version-dependent dependency to a
probe that must never fail.

Honesty rules, each with a test:

* **`UNAVAILABLE` ≠ `DISCONNECTED`.** No wireless hardware and a dead link are
  different operator problems and are reported differently, with a `note`.
* **SSID is always `null`.** Reading one needs a privileged ioctl; a
  plausible-looking network name would be a fabrication the operator cannot
  distinguish from a real reading.
* **`paired_devices` is `null`, never `0`.** `0` says "we looked and found
  none"; `null` says "we did not look". No scan is run, so only the second is
  true. Discovery is privileged and disruptive, and running it from a
  read-only endpoint would make the web layer an actuator.
* **Loopback is never read as a radio.** `lo` is always up and says nothing.
* **A failed poll is not a down link** — the console says the probe failed and
  leaves the last reading visible.

### Deliverables

* `GET /connectivity` (read-only; POST returns 404/405, asserted) and
  `AMRWebApp.connectivity()`.
* Command Center view `connectivity` — tab, panel, 5 s poll, 1 Hz robot state
  untouched. A re-entrancy guard stops `renderAll` (1 Hz) and the self-
  rescheduling timer from stacking into two probe chains a second.
* Three registry cards: **AVAILABLE** (overview), **PARTIAL** (`wifi_link` —
  SSID and signal are genuinely not measured, so AVAILABLE would oversell),
  **HARDWARE REQUIRED** (`bluetooth_link` — never run against a real adapter).

Statuses were chosen to be unflattering where that is the truth. The tempting
value in every case was the higher one.

**Suite: 1400 passed, 2 skipped, 0 failed** (+24). Live e2e: 20/20 routes, hub
now **19** applications, every deep link resolves to a real view.

**Not tested on real hardware.** macOS has no `/sys/class/net`, so the verified
path is the `UNAVAILABLE` degradation plus fixture-driven sysfs trees
(`tests/test_connectivity.py`, 14 tests). A Pi with a real `wlan0`/`hci0` is
**NOT TESTED** — the sysfs parsing is written against the documented kernel
format but has never met a real adapter.

---

## Web performance: measured, not guessed `[x]` (2026-09-28)

Asked to "make the site stable and fast". **Profiled before changing anything**,
and the measurement contradicted the assumption: the server was never the
bottleneck.

**Baseline (real `python -m amr.main --mock --mission-demo --web` subprocess):**
every route p50 ≤ 1.4 ms, worst p95 6.4 ms, 8 concurrent clients at **394 req/s**
with zero errors. The backend was fine. The waste was in the *transport*.

### What was actually wrong

| Problem | Cost |
|---|---|
| stdlib default **HTTP/1.0** | every response closed the socket — a console page load paid 5 TCP handshakes |
| **no gzip anywhere** | 135 KB of assets shipped as-is every load |
| static assets sent `no-store` | browser re-downloaded 62 KB of JS on every visit |
| `json.dumps` default separators | 13 KB of extra whitespace in a 1 Hz feed |

### What changed

1. **`protocol_version = "HTTP/1.1"`** → keep-alive. Safe only because every
   response already sets a correct `Content-Length`; without one the client
   waits for a close that never comes. Asserted live, not read off the class.
2. **gzip**, above a 512-byte floor (below it, the header + two CPU passes cost
   more than they save). `Vary: Accept-Encoding` always, and **`gzip;q=0` is
   honoured** — compressing for a client that asked not to be given it wastes
   CPU that is contended with the control loop on a Pi.
3. **Static assets pre-compressed once at import.** Their gzip is a constant;
   recomputing it per request is pure waste. `mtime=0` keeps the bytes
   identical across runs so the ETag stays valid.
4. **ETag + 304** and **`immutable` caching** for assets that change only when
   the process restarts. Safe here because the asset URLs carry no version
   query and the server restarts to pick up edits.
5. `json.dumps(..., separators=(",", ":"))` for the polled feeds.

### Measured result

| Page | Before | After | Cut |
|---|---|---|---|
| Command Center first paint | 124,242 B | **37,134 B** | **70%** |
| Applications Hub first paint | 63,996 B | **19,062 B** | **70%** |
| `/dashboard/state` on the wire | 12,807 B | **3,288 B** | 74% |
| worst p95 latency | 6.4 ms | **2.5 ms** | |
| 8-client throughput | 394 req/s | **680 req/s** | +73% |

The before-numbers were taken by `git stash`-ing the change and re-running the
*same* benchmark, so the comparison is like-for-like rather than remembered.

### Guarded, not just applied

`TestTransportPerformance` (9 tests) pins each property, because every one of
these failures looks like "the page still works" while silently costing every
operator the bandwidth: gzip offered/resused, `Content-Length` matching the
bytes actually sent, `q=0` refused, live state still `no-store` while assets are
`immutable`, 304 carrying no body, keep-alive on the wire, and the static
whitelist still blocking path traversal. **Each was verified to fail** when its
defect is reintroduced.

One caught by writing it: my first `_accepts_gzip` used `continue` inside the
parameter loop, so `gzip;q=0` was *accepted*. The mutation test is what exposed
it — the test that mattered most was the one aimed at the subtlest branch.

Also removed `raspberry_pi/_e2e_conn.py`, a scratch benchmark accidentally
committed in 9c3e924.

**Suite: 1409 passed, 2 skipped, 0 failed** (+9). Live e2e unchanged: 20/20
routes, hub 19, no dead links.

**Not measured:** real LAN/Wi-Fi throughput, RTT, or behaviour on a Pi — this
is localhost on a Mac. The gains are byte-counts and handshakes, which are
host-independent, but on-device performance is **NOT TESTED**.

---

## Applications Hub: clickable entry points + runnable demos `[x]` (2026-09-28)

Asked for a link you can click to reach the AMR web app, with instructions. The
Hub already existed at `/applications` with 19 entries, so the work was not
"add a page" — it was closing the gap between the README's eight run commands
and anything clickable.

### What was actually missing

* The five CLI demos (`amr.demo`, `amr.warehouse`, `amr.hazard`,
  `amr.hazard.vision`, `amr.hazard.visualisation`) were in the README and
  **nowhere else**. They are not pages, so they could never be a card, and
  nothing in the UI mentioned them.
* The README's instructions were prose on GitHub, not a page in the app.

### What changed

1. **New `demo` registry category** (`CATEGORIES` + the "a card with no URL is
   dead" validation). A demo is a command you run, not a page you open, so it is
   exempt from needing a URL — but that exemption is only sound while every entry
   in it really has a `launch_command`, which is asserted.
2. **Five demos registered with commands that were executed, not copied.** All
   five run and exit 0; the output line each produces is quoted in its
   description, so the card's claim is checkable. One README claim needed
   checking: `amr.demo` is a *module* (`demo.py`), not a package, so
   `python -m amr.demo` works while a naive `__main__.py` check would say it
   does not exist. The test accepts either form.
3. **A "Start here" card at the top of the Hub**: three numbered steps, the
   `--mock` warning, and the demo list with a **copy-to-clipboard** button each.
   Rendered from `/applications/state`, so a command that changes in
   `applications.yaml` changes on the page — a hand-typed copy in the HTML would
   have drifted from the README with nothing to catch it.
4. **Copy works on plain `http://`**, which is the actual deployment. The
   `navigator.clipboard` API needs a secure context, so a Pi serving over LAN
   would have had dead buttons; the `execCommand` textarea fallback is the path
   that really runs there. Off-screen rather than `display:none`, since a hidden
   element cannot be selected and the copy fails silently.
5. **README "See it work"** now leads with the one command and a table of
   clickable links, and states plainly that they only work while the server is
   running and that `localhost` must become the Pi's address off-box.

### Verified

`test_app_registry.py` gained 4 tests: the demo set is pinned, demos must be
commands with no URL and must be read-only, every command must name a module
that exists **on disk** (not by importing, which would run them), and every demo
must say it is simulated. The last one is the safety-adjacent one — a demo that
quietly touched hardware would be the most dangerous documentation error in this
project: an operator copies it expecting a simulation and gets a moving robot.

Live check against a live server: `/applications` 200 with the Start-here card
and demo container present, **24 applications** (19 + 5 demos), all five commands
served, `demo` present in `categories`.

**Suite: 1413 passed, 2 skipped, 0 failed** (+4). Live e2e unchanged.

**Not tested:** the copy button was not clicked in a real browser — no engine is
available here. The markup, the wiring and the JS syntax are verified; the actual
clipboard round-trip is **NOT TESTED**.

---

## Bug: "sites are not working" — the README's first command was a trap `[x]` (2026-09-28)

Reported as broken links. **The server was never broken** — every route returned
200 — so the cause had to be outside the code, and the first instinct (a blank
page from a JS error) was wrong. Ruled out by measurement: all four links
served, `/applications/state` returned 24 apps, and `logs/amr.log` had zero
errors or warnings.

### Root cause

The README's own instructions do not work on a fresh machine:

```
$ python3 -m amr.main --mock --web
ModuleNotFoundError: No module named 'yaml'
```

`pyyaml` and the other dependencies live in `raspberry_pi/.venv`, not in the
system Python. Every run command in the README said `python -m amr.main`, and
the `pip install` step existed only much further down under "Installing &
running". So a new user followed the first thing the README told them, hit a
stack trace, and reasonably concluded the sites were broken. My own instructions
from the previous session made this worse: I added a table of links *above* the
install step, so the very first clickable thing in the README assumed an
environment the reader did not have yet.

Worth recording what was **not** the cause, since two plausible theories were
tested and rejected: stdout buffering (a line-buffered print to a pipe survives
`SIGTERM`; proven with a control experiment) and a hidden exception in
`run_web` (in-process tracing shows the banner prints correctly and
`AMRWebApp.start` returns the bound port).

### Fixes

1. **README "See it work" leads with the install** (`python3 -m venv .venv`,
   `source .venv/bin/activate`, `pip install -e ".[dev]"`) and *then* the run
   command, naming the exact error a user would otherwise hit.
2. **Stated the two conditions that make a link fail**, which are invisible from
   a browser: the server must still be running (`Ctrl-C` stops it), and
   `localhost` must become the Pi's IP when opening from a phone. Also
   `--port 8090` for when 8080 is taken.
3. **A troubleshooting block inside the Hub page itself**, collapsed by default.
   Someone staring at a dead link needs the answer where they are looking, not in
   a different file. It names the real error, the localhost swap, the port
   conflict, and the hard-refresh for stale cached CSS.

### Guarded

Two new tests, both **verified to fail** when their defect is reintroduced:

* `test_readme_publishes_links_that_are_real_routes` — scrapes every
  `http://localhost:8080/...` link in the README and checks each against the
  server's own dispatch chain. Caught a typo'd link when mutated.
* `test_readme_says_how_to_install_the_dependencies` — the install block must
  precede the first runnable command, compared *inside code fences* so the prose
  that names the error is not mistaken for a command. Caught when the blocks
  were swapped.

The second test initially passed against a broken README because my mutation
regex never matched; the second attempt was a no-op that also passed. Only a
direct line-swap proved it had teeth — a reminder that a test which has never
been observed failing is not yet a test.

**Suite: 1415 passed, 2 skipped, 0 failed** (+2). Live check of the exact user
path: all four published links 200, all troubleshooting entries present, all
static assets 200.

---

## Bug: the startup banner was never printed `[x]` (2026-09-28)

Second pass on "sites are not working", and the previous fix was **incomplete**.

### The first pass was wrong about one thing

Last session I concluded buffering was "not the cause" and said so in the task
board. That conclusion came from a control experiment that was **invalid**: both
trials shared a single code string ending in `sys.stdout.flush()`, so the
"without flush" case flushed everything anyway and both reported 69 bytes. A
control that cannot fail proved nothing. Redone with one code string per trial
and `SIGTERM` instead of a clean exit:

```
print(), SIGTERM             ->   0 bytes captured
print(flush=True), SIGTERM   ->  57 bytes captured
```

Buffering **was** the cause.

### The real defect

`main.py` printed `AMR web control: http://...` with no `flush=True`. Measured:
**0 bytes** on stdout — even at process exit — while the `get_logger("main")`
line *immediately after it* appeared in `amr.log` correctly.

Python block-buffers stdout (~8 KB) whenever it is not a TTY, so the banner sat
in the buffer and was discarded when the process was signalled rather than
exiting. This hits precisely the deployment this project targets: a Pi over
SSH, under systemd, or with `nohup`. In an interactive terminal stdout is
line-buffered and it always worked — which is exactly why it survived, because
**the only way to see this bug is to not be on a TTY**, and every developer runs
it on one.

The README said "open the printed URL". On the intended hardware, nobody was
ever shown a URL.

### Fix

`flush=True` on every banner print, plus the two URLs an operator actually wants
(`/command-center` and `/applications`) and a note about swapping `localhost`
for the machine's IP when the bind address is not loopback.

Measured under the exact condition that hid it (stdout redirected, not a TTY):
**0 → 167 bytes**, and all four links it advertises return 200.

### Guarded, and the test was wrong first

`tests/test_startup_banner.py` (2 tests) starts the server with stdout on a
pipe, `SIGTERM`s it, and asserts the banner names a real route; a second test
fetches every URL the banner advertises.

The first mutation I tried **removed only the first `flush=True` and the test
still passed** — the remaining prints share one stdout buffer, so any one
`flush` flushes them all. Stripping all of them gives 0 bytes and the test
fails, which is what finally proved it had teeth. Recorded because the first
"verified" claim would have been false.

**Clean-room test** (`/tmp/cleanroom.sh`, not committed): fresh venv, README
commands typed verbatim, then every published link fetched. **PASS** — install
exit 0, banner printed, 24 applications, all links 200. That is the check that
would have caught the original `ModuleNotFoundError`, and it caught this one too
by flagging `banner: MISSING`.

**Suite: 1417 passed, 2 skipped, 0 failed** (+2).

---

## CI: a green build was saying nothing about the site `[x]` (2026-09-28)

Asked to check GitHub. CI was **green** on the last commit — all four jobs,
Python 3.10/3.11/3.12 plus ruff. But green was not evidence of the thing that
was actually broken, and inspecting the workflow showed why:

```
$ grep -c 'amr.main' .github/workflows/ci.yml
0
```

**No CI job had ever started the web server.** The suite is hardware-free *and*
server-free: every test drives the app in-process. So a passing build could not
distinguish a working site from a completely unreachable one — which is exactly
the class of defect that shipped twice in a row and reached the user.

### Added: a `smoke` job that runs the documented user path

Installs dependencies the way the README says, launches the server, and then
asserts the things a person depends on:

* the URL is **printed** (non-interactive stdout, so a missing `flush=True`
  loses the banner entirely — the bug from the previous commit);
* every link the README publishes returns 200;
* `/applications/state` parses as JSON with a non-zero count, and
  `/dashboard/state` and `/connectivity` return real payloads rather than an
  error page.

Runs on Ubuntu with no TTY, which is also how a Pi runs it under systemd or SSH
— the condition that hid the banner bug in the first place.

### Verified to fail on the real defects

Not just "it passes". Reverting the banner fix makes the job exit 1 with
`::error::no URL was printed; the operator is told to open one` — the CI job
would now have caught the bug that shipped as 6997613. Breaking a route makes
it fail on that path. YAML validated: 3 jobs, 4 steps each.

**Suite unchanged at 1417 passed, 2 skipped** (CI-only change).

### Follow-up: the status document itself had drifted

While verifying, the per-file table in `CURRENT_STATUS.md` turned out to be
wrong in four places: `test_connectivity.py` and `test_startup_banner.py` were
absent entirely, and `test_command_center.py` (57 → 63) and
`test_web_server.py` (86 → 101) were stale. The "Test files" line also claimed
37 against a real 36 — a number I had *guessed* with `sed` in the previous
commit rather than measured.

Regenerated from a measured collection, and
`test_current_status_test_counts_are_not_stale` now re-derives every count from
`pytest --collect-only` on each run, so the table cannot go quiet-fictional
again. **Verified to fail** both for a wrong count and for a deleted row — and
it caught the `sed` guess the moment it was written.

**Suite: 1418 passed, 2 skipped, 0 failed** (+1).

---

## Showcase: a public page that had quietly become fiction `[x]` (2026-09-28)

Continuing rather than starting something new, and looking for what was
*inconsistent* rather than for new work. Two real finds in `showcase.html`.

### It claimed 276 tests. The repo had 1418.

The first number in the file was **276** — a snapshot from many phases ago —
while the badge beside it in `README.md` said something different entirely. A
visitor's first impression of the project's rigour was a stale figure, and
nothing could notice, because no test had ever read this file.

### It was a different design language from the app

```
showcase:  --bg #0b0f18   --acc #4da3ff   --ok #2ecc71   --err #e74c3c
app:       --bg #0b0f16   --accent #22d3ee  --ok #2fbf71  --crit #ef4d5a
```

Different background, different accent, and an `--ok`/`--err` pair that matched
**nothing** in the running console. Someone who read the showcase and then opened
the Command Center saw two different products. The showcase now uses the app's
token names and values, with every remaining literal replaced by a token.

Also: a "Run it" block with the venv + install + start commands, a row for the
24 live interfaces, and an explicit **NOT TESTED** line for hardware in both the
status table and the footer — the showcase is public, so an unverified claim
there is the worst place for one.

### Guarded

`test_showcase_does_not_go_quietly_stale` and
`test_showcase_and_app_share_one_palette` compare the badge, the status table
and eight colour tokens against a measured collection and the app's own CSS.
**Both verified to fail** on the original defects: restoring the 276 claim fails
the first, restoring `#0b0f18` fails the second.

One correction made while writing them: the badge reports *passed*, not
*collected* (1420 vs 1422 — two camera tests skip without opencv/numpy). Counting
skips would overstate what ran, so the test subtracts them explicitly.

**Suite: 1420 passed, 2 skipped, 0 failed** (+2).

---

## Legacy pages: the last two surfaces that looked like a different product `[x]` (2026-09-29)

Continuing the palette thread to its end. The showcase was fixed last round, but
the two embedded pages served from `amr/web/server.py` still carried their own
`:root` blocks — and they had drifted from each other *and* from the app:

```
panel:      --bg #0f1420   accent #4da3ff   --ok/--err matched nothing
dashboard:  --bg #0e1420   --ok #3fb950     (its own green, again matching nothing)
app:        --bg #0b0f16   accent #22d3ee   --ok #2fbf71
```

The fix is substitution, not copy-paste: one `_PALETTE_CSS` block (the Command
Center's own token values, plus `--stage` for map/twin/camera views that stay
dark in both themes and `--btn`/`--well` for the legacy component surfaces) is
injected into both documents at import time, and every style literal outside
the palette block now reads via `var(--x)`. JS-drawn surfaces (SVG map strokes,
overlay colours arriving from `KIND_COLORS`) cannot use `var()` by construction
and are deliberately out of scope — the Command Center already documents this in
its `token()` bridge.

### Guarded

`test_embedded_pages_share_the_command_center_palette` compares ten tokens value
by value, asserts the old per-page roots are gone, and asserts both `<style>`
blocks are token-only. **Verified to fail twice**: restoring the old panel
accent fails it, and sneaking one hardcoded literal back into a style fails it.

Full suite **1421 passed, 2 skipped** (+1); live e2e 4/4 pages 200 with the new
palette present in every document.

---

## Legacy pages: the light half of the palette, and a switch to reach it `[x]` (2026-09-29)

The round above unified the *dark* palette and left it there. Both embedded pages
had no light theme at all — not one `prefers-color-scheme` query, no light rule,
zero occurrences of either. So "one palette" was true of one theme: an operator
who chose light in the Command Center opened `/` or `/dashboard` and fell back
into a dark page, with no switch on the page to get out again.

The fix adds the light half to the same `_PALETTE_CSS` block (`:root.light`,
carrying the Command Center's `body.light` values verbatim) and one shared
`_THEME_BOOT_JS` stub that both pages substitute.

Two decisions worth recording, because both are traps:

* **`:root.light`, not `body.light`.** An alias is substituted on the element
  that declares it, so `--panel:var(--card)` declared on `:root` keeps the *dark*
  card once `--card` is overridden on `body` — the pages would have looked right
  in dark mode and silently wrong in light. Keeping the override on the same
  element as the aliases removes the question, and lets the stub run in `<head>`
  so the class lands before first paint rather than flashing dark first.
* **`--btn-hover` on `.navlink:hover` had to stop using `--on-crit`.** The dark
  hover surface carried white text fine; the light one is a pale tint, where
  white would have been invisible. It now uses `--acc`, which reads on both.

A third finding came out of writing the test rather than reading the CSS: the
palette's `--stage` was *already* the console's `#060a11`, and a misread of a
column-aligned dump led to "fixing" it to `#0b0f16` — a value the console does
not use for a stage anywhere. The new test caught that in one run.

### Guarded

`test_embedded_pages_light_theme_matches_the_console` asserts three things:
every literal in the dark palette is restated for light (aliases excepted by
value, `--on-crit` by name and with its reason); the values match the console's
in **both** themes, with minimum counts so a dropped token cannot quietly shrink
what is compared; and the stub shares the `amr-theme` key and the OS query with
`command_center.js`. It also caught an edit that accidentally swallowed the
`def` line of `test_current_status_test_counts_are_not_stale`, which had merged
two tests into one — the count landed back at 42 and looked fine.

The move to a `<head>` script also invalidated four test slices that read
`DASHBOARD_HTML` from the first `<script>` to the last `</script>`: that meant
"the dashboard's script" only while a page shipped exactly one. They now select
it explicitly via new `_dashboard_script()` / `_page_script()` helpers, so a
future script cannot be folded into a rule about the dashboard.

Full suite **1422 passed, 2 skipped** (+1); live e2e 4/4 pages 200, no stale
palette literals on the wire, and `node --check` clean on both scripts per page.

---

## D. Do not take (owned / in progress)

* None currently. Check `HANDOFF.md` for live ownership before starting.

## E. Blocked on hardware (do not start expecting to verify)

C1, C4, and any firmware change under `firmware/arduino/` — CI has no Arduino
toolchain, so those cannot be tested in this environment.
