# HANDOFF — latest session

> **Read this before starting work.** Then re-read `TASK_BOARD.md` (it is shared
> and another agent may have added to it).

---

## Session: C7 — dashboard foundation (read-only telemetry + monitoring API)

**Agent:** cline · **Branch:** `main` ·
**Baseline when started:** `1833eee` (clean tree) · **Full suite:** **592 passed, 2 skipped, 0 failed**
**Feature commit:** `3870c8a`

### 1. What was completed

**C7 — dashboard foundation.** A new **read-only** `amr/telemetry/` package, a
schema-versioned telemetry snapshot, three new HTTP routes on the *existing*
web server, and a minimal self-contained dashboard page.

```
existing runtime → TelemetryCollector → TelemetrySnapshot → /telemetry /health /dashboard
                  (reads only)                            (no motor path)
```

* **New `raspberry_pi/amr/telemetry/types.py`** — frozen dataclasses: `DataSource`,
  `Vector3`, `Orientation`, `Velocity`, `NavigationTelemetry`, `SafetyTelemetry`,
  `HazardTelemetry`, `BatteryTelemetry`, `SensorTelemetry`, `MissionTelemetry`,
  `CameraTelemetry`, `SystemTelemetry`, `TelemetrySnapshot`, `HealthReport`.
* **New `raspberry_pi/amr/telemetry/collector.py`** — `TelemetryCollector` +
  `snapshot()` / `health()`; **reads only** public state of the existing managers.
* **New `GET /telemetry`, `GET /health`, `GET /dashboard`** on the existing
  `AMRWebApp` (C2) — **no second HTTP server**, no new port, no build step.
* **55 new tests** (46 `test_telemetry.py` + 9 in `test_web_server.py`).
* **Docs:** new `docs/telemetry.md`; updated `docs/web_control.md`, `README.md`,
  `AI_CONTEXT/` (task board, architecture, status).

### 2. The two rules C7 had to honour

**No second control path.** The collector performs reads only: it never calls
`tick()`, `request_mode()`, or any write method, and holds no Arduino/GPIO/PWM
handle. Tests assert this by spying on both `RobotManager.tick()` and the mock
serial transport's recorded writes. `POST /command` remains the only way to move
the robot and is unchanged by C7.

**No fabricated data.** Every section carries a `source` tag — `LIVE`,
`SIMULATION`, or `UNAVAILABLE` — and a measurement that does not exist is
`null`, never a plausible-looking number. There is no battery pack, so
`battery.percentage` is `null` (not `78`); there is no capture pipeline, so
`camera.fps` is `null`; there is no LiDAR, so there is no LiDAR field. The
dashboard renders `NOT AVAILABLE` / `SIMULATION` badges for those rows.

### 3. Bugs found and fixed while building C7

Building the collector against the real runtime surfaced three genuine contract
mismatches, all fixed (no existing test was changed to hide them):

1. `_sensors` and `_safety` read keys that `RobotState.to_dict()` never
   produces (`safety_action`/`safety_reasons`; the real key is `safety`, plus
   `SafetyManager.last_decision`).
2. `Navigator.plan()` requires a goal argument, so the naive read silently
   swallowed a `TypeError` and the route was always empty. The route is now
   derived from the active goal.
3. The `plan`/`route` path never reported the actual planned polyline.

### 4. Tests

| Command | Result |
|---|---|
| `cd raspberry_pi && python -m pytest tests/test_telemetry.py` | 46 passed |
| `cd raspberry_pi && python -m pytest tests/test_web_server.py` | 34 passed |
| `cd raspberry_pi && python -m pytest` | **592 passed, 2 skipped, 0 failed** |

The 2 skips are the pre-existing camera tests that need `opencv-python`/`numpy`.

### 5. What C7 deliberately does NOT do

No live camera stream (C8), no interactive 2D map (C9), no 3D twin (C10), no
mission/hazard UI panels beyond plain JSON (C11–C13), no recording/replay (C14).
The C7 dashboard is a minimal status page on purpose — the data architecture is
the deliverable, and each later milestone reads this one snapshot rather than
keeping its own copy of robot state.

### 6. Files changed (6 new, 6 modified)

| Path | Change |
|---|---|
| `raspberry_pi/amr/telemetry/types.py` | **New**: the frozen telemetry contract |
| `raspberry_pi/amr/telemetry/collector.py` | **New**: read-only `TelemetryCollector` |
| `raspberry_pi/amr/telemetry/__init__.py` | **New**: package exports |
| `raspberry_pi/tests/test_telemetry.py` | **New**: 46 tests |
| `docs/telemetry.md` | **New**: contract, API, safety boundary |
| `raspberry_pi/amr/web/server.py` | Collector wiring + `/telemetry`, `/health`, `/dashboard` |
| `raspberry_pi/amr/main.py` | Constructs the collector; passes `simulated=args.mock` |
| `raspberry_pi/tests/test_web_server.py` | +9 tests for the new routes |
| `docs/web_control.md` | C7 section + test list |
| `README.md` | Badge/count 537→592, module + doc rows, API table |
| `AI_CONTEXT/TASK_BOARD.md` | C7 marked `[x]`; monitoring roadmap C8–C15; legacy C8–C10 renumbered to C17–C19 |
| `AI_CONTEXT/ARCHITECTURE.md` | §10 telemetry layer, API surface, extension point |

### 7. Handoff integrity

| Commit | Contents |
|---|---|
| (feature) | `feat(dashboard): add read-only telemetry foundation` — telemetry package, web routes, tests, docs |
| (this commit) | `docs(ai-context): record C7 commit hash` — the `AI_CONTEXT/` files |

Resolve the live hash with `git rev-parse HEAD` (also mirrored in
`AI_CONTEXT/CURRENT_STATUS.md`). **Verified at commit time:**
`python -m pytest` → 592 passed, 2 skipped, 0 failed.

---

## Session: C6 — activate obstacle avoidance (`TURN` / `REPLAN`)

