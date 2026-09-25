# C12 — Mission monitoring

C12 makes the dashboard's **Mission** panel show the real warehouse task
manager instead of "Mission data unavailable". It adds no mission engine: the
existing `WarehouseTaskManager` remains the only thing that decides what the
robot is doing.

## The bug this milestone found

The mission telemetry section had **never reported anything**. Three separate
defects in `TelemetryCollector._mission()` each independently forced it to
`UNAVAILABLE`:

| # | Defect | Effect |
|---|--------|--------|
| 1 | Tested `isinstance(wh.status(), dict)`, but `status()` returns a `ManagerStatus` **object** | Early return → `UNAVAILABLE` |
| 2 | Read `current_task`; the real key is `current` | Active task silently dropped |
| 3 | Read `mission_id`; no runtime ever produced it | Always `None` |

Defect 1 masked the others, which is why the panel looked merely "empty" rather
than broken. The fix accepts **either** an object or a plain dict, and tolerates
both key spellings, so existing hand-rolled test doubles keep working.

This was only findable by driving the *real* manager — a test double written
from the same wrong assumption would have kept it broken.

## Data flow (read-only)

```
WarehouseTaskManager.status()            ManagerStatus (the only mission truth)
        │  mission_id, destination, total_tasks, task counters
        ▼
TelemetryCollector._mission()            adapters + progress, no new state
        ▼
MissionTelemetry                         the C7 mission section, extended
        ▼
build_console_state()                    mission_phase() + counters
        ▼
GET /dashboard/state  →  Mission panel
```

## New fields

`ManagerStatus` (additive, last, all optional — existing positional
construction is unaffected):

| Field | Meaning |
|---|---|
| `mission_id` | Caller-supplied label for this run. `None` when unconfigured — never invented. |
| `destination` | The active task's own named location. `None` when idle. |
| `total_tasks` | Queued + active + completed + failed. |

`MissionTelemetry` (also additive):

| Field | Meaning |
|---|---|
| `destination` | Same source as above, carried through. |
| `total_tasks` | Real count of work submitted. |
| `mission_progress` | `completed / total`, 0..1. `None` when no tasks exist. |
| `task_progress` | Straight-line progress of the *active task*, 0..1. `None` with no goal. |

`task_progress` deliberately reuses the collector's existing `_goal_progress()`
helper and the navigator's own goal — one calculation, so the Mission panel and
the navigation panel can never disagree.

## Mission phases

The roadmap narrative is
`PICKUP → NAVIGATE → AVOID → ARRIVE → DROP → RETURN`. `mission_phase()` maps it
onto what the runtime actually knows, using **only** the real task type
(`pick` / `place` / `move` / `return_to_dock`) and real travel progress:

| Real state | Phase |
|---|---|
| Task `pick`/`place`/`move`, progress < 0.9 | `NAVIGATE` |
| Task `pick`, arrived | `PICKUP` |
| Task `place`, arrived | `DROP` |
| Task `move`, arrived | `ARRIVE` |
| Task `return_to_dock` | `RETURN` |
| No task, work completed | `COMPLETED` |
| No task, no work | `IDLE` |
| Source unavailable/error | `UNAVAILABLE` |

`AT_ARRIVAL = 0.9` is a **display convention only**. It is never fed back into
navigation, and the raw `current_task_type` / `current_task_status` are always
shown beside the derived phase so the runtime's own wording is never hidden.

Two honesty rules are enforced and tested:

- **Unknown progress is not arrival.** `None` or `NaN` keeps the phase at
  `NAVIGATE`; a missing measurement is never read as success.
- **Safety outranks the narrative.** A C6 avoidance action shows `AVOID`
  (`TURN`/`REPLAN`), a hold shows `HELD` (`STOP`/`WAIT`), and an emergency stop
  shows `EMERGENCY` — even during an otherwise-completed mission.

## Seeing it live

The Mission panel is only interesting while a mission is running, so C12 adds an
opt-in, **mock-only** demo:

```bash
python -m amr.main --mock --web --mission-demo
# Mission panel: NAVIGATE -> PICKUP -> NAVIGATE -> DROP -> ... -> COMPLETED
```

`--mission-demo` commands autonomous motion, so it is **refused without
`--mock`** rather than silently starting a run nobody asked for. Without the
flag the panel simply monitors, and reports mission counters as they are.

## Safety

- **No new endpoint.** The existing `POST /command` remains the only actuator
  path; C12 adds no route at all.
- **Reads never actuate.** A test drives the real manager and asserts mission
  and console reads write **zero** bytes to the mock serial transport.
- **The mission demo is a runtime loop**, not a dashboard control — the panel
  only observes its result.
- Navigation, the planner and `ManagerStatus.idle` semantics are unchanged.

## Testing

`tests/test_mission_monitoring.py` (45 tests) drives the **real**
`WarehouseTaskManager` from the real config through the standard
pick → place → return scenario, rather than asserting against a hand-written
double. It covers the three original defects, the new fields, every phase
transition, monotonic progress, both progress sources, degradation paths
(status raising, garbage types, non-numeric counts), the read-only guarantee,
and the mock-only safety gate.

One pre-existing assertion in `tests/test_warehouse.py` was changed from an
exact key-set equality to a subset check plus separate assertions for the three
new keys. Every original key is still asserted present with the same meaning, so
net coverage increased.

## Limitations

- **Hardware tested: no.** Software/mock only; no physical robot was involved.
- `mission_id` is a caller-supplied label, not a UUID generated by a mission
  engine — the project has no persistent run identity yet.
- `mission_progress` counts completed tasks; a failed task is excluded from the
  numerator but is shown separately as `failed_tasks`, so the bar never claims
  work succeeded.
- Progress is straight-line distance to goal, not path length. Fine for the
  current waypoint-based planner; a path-following planner would need a
  different basis.
