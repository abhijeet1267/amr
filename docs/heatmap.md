# Spatial heat map (C19)

Two density grids over **one shared extent**: where hazards were recorded, and
where the robot actually went. It is the "future spatial hazard visualisation"
`AI_CONTEXT/PROJECT_CONTEXT.md` names as the project's novelty direction, plus
the traffic half that makes the hazard half readable in context.

```bash
python -m amr.main --mock --web --mission-demo   # then open /command-center#heatmap
curl -s http://localhost:8080/heatmap | python -m json.tool
```

---

## 1. What it is (and is not)

It is a **view**, in the same sense as the 2D map and the 3D twin:

- **Read-only.** `GET /heatmap` performs no `tick()`, evaluates no hazard, and
  cannot reach an actuator. `POST /command` remains the only path to the motors.
- **Not a new state model.** It is a pure projection of two things the runtime
  already owns: the C9 `MapSnapshot` (for the extent, the travelled path and the
  waypoints) and the hazard layer's `HazardEventLog` history.
- **No invented floor plan.** Cells outside the configured geometry are simply
  empty. The project has no surveyed shelf, rack or wall geometry, and none is
  added here.

`amr/map/heatmap.py` builds both grids in Python, where they are unit tested, so
the browser and the client never re-derive a bin index. That is deliberate: an
off-by-one in a bin index is invisible in a picture and silent in a test.

---

## 2. The two grids

| Grid      | One sample is                                               | Value                     |
| --------- | ----------------------------------------------------------- | ------------------------- |
| `hazard`  | one recorded hazard event **that carries a world location** | severity-weighted (below) |
| `traffic` | one point on the travelled path                             | 1 per sample              |

**Severity weighting** (`severity_weights` is published in the payload, so a
client never guesses): `INFO` 1, `WARNING` 2, `CRITICAL` 4, and an unrecognised
severity 2 — an unknown severity must not vanish from the picture. The weighting
is a _display_ convention. It never feeds a safety decision: the hazard verdict
is computed from raw readings, not from this grid.

**Traffic is time, not distance.** The path is appended by the control loop, so
a cell's value is how long the robot was there, not how far it travelled. The
sampling rate is the clock, not the odometer.

---

## 3. The rules that keep it honest

1. **A stable extent.** The grid covers the _configured_ geometry (waypoints and
   hazard zones, padded by `margin_m`), snapped outwards to whole square cells.
   The robot's pose and the data are deliberately **excluded** from the extent: a
   heat map is read by comparing polls, and a frame that rescales every second
   cannot be compared with itself.
2. **Nothing is silently dropped.** A sample outside the extent is counted in
   `clipped` and reported, so a reader can tell "no hazards here" from "hazards
   here were not drawn".
3. **The C5 rule still holds.** An event whose evidence is image-space (a vision
   bounding box) or that has no location at all is **never placed**; it is
   counted in `unlocated` and listed in `notes`.
4. **Absence is absence.** With no configured geometry both grids are `null` and
   the source is `UNAVAILABLE` — the same rule `amr.map.snapshot.bounds_for`
   follows — rather than an invented room.
5. **Provenance is inherited.** `source` comes from the map snapshot, so a
   simulated run cannot be labelled `LIVE` by a caller that forgot a flag.

---

## 4. Payload

`GET /heatmap` — schema `1.0`:

```json
{
  "schema_version": "1.0",
  "source": "SIMULATION",
  "units": "metres",
  "frame": "warehouse",
  "y_axis": "up",
  "severity_weights": { "INFO": 1.0, "WARNING": 2.0, "CRITICAL": 4.0 },
  "hazard": {
    "cols": 20,
    "rows": 16,
    "cell_m": 0.25,
    "extent": { "x_min": -0.5, "x_max": 4.5, "y_min": -0.5, "y_max": 3.5 },
    "cells": [0.0, 4.0, 0.0, "..."],
    "row_order": "row 0 is y_min (bottom); index = row * cols + col",
    "max_value": 4.0,
    "total": 4.0,
    "samples": 1,
    "clipped": 0,
    "unlocated": 2,
    "source": "SIMULATION",
    "note": "..."
  },
  "traffic": { "...": "same shape" },
  "notes": ["2 recorded hazard event(s) carried no world location ..."]
}
```

**`row_order` is load-bearing.** The repository frame is y-up, so row 0 is the
_bottom_ row. A client that assumed row 0 was the top would draw every map
vertically mirrored — which looks entirely plausible and would never fail a
"does it render" check. Both clients are held to the published rule.

`/dashboard/state` also carries `heatmap`, byte-identical to `GET /heatmap`, so
the Command Center still polls **once** per tick. A server test asserts the
equality, exactly as it does for `map` and `twin`.

---

## 5. Where it is shown

| Surface        | Where                                                                         |
| -------------- | ----------------------------------------------------------------------------- |
| Command Center | the **Heat map** view — two graphs, plus a scale legend and per-grid readouts |
| Flutter client | the **Heat map** destination (`lib/features/heatmap/heatmap_screen.dart`)     |

Both draw the scene on a **dark stage** (the console) or the app's white panel
(the client) and read the ramps from the palette, so a theme change repaints
them. The console's stage stays dark in both themes for the same reason the map
and twin do: it is world-coordinate spatial data.

---

## 6. What is not verified

- **No hazard sensor hardware exists.** `config/hazard.yaml` is `NOT_VERIFIED`
  and no gas/smoke/fire/vision source is wired, so on the shipped configuration
  the hazard grid is **always empty**. That is the honest result, not a bug: the
  grid fills from `HazardEventLog` history, and nothing produces that history
  yet. It is exercised in tests with injected readings.
- **The thresholds behind a hazard event are unvalidated** software defaults.
- **Nothing here has been run against a physical robot.** The grids are built
  from a mocked navigator and a simulated event log.