**Agent:** cline · **Branch:** `main` · **Date:** 2026-09-24 ·
**Baseline when started:** `7a169fa` (clean tree, = `origin/main`) ·
**Tests:** 461 → **537 passed, 2 skipped, 0 failed**

### 1. What was completed

**C6 is fully implemented, tested and documented.** The reserved
`SafetyAction.TURN` / `REPLAN` are now *active* policy. Previously they were
declared but never produced; now a non-blocking obstacle can produce them.

The safety argument rests on **ordering, not on thresholds**:

1. `SafetyManager.evaluate()` runs the original rules (now factored into
   `_check_base()`) **first**. A `STOP` or `WAIT` is returned unchanged and the
   avoidance policy is never even called.
2. Only when the base verdict is `PROCEED` *and* an `AvoidancePolicy` is
   supplied may an obstacle upgrade the action.
3. A *critical* obstacle never reaches C6: the hazard layer raises `STOP` and
   blocks motion through the pre-existing hazard → `RobotManager` path.
4. So the only thing C6 ever acts on is a **non-blocking `WARNING` obstacle**.

* **New `raspberry_pi/amr/safety/avoidance.py`** (357 lines) — pure, config-driven
  and side-effect free: `ObstacleSide`, `ObstacleReport`, `AvoidanceAction`
  (`NONE`/`TURN`/`REPLAN`/`STOP`), `AvoidancePolicy.decide()`, and
  `report_from_hazard()` (adapts a `HazardStatus` to obstacle evidence).
* **`LocalNavigator`** gained an opt-in avoidance gate. Manoeuvre commands leave
  through the **single existing `command()` callback** — no second motor path.
* **`SafetyManager.evaluate()`** gained three keyword-only, all-`None` params
  (`avoidance`, `obstacle`, `clearance`). The old 2-arg call signature still works
  and returns a byte-identical result.
* **Config:** `AvoidanceConfig` in `amr/utils/config.py` + `safety.avoidance`
  block in `config/safety.yaml`, **`enabled: false` by default**.
* **76 new tests** in `tests/test_avoidance.py` (738 lines, all offline).

Explicitly **not** done: no sensor/hardware wiring, no ultrasonic clearance
provider, no `RobotManager` auto-wiring of the policy, and **no pre-existing stop
test was modified** — the deterministic-stop suite is untouched and green.

### 2. Files changed (11, new + modified)

| Path | Change |
|---|---|
| `raspberry_pi/amr/safety/avoidance.py` | **New**: policy, report, action types (357 lines) |
| `raspberry_pi/tests/test_avoidance.py` | **New**: 76 tests (738 lines) |
| `raspberry_pi/amr/navigation/navigator.py` | Opt-in avoidance gate; committed turn; replan budget |
| `raspberry_pi/amr/safety/safety_manager.py` | `_check_base()` split; keyword-only avoidance params |
| `raspberry_pi/amr/utils/config.py` | `AvoidanceConfig` + nested `load_config()` build |
| `config/safety.yaml` | `safety.avoidance` block, `enabled: false` |
| `docs/safety.md` | New C6 section: ordering guarantee, turn/replan rules, limits |
| `README.md` | Test count 461 → 537 |
| `AI_CONTEXT/CURRENT_STATUS.md` | Counts, module row, honest test-status rows |
| `AI_CONTEXT/ARCHITECTURE.md` | Layer-3 row notes the C6 policy + gating order |
| `AI_CONTEXT/TASK_BOARD.md` | C6 `[ ]` → `[x]` with the full safety argument |

### 3. Tests

| Command | Result | Status |
|---|---|---|
| `python -m pytest tests/test_avoidance.py` | **76 passed** | ✅ software |
| `python -m pytest` (full suite) | **537 passed, 2 skipped, 0 failed** | ✅ software |
| `python -m pytest tests/test_safety_manager.py` | 14 passed, unchanged | ✅ no regression |
| `python -m pytest tests/test_navigation.py` | passed, unchanged | ✅ no regression |
| `python -m amr.warehouse` | `completed=3 failed=0`, exit 0 | ✅ no regression |
| `python -m amr.main --mock` | exit 0 | ✅ no regression |
| `python -m py_compile` on all changed modules | clean | ✅ |
| **Robot on floor / obstacle avoidance** | **not run** | ❌ **hardware-dependent** |
| **Arduino firmware** | **untouched, not flashed** | ❌ **firmware-dependent** |

The 2 skips are the pre-existing camera tests needing `opencv-python`/`numpy`.

**One observed transient failure (unresolved, disclosed).** During this session a
single full-suite run reported `1 failed, 536 passed` without naming the test in
the captured output, and it did **not** reproduce in 13 subsequent full runs
(`tests/test_web_server.py` alone: 12/12 clean). No sleeps, `time.time()`,
`perf_counter`, `random` or `uuid` assertions exist anywhere in `tests/`, and
`amr/safety/avoidance.py` imports no time/random/uuid — so C6 is deterministic
by construction. The only external resource in the suite is the real
`ThreadingHTTPServer` on an ephemeral port (pre-existing, from C2), the most
plausible source of a rare transient. **C6 touched no HTTP or timing code.**
Recorded rather than hidden; if it recurs, capture the full `FAILED` line.

### 4. Coverage of the 12 required areas

| # | Area | Where |
|---|---|---|
| 1 | Evidence reaches the decision layer | `TestEvidenceReachesDecisionLayer` |
| 2 | Obstacle triggers `TURN` | `TestTurn` |
| 3 | Obstacle triggers `REPLAN` | `TestReplan` |
| 4 | Normal navigation unchanged | `TestNormalNavigationUnchanged` |
| 5 | E-stop overrides `TURN` | `TestStopPriority` |
| 6 | E-stop overrides `REPLAN` | `TestStopPriority` |
| 7 | Malformed evidence doesn't crash | `TestMalformedEvidence` |
| 8 | Low-confidence policy | `TestLowConfidence` |
| 9 | No uncontrolled command loops | `TestLoopGuard` |
| 10 | C2 / C3 / C5 + warehouse compatibility | `TestCompatibility` |
| 11 | Determinism (repeatable runs) | `TestDeterminism` |
| 12 | Config / validation | `TestConfig` |

