# HANDOFF — latest session

> **Read this before starting work.** Then re-read `TASK_BOARD.md` (it is shared
> and another agent may have added to it).

---

## Session: bootstrap AI_CONTEXT + context-aware multi-hazard safety layer

**Agent:** cline · **Branch:** `main` · **Feature commit:** see §7
**Baseline when started:** `dfa70c6` (`Initial commit: AMR autonomous mobile robot project`)

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

**Branch:** `main` (working tree was on `main` at `dfa70c6`; not pushed)

Two commits were made, in this order:

| # | Commit |
|---|---|
| 1 | `chore(repo): track project artifacts that were previously untracked` — `CONTRIBUTING.md`, `LICENSE`, `assets/`, `.github/`, `showcase.html`, plus `.gitignore` now ignoring `.kilo/` |
| 2 | `feat(hazard): add context-aware multi-hazard safety layer` — the `amr/hazard/` package, config, tests, `docs/hazard.md`, the AI_CONTEXT bootstrap, and the README/`docs/safety.md`/`logger.py` documentation updates |

**Exact hashes:** run `git log --oneline -3` — commit 2 is the feature commit and
the one that introduced this file
(`git log -1 --format=%H -- AI_CONTEXT/HANDOFF.md`).

Nothing was pushed. **The next agent should `git pull` before starting**, and
must re-read `TASK_BOARD.md` since it is shared.

