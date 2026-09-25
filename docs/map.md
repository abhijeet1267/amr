# AMR — C9 LIVE 2D WAREHOUSE MAP

Status: **Implemented, unit-tested, opt-in.** Read-only. No hardware required.

## What this is

A live 2D map of the warehouse inside the existing dashboard, drawn from the
runtime the robot is actually using.

```
Existing WarehouseMap (waypoints)   ┐
Existing HazardZone rectangles (C5) ├─> amr/map/snapshot.py   MapSnapshot
Existing Navigator (pose/goal/route)│        │
Existing HazardManager (events)     │        ├─> GET /map      (JSON, C10-ready)
Existing Telemetry (safety)         ┘        └─> GET /map.svg  (server-rendered)
                                                     │
                                                     └─> dashboard SVG panel
```

There is **no second navigation engine and no second coordinate system**: the map
is a projection of the objects the robot already owns, and it is read-only.

## Coordinate system

The repository's own warehouse frame, unchanged:

| Property | Convention | Source |
|---|---|---|
| `x`, `y` | metres | `amr/navigation/types.py` `Pose` |
| y axis | **up** (positive north) | `config/warehouse.yaml` |
| `theta` | radians | `WarehouseMap` |
| origin | the map's `dock` is `(0, 0)` | `_DEFAULT_LOCATIONS` |

The map publishes these facts in every response (`units`, `frame`, `y_axis`,
`yaw_units`) so a consumer never has to guess.

### World → screen

`amr/map/transform.py` owns the **only** coordinate conversion:

```
scale    = min(usable_w / world_w, usable_h / world_h) * zoom
screen_x = world_x * scale + offset_x
screen_y = offset_y - world_y * scale      # y flipped: world y-up, SVG y-down
```

One uniform `scale` for both axes preserves the aspect ratio, and that single
`y` negation is the only difference between the two frames. The transform is
deterministic: the same snapshot always renders byte-identically.

The browser repeats this formula in `DASHBOARD_JS` for interactive zoom/pan, but
only after the server has resolved *what* is real — the client never decides map
semantics.

## Map schema (`GET /map`)

```json
{
  "schema_version": "1.0",
  "source": "SIMULATION",
  "units": "metres", "frame": "warehouse",
  "y_axis": "up", "yaw_units": "radians",
  "warehouse": {
    "waypoints": [{"name": "dock", "x": 0.0, "y": 0.0, "theta": 0.0,
                   "source": "SIMULATION"}],
    "shelves": [], "racks": [], "obstacles": [],
    "boundary": null,
    "bounds": {"x_min": -1.0, "x_max": 5.0, "y_min": -1.0, "y_max": 4.0},
    "source": "SIMULATION",
    "note": "not modelled: ..."
  },
  "robot": {"x": 0.0, "y": 0.0, "yaw": 0.0, "source": "SIMULATION"},
  "goal": null,
  "route": [], "path": [{"x": 0.0, "y": 0.0}],
  "hazards": [], "unlocated": [],
  "zones": [],
  "safety": {"state": "IDLE", "action": "PROCEED",
             "emergency_stop": false, "hazard_state": null,
             "latched": false, "source": "SIMULATION"},
  "navigation": {"state": "IDLE"}
}
```

## What the project does **not** model yet

The warehouse is defined as **named waypoints** (`warehouse.locations`) plus
**hazard-zone rectangles** (`hazard.zones`). There is no shelf, rack,
static-obstacle or surveyed-boundary geometry anywhere in the codebase.

So the map reports those as empty/`null` with an explicit `note`, and derives its
**viewport** from the real data extent instead. The drawn frame is a fit-to-data
window, **not** a warehouse wall — the SVG says so on its face, and the UI shows
the same note.

## Hazard placement rule (C5 preserved)

A hazard is drawn **only** when its event carries a real world `location`.

* Located → appears in `hazards` with `x`/`y`.
* No location → appears in `unlocated` with a `reason`, and **no coordinates**.
* An image-space detection (`metadata.bbox`) → listed as
  `"image-space evidence only; no calibrated world location"`, never placed.

A `(0, 0)` hazard *is* placed, because `(0, 0)` is a real place (the dock).

## Travelled path

`PathHistory` keeps a **bounded, de-duplicated** trail (default 600 points ≈ 10
minutes at the 1 Hz dashboard poll):

* a pose is appended only if it moved > 1 cm, or the yaw changed — a stationary
  robot cannot fill the buffer;
* the buffer is a fixed-size deque, so the **oldest** point is dropped at the
  limit; memory is bounded no matter how long the dashboard runs.

## Dashboard panel

`GET /dashboard` gained a **Live 2D Warehouse Map** card with a source badge, a
safety badge, and a robot/goal/route/hazard summary. Interaction is read-only
and purely visual:

* scroll = zoom, drag = pan
* **Follow** re-centres on the robot each tick
* **Reset view** returns to fit-to-data
* **Labels** toggles waypoint/zone text

The map rides the existing 1 Hz telemetry poll — no second timer. There is no
movement control anywhere in the panel.

## Safety

* `amr/map/` imports no motor, PWM, serial, GPIO or robot-control module (a test
  asserts this by scanning its imports).
* The service only *reads*: never `tick`, `step`, `go_to` or `dispatch`.
* The navigator handed to the dashboard is the runtime's own; the web layer never
  steps it, so it cannot move the robot.
* A test spies on the mock serial transport and proves that repeated map reads
  write nothing to the controller.
* `GET /map` and `GET /map.svg` are GET-only; POSTing to them is 404/405.

## Limitations

* No shelf/rack/obstacle geometry — see above.
* Pose comes from `LocalNavigator` odometry, which is still **unvalidated** on
  hardware (`robot.wheel_track_m` / `wheel_diameter_m` are `null` in
  `config/robot.yaml`).
* Viewport is data-fitted, not surveyed.
* Dynamic ultrasonic obstacles are not yet mapped (the C6 `ObstacleProvider` is
  not wired to the map).
* Polling is 1 Hz; no WebSocket.

## Hardware status

**REAL ROBOT: NOT TESTED · REAL RASPBERRY PI: NOT TESTED · REAL NAVIGATION
HARDWARE: NOT TESTED.** Everything here is software-verified against mocks.

## Tests

`tests/test_map.py` (111 tests) covers the model, the transform, the placement
rule, path bounding, SVG validity/determinism/escaping, read-only guarantees, the
HTTP surface, and an end-to-end warehouse → navigation → hazard → map run.