### 5. Documented policy decisions (deliberate, not accidental)

* **A turn needs a *proven clear* side.** With no clearance data, or with both
  sides blocked, the policy returns `REPLAN` — it never guesses a heading.
  The roomier side wins when both are open.
* **Confidence is never re-thresholded or rescaled by C6.** That gate belongs to
  the hazard layer (C5). C6 honours whatever actionable reading reaches it.
* **Loss of information degrades conservatively.** An obstacle provider that
  raises ⇒ no evidence. A clearance provider that raises ⇒ `REPLAN`, not a turn.
* **`max_replans` is per obstacle *episode*.** When the obstacle clears the
  budget resets; exhaustion reports `NavStatus.FAILED` with `"exhausted"`.
* **A `STOP` arriving mid-turn preempts immediately** and commands `(0, 0)`.

### 6. Known issues / limitations

* `safety.avoidance.*` values are **NOT_VERIFIED** conservative software
  defaults. `turn_speed_scale`, `turn_duration_s` and `open_clearance_m` have
  **never been measured on a robot**.
* Avoidance is **`enabled: false`** by default and **not yet wired** into
  `RobotManager`/`main.py` — a caller must pass the policy explicitly.
* No clearance provider ships with C6; `clearance` arrives as a plain dict.
* No obstacles have been physically detected or avoided. No camera, ultrasonic
  or Arduino hardware was exercised in this session.

### 7. Recommended next task

**C7 — real manipulator (gripper / arm)**, or wire an ultrasonic clearance
provider + opt-in `AvoidancePolicy` into `main.py` **after** hardware
verification of the clearance values. Do not enable avoidance on a real robot
before `config/safety.yaml` is measured and flipped to `VERIFIED`.

### 8. Handoff integrity

| Commit | Contents |
|---|---|
| `ed0497c` | `feat(safety): activate TURN/REPLAN obstacle avoidance` — code, config, tests, `docs/safety.md`, README count |
| (this commit) | `docs(ai-context): record C6 commit hash` — the four `AI_CONTEXT/` files |

A file cannot contain the hash of the commit that creates it, so the second
commit above is labelled *this commit*; resolve the live value with
`git rev-parse HEAD` (also mirrored in `AI_CONTEXT/CURRENT_STATUS.md`).
**Verified at commit time:** `python -m pytest` → 537 passed, 2 skipped,
0 failed, on the tree committed as `ed0497c`.

---

## Session: C5 — vision detector → `VisionHazardSource` → hazard event

**Agent:** cline (Laptop 1 / core robot agent) · **Branch:** `main` ·
**Date:** 2026-09-24 · **Baseline when started:** `ce07420` (clean tree)
**Commit:** see §10 below · **Tests:** 366 → **461 passed, 2 skipped, 0 failed**

### 1. What was completed

**C5 is fully implemented, tested, integrated and documented.** The vision path
now exists end-to-end in software:

```
CameraFrame / VisionDetector (protocol)
        ↓
VisionDetection  (validated contract)
        ↓
VisionHazardSource  (existing class, extended — not duplicated)
        ↓
HazardManager → HazardEventLog → C3 render_map_svg() → C2 GET /hazard
```

* **New `raspberry_pi/amr/hazard/vision.py`** (571 lines, stdlib only) —
  `VisionClass`, `VisionBoundingBox`, `VisionDetection` (frozen dataclass with
  strict validation + `from_any()` coercion), `CameraFrame`/`VisionDetector`
  protocols, `make_vision_reading(s)`, `SIMULATED_SCENARIOS` (12 named cases),
  `SimulatedVisionDetector`, and a `python -m amr.hazard.vision` demo.
* **Extended the existing `VisionHazardSource`** in `sources.py` to accept a
  `VisionDetection` sequence, a detector, or raw dicts, and to emit a
  `HazardKind.VISION_FAULT` reading when the detector itself raises (existing
  tests pin the default to `ROBOT_FAULT`, so that default is unchanged).
* **`HazardReading` / `HazardEvent` gained `metadata`** and `HazardReading`
  gained `location`; the manager now prefers a source-supplied hazard pose over
  the robot pose. Confidence is preserved verbatim (0..1) end-to-end and is
  exposed via `HazardEvent.confidence` and `HazardEvent.to_dict()`.
* **Config:** a validated `vision:` block in `config/hazard.yaml`
  (`enabled`, `warn_at`, `critical_at`, `classes`) parsed by `HazardConfig`,
  with safe defaults and `resolved_vision_thresholds()`.
* **95 new tests** in `tests/test_vision.py` covering all 14 mandated areas plus
  failure handling, C3 SVG, C2 snapshot and safety integration.

### 2. Hardware / firmware honesty

| Area | Status |
|---|---|
| Software simulation | **PASS** (461 tests + 3 demos) |
| Physical camera | **NOT TESTED** — no camera connected, none read |
| ML model / accuracy | **NOT TESTED / NOT CLAIMED** — no weights, no YOLO/OpenCV |
| Firmware | **NOT TESTED / UNTOUCHED** — no Arduino flashed or rebuilt |
| Robot motion caused by vision | **NOT TESTED** — the layer produces evidence only; the existing safety layer is authoritative and was exercised via mocks |

The `SimulatedVisionDetector` is **simulated input**, not a camera result, and
carries no accuracy claim.

### 3. Files changed (12, 2 new)

