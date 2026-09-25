# Advanced Telemetry & Mission Monitoring (C11)

The dashboard becomes an **operations console**: a global status strip plus
detailed panels for robot, navigation, mission, safety, hazards, battery,
sensors, camera and system health — all read-only, all from existing state.

## 1. Architecture

C11 adds **no new telemetry schema and no second state engine**. It reuses the
C7 contract verbatim and only *assembles* it:

```text
AMR Runtime
   ├── TelemetryCollector (C7)   ─┐
   ├── MapService / MapSnapshot (C9) ─┼─→ build_console_state() ─→ GET /dashboard/state
   ├── build_twin_state (C10)     ─┤                                  ↓
   └── TelemetryCollector.health (C7) ┘                           Dashboard
```

`amr/telemetry/console.py` is a pure function of its inputs. It samples no
hardware, caches nothing, mutates nothing, and re-decides no safety or
navigation outcome. Every value it emits is copied or derived arithmetically
from objects the existing panels already read.

The `map` and `twin` keys are the **untouched** C9 and C10 payloads, passed
through by reference. A test asserts `console["map"] == GET /map` and
`console["twin"] == GET /digital-twin`, so the console can never become a second
map or twin state.

## 2. Why a consolidated endpoint

Before C11 the page issued four requests per tick (`/telemetry`, `/map`,
`/digital-twin`, …). `GET /dashboard/state` returns all of it in **one** read,
which matters on a Raspberry Pi.

Every previous endpoint is still served and still tested — `/telemetry`,
`/health`, `/map`, `/map.svg`, `/digital-twin`, `/camera/status`,
`/camera/frame`, `/status`. Only the page's internal choice changed. The
console endpoint is **GET-only**; there is no POST route, so no browser command
can reach it, let alone the robot through it.

## 3. Update model

The existing **1 Hz** `poll()` is unchanged in cadence — still one
`setInterval`, no second timer, no WebSocket. It now fetches one URL and
dispatches the map and twin renderers with the embedded payloads
(`pollMapWith` / `tApplyState`), so the 2D and 3D views are driven by exactly
the same numbers they consumed before.

## 4. Source honesty

Every panel keeps the C7 `DataSource` tag (`LIVE` / `SIMULATION` /
`UNAVAILABLE` / `ERROR`) and adds an `availability` word. Two invariants are
enforced by tests:

* `UNAVAILABLE` is never coerced to `0`, `"ok"`, `100%` or a plausible default.
  A missing battery shows `percentage: null`, `N/A`, and
  `note: "no battery source in this build"`.
* An empty runtime reports **"Mission data unavailable"** rather than a
  blank-but-healthy mission.

Route progress is **reported, never recomputed**. The C7 collector's value is
straight-line distance to the goal, not path-following completion, so the
console labels it (`progress_basis`) and the panel says "display only, never a
planner input". With no goal/pose pair, progress is `N/A` — never a fabricated
percentage.

## 5. Hazard placement rule (C9/C10 preserved)

The console reads the placed/unplaced split from the **map** projection, which
already places a hazard only when a real world location exists. An image-space
detection is counted under `unlocated` and shown as "N unlocated" — it is never
given coordinates and never drawn on either map.

## 6. JavaScript validation (mandatory since C10)

C10 shipped a dashboard-wide JavaScript break that every pytest test passed
over, because the tests asserted on HTML *text* while the failure was in the
executed script. C11 makes that impossible:

`tests/test_console.py::TestDashboardJavaScriptSyntax` extracts the served
`<script>` bodies from `DASHBOARD_HTML` / `INDEX_HTML`, writes them to a
temporary file and runs **`node --check`**. This is a *validation tool only* —
the AMR never imports Node, and the project still needs no npm.

If Node is absent the two syntax tests **skip with an explicit reason**
(`"node not installed: JS syntax NOT verified"`) rather than silently passing,
and the remaining structural tests (panel presence, no actuation endpoints,
single-console-endpoint wiring) still run. Verified: with Node removed from
`PATH` the class reports `4 passed, 2 skipped`.

This guard immediately caught a real bug during C11 development: a
double-quote-escaping mistake in the new progress-bar renderer that would have
blanked the whole dashboard.

## 7. Read-only verification

`conftest.NoActuation` is the shared assertion. It records the mock transport's
line count on entry and fails if anything appended during the block is an
actuator command (`MOVE` / `STOP`).

It deliberately does **not** assert that the total line count is unchanged.
The control loop emits its own periodic `PING` / `VERSION` / `SENSOR` polls on
a background thread, so a total-count assertion is racy under load — it fails
whenever a background poll lands inside the measurement window, regardless of
what the code under test did. Asserting on actuator verbs is both deterministic
and a stronger guarantee: it still catches a read path that issued `MOVE` even
if background traffic tripled. This replaced the racy pattern in the C7, C8,
C9 and C10 read-only tests, which shared the same latent defect.

## 8. Limitations

* Battery, real sensors, a real mission runtime and a real camera remain
  **unavailable in this build**; the console reports them as such rather than
  filling the gaps.
* Mission "state" is *described* from existing counters, not a new state
  machine.
* The mission runtime is not wired into the mock dashboard, so the panel
  normally shows "Mission data unavailable".
* No historical replay, no analytics, no cloud backend, no authentication.

## 9. Testing status

**Software tested** — 35 console unit tests + 10 `TestDashboardStateApi` HTTP
tests, covering every panel, all mission states, hazard placement, source
honesty, route progress, system health, endpoint behaviour, the JavaScript
guard, and read-only guarantees.

**Hardware tested: NO.** No Raspberry Pi, robot, camera or battery was used.
**Firmware tested: NO.** Firmware untouched.

