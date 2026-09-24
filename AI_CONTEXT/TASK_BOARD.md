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

### C5 — Fire / human detection model `[ ]`
**Touches:** new module under `raspberry_pi/amr/camera/` or `amr/hazard/`,
tests
Implement a detector returning `[(HazardKind.FIRE, confidence), ...]` to feed
`VisionHazardSource`. Must degrade gracefully with no camera and must not become
an import-time dependency (no OpenCV/ROS at import).

### C6 — Activate obstacle avoidance (`TURN` / `REPLAN`) `[ ]`
**Touches:** `raspberry_pi/amr/safety/safety_manager.py`, `docs/safety.md`,
`tests/test_safety_manager.py`
Promote the reserved `SafetyAction.TURN` / `REPLAN` from reserved to active
policy. **Risk: high — this changes Layer-3 stop behaviour.** Must keep the
existing deterministic-stop tests green and add coverage for the new actions.

### C7 — Real manipulator (gripper / arm) `[ ]`
**Touches:** `raspberry_pi/amr/warehouse/tasks.py` (implement `Manipulator`),
`config/warehouse.yaml` (`manipulator` backend name)
Replace the `mock` backend. Keep `MockManipulator` for tests.

### C8 — RFID `[ ]`
**Touches:** new module + `config/`, tests
Not started anywhere in the repo. Define a reader interface, integrate with the
warehouse task manager for shelf/payload identification.

### C9 — ROS 2 bridge `[ ]`
**Touches:** new `ros2/` package, docs
**Not present today.** Must be optional: the core stack must keep importing with
no ROS installed. Publish `RobotState` / `HazardStatus`, subscribe to goals.

### C10 — Housekeeping `[x]` (done by the hazard session)
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