| Path | Change |
|---|---|
| `raspberry_pi/amr/hazard/vision.py` | **New**: detection contract, protocols, simulated detector, demo |
| `raspberry_pi/tests/test_vision.py` | **New**: 95 tests |
| `raspberry_pi/amr/hazard/types.py` | `HazardReading.location/metadata`, `HazardEvent.metadata`, `.confidence`, serialisation, `VISION_FAULT` / `kind_for_class` |
| `raspberry_pi/amr/hazard/sources.py` | `VisionHazardSource` accepts detections/detector/dicts |
| `raspberry_pi/amr/hazard/manager.py` | Event records source-supplied location + metadata |
| `raspberry_pi/amr/hazard/__init__.py` | Lazy PEP 562 re-exports |
| `raspberry_pi/amr/utils/config.py` | `HazardConfig` vision block + validation |
| `config/hazard.yaml` | `vision:` block |
| `docs/hazard.md` | New vision section; pipeline, limits |
| `README.md` | Badge/table 366→461, demo step 6, roadmap item |
| `AI_CONTEXT/CURRENT_STATUS.md` | Counts, module status, entry point |
| `AI_CONTEXT/TASK_BOARD.md` | C5 `[x]` with outcome |

### 4. Supported classes (canonical table, nothing invented)

`PERSON`/`HUMAN` → `HazardKind.HUMAN`, `FIRE` → `HazardKind.FIRE`,
`SMOKE` → `HazardKind.SMOKE`, `OBSTACLE` → `HazardKind.OBSTACLE`.
Unknown classes are ignored (not a new hazard type). Severity comes from the
existing `HazardConfig` thresholds — `PERSON` is **not** assumed to be
`EMERGENCY`; only kinds in the manager's configured emergency set reach
`EMERGENCY`.

### 5. Location handling

World coordinates are **only** stored when a detection supplies them (e.g. a
calibrated detector/localiser). A bounding box stays in `metadata` as image
space and is **never** converted to metres. A detection with no location leaves
`location=None`; the manager then falls back to the robot pose, exactly as
before. No coordinates are fabricated.

### 6. Tests performed

| Command | Result |
|---|---|
| `python -m pytest tests/test_vision.py` | **95 passed** |
| `python -m pytest` (full) | **461 passed, 2 skipped, 0 failed** |
| `python -m amr.hazard` | exit 0 — `steps=4 failures=0 events_recorded=3 final_hazard=NORMAL` |
| `python -m amr.warehouse` | exit 0 — `completed=3 failed=0` |
| `python -m amr.hazard.vision` | exit 0 — SIMULATION, `events_recorded=3`, prints `SIMULATION ONLY` |
| `python -m amr.hazard.visualisation --out /tmp/c5_verify.svg` | exit 0, SVG well-formed (parsed with `ElementTree`) |

The 2 skips are the pre-existing OpenCV/numpy camera tests.

### 7. Demo

`python -m amr.hazard.vision` runs the deterministic scenarios end-to-end
(detection received → hazard reading → event recorded) and ends with an explicit
`SIMULATION ONLY: no camera was read and no robot was controlled.` line.

### 8. Recommended next task

**C6 — activate obstacle avoidance (`TURN` / `REPLAN`)** is unblocked but flagged
**high risk** (changes Layer-3 stop behaviour). Safer high-value next steps:
(a) a real camera/ML backend behind the existing `VisionDetector` protocol
(hardware-dependent), or (b) a small, read-only C2 web route that serves the C3
SVG. Do not mark C6 done without keeping the deterministic stop tests green.

### 9. Commits / GitHub

