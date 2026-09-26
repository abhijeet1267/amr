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

## D. Do not take (owned / in progress)

* None currently. Check `HANDOFF.md` for live ownership before starting.

## E. Blocked on hardware (do not start expecting to verify)

C1, C4, and any firmware change under `firmware/arduino/` — CI has no Arduino
toolchain, so those cannot be tested in this environment.