* Implementation: `24cdc72` — `feat(hazard): add vision hazard source`
* Context: `docs(ai-context): record C5 commit hash` (this session's second commit)
* Branch `main`. **Push SUCCEEDED**: `dfa70c6..24cdc72 main -> main` (fast-forward,
  8 local commits published). No force-push was used.

### 10. Exact commit hashes

Implementation: `24cdc72`
Documentation: `__C5_DOC__`
Local HEAD at handoff write: `24cdc72`.
origin/main after push (verified): `24cdc72` — `HEAD == origin/main` confirmed.

---

## Session: C3 — spatial hazard visualisation (read side)

**Agent:** cline · **Branch:** `main` ·
**Commit:** see §10 · **Baseline when started:** `179f0e7` (clean tree)

### 1. What was completed

**C3 — spatial hazard visualisation (read side).** Recorded events render
onto the warehouse map as one self-contained SVG, styled like
`assets/warehouse-map.svg`. Pure read-side: never touches the control loop.

* **New `raspberry_pi/amr/hazard/visualisation.py`** — `render_map_svg()`
  plus `events_from_snapshot()` plus CLI
  `python -m amr.hazard.visualisation --events X.jsonl --out map.svg|-`.
* **Lazy re-exports** in `amr/hazard/__init__.py` via PEP 562 `__getattr__`.
* **23 new tests** in `tests/test_hazard_visualisation.py` (offline).
* **Docs:** `docs/hazard.md`, `README.md`, `AI_CONTEXT/` updates.

Explicitly **not** done: no live dashboard, no web route, no warehouse
wiring, no sensor sources (still no hardware).

### 2. Files changed (8, new + modified)

| Path | Change |
|---|---|
| `raspberry_pi/amr/hazard/visualisation.py` | **New**: renderer + CLI, stdlib only |
| `raspberry_pi/tests/test_hazard_visualisation.py` | **New**: 23 tests |
| `raspberry_pi/amr/hazard/__init__.py` | Lazy PEP 562 re-exports (3 names) |
| `docs/hazard.md` | New section; stale limitation removed |
| `README.md` | Badge + table 343 to 366, demo step 5 |
| `AI_CONTEXT/CURRENT_STATUS.md` | Counts 366, 16 files, new entry point |
| `AI_CONTEXT/TASK_BOARD.md` | C3 `[ ]` to `[x]` with outcome |
| `AI_CONTEXT/ARCHITECTURE.md` | Layer 3.5 row notes `render_map_svg` |

### 3. Tests

| Command | Result | Status |
|---|---|---|
| `python -m pytest` (full suite) | **366 passed, 2 skipped, 0 failed** in ~18 s | **software-tested** |
| `python -m pytest tests/test_hazard_visualisation.py` | **23 passed** | **software-tested** |
| `python -m amr.hazard` | exit 0 (no regression) | **software-tested** |
| `python -m amr.hazard.visualisation --out /tmp/x.svg` | exit 0, valid SVG | **software-tested** |

The 2 skips are the conditional OpenCV camera tests.

### 4. API

`render_map_svg(locations, events, *, zones=(), title=...) -> str` and
`events_from_snapshot(snapshot) -> list[dict]` (active wins, sorted).
CLI: `--events X.jsonl --out map.svg|- --title T --config-dir D`.

### 5. Safety behaviour

* The renderer imports nothing from `amr.robot` / `amr.navigation` /
  `amr.warehouse`, issues no commands, and runs fully offline on a laptop
  that has only the JSONL export — it **cannot** affect the control loop.
* No thresholds, latches, or acknowledgement semantics were touched; C2's
  two-step release is unchanged.

### 6. Hardware status

**No physical hardware was tested.** All results above are software/mock/offline
tests on this machine. `config/hazard.yaml` remains `NOT_VERIFIED`, and
`hazard.enabled` remains `false` in the shipped config.

### 7. Known issues

* The SVG is a **static offline render**, not a live dashboard — there is still
  no web route serving it (a future task could add one as pure read-side).
* `amr/warehouse` still ignores the hazard verdict (unchanged from C2).
* No hazard sensor sources are wired (no hardware); thresholds still
  `NOT_VERIFIED`; no panel authentication (pre-existing).
* `ruff check` on the new files reports only modern-typing suggestions
  (`UP035/UP006/UP045`) that apply equally to the whole pre-existing `amr/`
  tree (273 findings on the clean tree) — the new code deliberately matches
  the repo's existing `typing.Dict/List/Optional` convention.

### 8. Remaining work

See `TASK_BOARD.md` §C. Next recommended: **C5** (fire/human detector feeding
`VisionHazardSource`, giving the layer — and this map — its first real
non-zone source) or serve this SVG from the web panel as a read-only view.
C1/C4 remain blocked on hardware; C6 is high-risk Layer-3 behaviour change;
C7–C9 unstarted.

### 9. Integration notes

* **No interface of `amr/hazard` was changed** — C3 only *reads*
  `HazardEvent.to_dict()` / `read_events()` dicts / `snapshot()` dicts. No
  `INTEGRATION_REQUESTS.md` was needed.
* Treat `render_map_svg()` / `events_from_snapshot()` / `STATE_COLORS` as the
  stable read-side contract — only additive changes are safe.
* Re-read `TASK_BOARD.md` before starting — C5 is the likely next pick.

### 10. Commit

Baseline history: `dfa70c6` → `eadf6a5` → `4eeb571` → `5a09791` →
`a9bc358` (C2 feature) → `179f0e7` (C2 hash record). This session's commits:

| # | Hash | Commit |
|---|---|---|
| 7 | `59269a4` | `feat(hazard): add spatial visualisation of recorded events` — C3 renderer, lazy re-exports, 23 tests, docs |
| 8 | *this commit* | `docs(ai-context): record C3 commit hash` — this row's hash (a file cannot contain its own hash) |

For the live value run `git rev-parse HEAD`.

Working tree: only the 8 files listed in §2; no `.kilo/`, no secrets, no
temporary files. Nothing was pushed.

---

## Previous session: C2 — web panel hazard integration (Laptop 1)

**Agent:** cline (Laptop 1 / Core Robot Agent) · **Branch:** `main` ·
**Commit:** see §10 (of that session) · **Baseline when started:** `5a09791` (clean tree)

### 1. What was completed (C2, kept for history)

### 1. What was completed

**C2 — wire `amr/hazard` into the web panel.** The latched `EMERGENCY` is now
reachable by an operator through the browser instead of only a Python REPL.

* **`GET /hazard`** — pure read of `HazardManager.snapshot()` plus derived
  operator keys (`attached`, `severity`, `active`, `hazard` descriptor with
  `confidence` when the reading carries one, `latest_event`). When no layer is
  wired it returns an honest stable shape with `attached: false` and
  `state: null` (the `/camera` `available: false` convention — no layer means
  *no assessment*, not `NORMAL`).
* **`POST /hazard/acknowledge`** — **step 1 of the two-step release only.**
  Calls exactly `HazardManager.acknowledge()` under the same lock as the
  control loop. Optional `{}`/empty body; `400` when no layer is attached or
  the payload is not a JSON object.
* **Panel** — header badge `HAZARD <state>` (blinking red for
  `STOP`/`EMERGENCY`, respects `prefers-reduced-motion`), a hazard card
  (state, severity, active, kind, confidence, source, location, reason,
  timestamp) and an **Acknowledge** button that appears only while `latched`.
* **`amr/main.py`** — `attach_hazard_layer(mgr, config)` runs after
  `mgr.start()` and attaches `HazardManager.from_config(config.hazard)`
  **only when `config.hazard.enabled`** (default `false`, so default
  behaviour is byte-identical to before).

Explicitly **not** done: no `amr/warehouse` wiring, no sensor sources attached
(no hardware exists), and `HazardManager.reset()` is deliberately **not**
exposed over HTTP (it would drop the audit trail).

### 2. Files changed (10, +769/−21)

| Path | Change |
|---|---|
| `raspberry_pi/amr/web/server.py` | `hazard_status()`, `acknowledge_hazard()`, `_hazard_payload()` (snapshot + derived keys, `_STATE_SEVERITY` floor); `GET /hazard` + `POST /hazard/acknowledge` routes; header badge, hazard card, `refreshHazard()` (1 s poll), ack button JS/CSS; endpoint + safety docstrings |
| `raspberry_pi/amr/web/__init__.py` | Package docstring documents the hazard surface |
| `raspberry_pi/amr/main.py` | `attach_hazard_layer()` gated on `config.hazard.enabled`, called after `mgr.start()`; imports `HazardManager` |
| `raspberry_pi/tests/test_web_server.py` | `MutableHazardSource` + `web_hazard` fixture + `_tick`/`_hazard` helpers; **10 new tests** (25 total in file) |
| `docs/web_control.md` | Endpoint rows, new "Hazard layer (C2)" section (payload keys, ack semantics, two-step diagram), test note |
| `docs/hazard.md` | Two-step section documents the HTTP paths; limitations updated (wired into web, not warehouse; no sources auto-wired) |
| `README.md` | API table rows, poll note, badge + counts `333 → 343` |
| `AI_CONTEXT/ARCHITECTURE.md` | §9 web API surface lists both new routes |
| `AI_CONTEXT/CURRENT_STATUS.md` | Counts `343`, `test_web_server.py 25`, live-smoke row, known-issues rewritten |
| `AI_CONTEXT/TASK_BOARD.md` | C2 `[~]` → `[x]` with outcome; C10 badge note superseded |

### 3. Tests

| Command | Result | Status |
|---|---|---|
| `python -m pytest` (full suite) | **343 passed, 2 skipped, 0 failed** in ~17 s (baseline 333/2 → +10 legitimate new tests) | **software-tested** |
| `python -m pytest tests/test_web_server.py` | **25 passed** | **software-tested** |
| `python -m pytest tests/test_hazard.py` | **48 passed** (no regression) | **software-tested** |
| `python -m amr.hazard` | exit 0 — `steps=4 failures=0 events_recorded=3 final_hazard=NORMAL` | **software-tested** |
| `python -m amr.warehouse` | exit 0 — `completed=3 failed=0` | **software-tested** |
| Live smoke `--mock --web` + `hazard.enabled=true` + `curl` | `/hazard` → `attached:true, state:NORMAL, sources:["zones"]`; ack → `ok:true`; `/status` carries `hazard` | **software-tested** |

The 2 skips remain the conditional OpenCV camera tests. New tests cover:
normal-without-layer shape, normal-with-layer, active hazard reported
(kind/confidence/source/events), latched `EMERGENCY` (→ `SAFETY_STOP`,
motion `400`), **ack cannot clear an active hazard** (re-latches), the full
**two-step release**, ack idempotence, `400` without a layer, `400` on
non-object payload, and `/status` + panel regression.

### 4. API

```
GET  /hazard
  → 200 {attached, enabled, status, state, severity, active, latched,
         blocks_motion, speed_scale, reasons, location,
         hazard{kind, severity, source, message, location, raised_at,
                value, unit, confidence},
         latest_event, active_events, recent_events, events_recorded,
         counts_by_kind, sources, updated_at}
  → no layer attached: same keys, honest nulls/false, state: null
  Pure read — never evaluates or clears anything.

POST /hazard/acknowledge     body: {} or empty (JSON object enforced)
  → 200 {ok:true, acknowledged:true, was_latched, latched, state, hazard{…}}
  → 400 {ok:false, error:"hazard layer not attached"}   (no layer)
  → 400 {ok:false, error:"bad JSON: …"}                 (non-object payload)
```

### 5. Safety behaviour — what acknowledge does and does not do

* **Does:** clear the hazard `EMERGENCY` *latch* and re-evaluate the layer.
* **Does NOT** bypass an active hazard: if evidence is still present the very
  same call re-latches (`latched:true` in the response) — proven by
  `test_hazard_ack_cannot_clear_an_active_hazard`.
* **Does NOT** touch the robot mode: `SAFETY_STOP` survives acknowledgement;
  motion stays `400` until the operator performs step 2 via the **existing**
  `POST /command {"cmd":"mode", …}` path — proven by
  `test_hazard_ack_is_step_one_of_a_two_step_release`.
* **Does NOT** delete audit events: `HazardManager.reset()` remains
  REPL/maintenance-only and is not routed in the web layer.
* The web layer still reaches the motors **only** through `RobotManager`;
  both new endpoints run under the same lock as `tick()`/`dispatch()`.

### 6. Hardware status

**No physical hardware was tested.** No robot, Arduino, sensor, camera, or
firmware was exercised — all results above are software/mock/HTTP tests on
this laptop. Firmware not rebuilt or flashed. `config/hazard.yaml` remains
`NOT_VERIFIED`, and `hazard.enabled` remains `false` in the shipped config.

### 7. Known issues

* **No hazard sensor sources are wired** — `attach_hazard_layer` attaches the
  layer with only the (silent-without-pose) zone source; `GET /hazard` on a
  real deployment reports `sources:["zones"]` until C4/C5 deliver drivers.
* **`RobotStateSource` intentionally not auto-wired:** `RobotState.last_error`
  is sticky (never cleared after E-STOP/`_enforce_stop`), so wiring it would
  pin the hazard layer at `WARNING` forever after the first safety stop.
  Wiring it needs a `last_error` lifecycle decision first.
* `amr/warehouse` still ignores the hazard verdict (unchanged from before).
* Hazard thresholds still `NOT_VERIFIED`; no authentication on the panel
  (pre-existing).
* `HazardManager.reset()` has no web route by design — if an operator ever
  needs it, that is a deliberate safety review, not an oversight.

### 8. Remaining work

See `TASK_BOARD.md` §C. Next recommended: **C3** (spatial hazard
visualisation — reads the JSONL/event data, hardware-free) or **C5**
(fire/human detector feeding `VisionHazardSource`, which would give `/hazard`
its first real non-zone source). C1/C4 remain blocked on hardware; C6 is
high-risk Layer-3 behaviour change; C7–C9 unstarted.

### 9. Laptop 2 integration

* **No interface of `amr/hazard` was changed** — C2 only *consumed*
  `snapshot()`, `status`, `acknowledge()` and the `RobotManager.hazard` /
  `hazard_snapshot()` seam. No `INTEGRATION_REQUESTS.md` was needed.
* If Laptop 2 wires camera/gas/vision sources: attach the hazard manager
  **before** `attach_hazard_layer` runs, or attach after it —
  `attach_hazard_layer` no-ops when `mgr.hazard is not None`, so it will not
  fight an earlier attachment. Sources can also be added later via
  `hazard.add_source(...)` on the already-attached manager.
* `GET /hazard` is the read contract for any dashboard work; treat the
  snapshot keys as stable — only additive changes are safe.
* Re-read `TASK_BOARD.md` before starting — C3/C5 are the likely next picks.

### 10. Commit

Baseline history (previous session): `dfa70c6` → `eadf6a5` → `4eeb571` →
`5a09791`. This session's commits:

| # | Hash | Commit |
|---|---|---|
| 5 | *this commit* | `feat(web): integrate hazard status and acknowledgement` — the C2 feature: both routes, panel UI, `main.py` wiring, 10 tests, docs |
| 6 | filled in by the follow-up docs commit | `docs(ai-context): record C2 commit hash` — this row's hash (a file cannot contain its own hash) |

**Exact hash of commit 5: `a9bc358`** (filled in by follow-up commit 6).
For the live value run `git rev-parse HEAD`.

Working tree: only the 10 files listed in §2; no `.kilo/`, no secrets, no
temporary files. Nothing was pushed (`origin/main` still at `dfa70c6`).

---

## Previous session: bootstrap AI_CONTEXT + multi-hazard layer (baseline)

**Agent:** cline · **Branch:** `main` · **Feature commit:** see §7
**Baseline when started:** `dfa70c6` (`Initial commit: AMR autonomous mobile robot project`)

> *Superseded by the C2 session above; kept for baseline history.*

---

## 1. What was completed

### 1.1 Discovered state (important — this was NOT a greenfield repo)

Before writing code I verified the actual repository state. Two findings shaped
this session:

* **`AI_CONTEXT/` did not exist.** None of the five mandated documents existed,
  so the required "read PROJECT_CONTEXT / CURRENT_STATUS / ARCHITECTURE /
  TASK_BOARD / HANDOFF first" step was impossible. I created all five, derived
  strictly from inspection of the existing code (no invention).
* **The remote was missing most of the project's documentation.** `README.md`,
  `CONTRIBUTING.md`, `LICENSE`, `assets/*.svg`, `.github/workflows/ci.yml` and
  `showcase.html` were all **untracked** on `main` — a fresh clone of
  `origin/main` had none of them, and CI could not run. Tracked separately in
  commit `chore(repo): ...` (see §7) so attribution stays honest.

Also checked: `.kilo/worktrees/equal-sheep/` is a **detached-HEAD git worktree at
`dfa70c6` with a clean status and zero divergence** — an abandoned tooling
worktree containing no other agent's work. Left untouched, and deliberately not
committed (it holds a nested `.git` file).

**No other agent's work was overwritten.** No existing public interface was
renamed or removed. `git status` showed no unexpected local modifications.

### 1.2 Task taken (was unassigned)

**Context-aware multi-hazard safety layer** — the project's stated novelty
direction. Implemented as a new, independent `amr/hazard/` package plus an
**additive, opt-in** integration point in `RobotManager`.

States produced: `NORMAL · WARNING · SLOW · STOP · EMERGENCY`.
Inputs supported: gas/smoke sensors, camera vision (fire/human), robot state,
navigation state, robot location (restricted zones). Includes a latched
life-safety `EMERGENCY`, a bounded event log with JSONL export, and location
tagging for future spatial hazard visualisation.

### 1.3 Explicitly NOT done

* No real sensor hardware, no pins, no drivers — the layer provides the
  aggregation and the *seam* only.
* Not wired into `amr/web` or `amr/warehouse` yet.
* No spatial visualisation renderer.
* No ROS 2, RFID, vision model, or real manipulator work.

---

## 2. Files changed

### Created
| Path | What |
|---|---|
| `AI_CONTEXT/PROJECT_CONTEXT.md` | Project, conventions, ground rules, working agreement |
| `AI_CONTEXT/CURRENT_STATUS.md` | Verified test counts, per-module status, honest gaps |
| `AI_CONTEXT/ARCHITECTURE.md` | Layers, gate, safety layers, config, extension points |
| `AI_CONTEXT/TASK_BOARD.md` | Shared queue with `[ ]/[~]/[x]/[!]` legend |
| `AI_CONTEXT/HANDOFF.md` | This file |
| `raspberry_pi/amr/hazard/types.py` | `HazardKind/Severity/State`, `HazardReading`, `HazardEvent`, `HazardStatus`, `HazardLocation` |
| `raspberry_pi/amr/hazard/sources.py` | `HazardSource` protocol, `GasSensorSource`, `VisionHazardSource`, `RobotStateSource`, `RestrictedZoneSource`, `HazardZone`, `severity_for` |
| `raspberry_pi/amr/hazard/event_log.py` | Bounded `HazardEventLog` + JSONL persist/`read_events` |
| `raspberry_pi/amr/hazard/manager.py` | `HazardManager` (decision, latching, event sync, snapshot) |
| `raspberry_pi/amr/hazard/__init__.py` | Public exports |
| `raspberry_pi/amr/hazard/__main__.py` | Offline scripted demo (`python -m amr.hazard`) |
| `raspberry_pi/tests/test_hazard.py` | 48 tests |
| `docs/hazard.md` | Full documentation + limitations |
| `config/hazard.yaml` | Thresholds, kinds, one placeholder zone (`NOT_VERIFIED`) |

### Modified (additive only)
| Path | Change | Risk |
|---|---|---|
| `raspberry_pi/amr/robot/robot_manager.py` | `attach_hazard()`, `hazard_snapshot()`, `_scaled()`, `_hazard_location()`; hazard veto in `_gate()`; Layer-3.5 evaluation in `tick()`; optional `hazard` key in `snapshot()` | Low — no-op unless `attach_hazard` is called |
| `raspberry_pi/amr/utils/config.py` | `HazardConfig` dataclass, `AppConfig.hazard` field, load + `_validate_hazard`, `typing.List` import | Low — defaults preserve behaviour |
| `raspberry_pi/tests/test_config.py` | +9 hazard config tests | None |
| `README.md` | Badge 276→333, hazard row/layout/roadmap, "See it work" step 4, Layer-3.5 note | None |
| `docs/safety.md` | Fixed stale `architecture.md` link → `AI_CONTEXT/ARCHITECTURE.md` | None |
| `raspberry_pi/amr/logging/logger.py` | Fixed stale `docs/architecture.md` docstring reference | None (comment only) |

---

## 3. Tests performed

All hardware-free, on `amr/mocks/`, run from `raspberry_pi/` with the repo
virtualenv.

| Command | Result | Status |
|---|---|---|
| `python -m pytest` (full suite) | **333 passed, 2 skipped, 0 failed** in 11.91s | **tested** |
| `python -m pytest tests/test_hazard.py` | 48 passed | **tested** |
| `python -m pytest tests/test_config.py` | 18 passed (incl. 9 new hazard tests) | **tested** |
| `python -m amr.hazard` | exit 0 · `RESULT: steps=4 failures=0 events_recorded=3 final_hazard=NORMAL final_mode=IDLE` | **tested** |
| `python -m amr.warehouse` | `RESULT: completed=3 failed=0` (no regression) | **tested** |
| `python -m amr.main --mock --demo` | all steps `ok` (no regression) | **tested** |
| `python -m amr.main --mock --web` + `curl /status`, `POST /command` | HTTP 200, E-STOP accepted | **tested** (earlier in session) |

**Regression evidence:** the baseline suite was 276 passed / 2 skipped before this
session; it is 333 / 2 after, so all 276 pre-existing tests still pass and the 57
net new tests are additive.

### Test status honesty

| Area | Status |
|---|---|
| `amr/hazard` decision logic, latching, events, sources, zones | **tested** (48 unit tests, no hardware) |
| `RobotManager.attach_hazard` integration (escalate-only, veto, speed cap, no-op when detached) | **tested** (7 integration tests on the mock stack) |
| Hazard config load + validation | **tested** (9 tests) |
| Real gas/fire/human sensor behaviour | **not tested** — no hardware exists |
| Anything on a physical robot | **not tested / hardware-dependent** |
| Arduino firmware | **not tested** — no toolchain in CI |

### Bugs found and fixed during testing

1. `HazardZone.__post_init__` read `x_min` **after** mutating it, collapsing
   `x_max` to the same value for swapped bounds. Caught by
   `test_zone_contains_normalises_swapped_bounds`; fixed by sorting the original
   pair before assignment.
2. One test asserted the wrong error string: the **mode gate** correctly rejects
   motion before the hazard veto runs. Test corrected, and a separate test now
   isolates the hazard-veto path (`test_hazard_stop_vetoes_motion_at_the_gate`).
   The production behaviour was correct; the assertion was not.

---

## 4. Known issues

* **`amr/hazard` is not wired into `amr/web` or `amr/warehouse`.** The manager
  exposes a JSON `snapshot()`; consumers are unwritten.
* **No sensor hardware and no pins.** `config/hazard.yaml` is `NOT_VERIFIED` and
  the example zone is a placeholder (it happens to overlap `shelf_c`).
* `HazardManager` does **not** self-disable on `config.hazard.enabled` — the
  deployment switch is honoured by *wiring* (documented in `docs/hazard.md`).
  An agent that attaches it manually bypasses that switch by design.
* `VisionHazardSource` is a seam only; no detector model.
* No spatial visualisation renderer (events export as JSONL with locations).
* Pre-existing: no web authentication; `SafetyAction.TURN`/`REPLAN` still
  reserved and never emitted; robot geometry still `null`.
* `.kilo/` remains untracked on purpose (agent tooling with a nested `.git`).

---

## 5. Remaining work

See `TASK_BOARD.md` §C for the full, scoped list. Summary:

1. **C1 (blocked on hardware)** — verify geometry + safety thresholds, fill the
   `TODO_VERIFY` pins, flip statuses to `VERIFIED`.
2. **C2** — wire the hazard layer into the web panel (`GET /hazard`, panel
   status, acknowledge step 1 only) and telemetry.
3. **C3** — spatial hazard visualisation from the JSONL event export.
4. **C4 (blocked)** — real gas/smoke driver + pins.
5. **C5** — fire/human vision detector feeding `VisionHazardSource`.
6. **C6 (high risk)** — activate `TURN`/`REPLAN` obstacle avoidance.
7. **C7/C8/C9** — real manipulator, RFID, ROS 2 bridge (all unstarted).

---

## 6. Recommended next task

**C2 — wire `amr/hazard` into the web panel and telemetry.**

Rationale: it is unblocked, hardware-free, additive, low-risk, and it is what
makes the new layer *visible* to an operator — without an acknowledge path and a
status readout the latched `EMERGENCY` is only reachable from a Python REPL.
It also exercises the `hazard.enabled` deployment switch for the first time.

Concretely: `GET /hazard` → `HazardManager.snapshot()`; attach the layer in
`amr/main.py` **only when `config.hazard.enabled`**; add a panel indicator for
`HazardState`; add an acknowledge endpoint that performs step 1 of the two-step
release and leaves the `SAFETY_STOP` mode reset to the existing
`POST /command {"cmd":"mode", ...}` path.

---

## 7. Commit / branch

**Branch:** `main` (not pushed). Three commits, in this order:

| # | Hash | Commit |
|---|---|---|
| — | `dfa70c6` | (pre-existing baseline, = `origin/main`) `Initial commit: AMR autonomous mobile robot project` |
| 1 | `eadf6a5` | `chore(repo): track project artifacts that were previously untracked` — `CONTRIBUTING.md`, `LICENSE`, `assets/`, `.github/`, `showcase.html`, plus `.gitignore` now ignoring `.kilo/` |
| 2 | `4eeb571` | `feat(hazard): add context-aware multi-hazard safety layer` — the `amr/hazard/` package, config, tests, `docs/hazard.md`, the AI_CONTEXT bootstrap, and the README/`docs/safety.md`/`logger.py` documentation updates |
| 3 | *this commit* | `docs(ai-context): record handoff commit hashes` — this §7 hash table plus the `TASK_BOARD.md` C10 housekeeping status |

**Exact hashes:** this table was filled in by a small follow-up commit (row 3),
because a file cannot contain its own commit hash. For the live value run
`git rev-parse HEAD`.

Nothing was pushed — `origin/main` is still at `dfa70c6`. **The next agent should
`git pull` before starting** and must re-read `TASK_BOARD.md` (it is shared).

