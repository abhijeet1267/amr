# 3D Digital Twin (C10)

The 3D twin is a **view of the same robot state as the 2D map** — not a second
robot, and not a second state model.

```text
Existing AMR Runtime
        ↓
TelemetrySnapshot
        ↓
MapSnapshot  (C9 — the single source of truth)
        ├── 2D SVG map          (C9)
        └── 3D digital twin     (C10)  ← this document
        ↓
Existing AMRWebApp dashboard
```

Both views consume the identical `MapSnapshot` object, so they cannot disagree:
if the pose changes, the 2D marker and the 3D AMR move together.

## 1. Data flow

`GET /digital-twin` builds the scene in three steps, all read-only:

1. `MapService.snapshot()` samples the runtime exactly as `GET /map` does.
2. `build_twin_state(snap)` converts world coordinates into renderer
   coordinates and assembles the scene description.
3. The browser draws that description. **The browser computes no robot state** —
   it only applies the camera transform to already-converted numbers.

The server provides state; the browser renders it. There is no server-side
render loop and no per-frame server work.

## 2. Why raw WebGL, not Three.js

The project ships **zero frontend dependencies**: no npm, no package.json, no
CDN, no build step. It must run from one self-contained Python process on a
Raspberry Pi, including offline. Pulling in Three.js would add a vendored
library, a minified blob to maintain, and an update burden for a scene that is
a few dozen boxes and cylinders.

WebGL is built into every browser, so a small hand-written renderer is lighter
and more portable here. The response declares this explicitly:

```json
"renderer": {"backend": "webgl", "library": null,
             "shading": "per-face lambert + hemisphere ambient, distance fog"}
```

If WebGL is unavailable, the panel shows a plain message and the 2D map and all
telemetry keep working — the dashboard degrades honestly rather than showing a
blank black box.

### How the scene is lit

One colour per primitive with no shading is what made the twin read as a flat
silhouette: every face of a box landed at the same brightness, so the chassis
looked like a green sticker rather than a solid. Every triangle is therefore
shaded once, as the mesh is built, from its own face normal:

- a **key light** from above/front/left, which gives each face of a box its own
  brightness — the single change that makes the scene read as 3D;
- a **sky/ground hemisphere ambient**, so an up-facing panel stays brighter than
  a down-facing one even out of the key light. A flat ambient renders every
  unlit face identically, which is what a schematic looks like.

Both terms are view-independent, so they are correct at every camera angle and
cost nothing per frame. On top of that:

- **distance fog**, using the linear view depth from the vertex shader (not
  `gl_FragCoord.z`, which is non-linear and would be uncontrollable here). The
  fog colour is `--stage`, so the ground plane dissolves into the panel;
- a **contact shadow** — three stacked opaque discs of darkened floor colour,
  giving a stepped radial falloff with no blending pass and no z-fighting.
  Without it the robot reads as hovering above the floor;
- a **0.5 m floor grid**, so the floor is a measurable surface rather than a
  coloured rectangle. It is capped, so a huge configured floor cannot stall the
  frame building grid boxes.

## 3. Coordinate system

The repository frame is authoritative and unchanged: **metres, y-up, right-handed,
yaw CCW from +x in radians**. A 3D renderer is z-up, so one conversion is applied,
in Python, in `amr/map/twin.py`:

```text
three.x =  world.x
three.y = -world.y        # y-up → screen depth
three.z =  height          # metres above the floor

rotation_z_deg = -degrees(world_yaw)
```

The yaw negation is the same axis swap the 2D SVG renderer already applies, so
`yaw = 0` points the AMR along world **+x** (its configured forward direction),
and `+pi/2` turns it 90° CCW in world terms.

This conversion is **centralised and unit tested** in `tests/test_digital_twin.py`
(origin, positive/negative coordinates, all four required angles, determinism,
NaN refusal). JavaScript never re-derives it.

Every response republishes the rule:

```json
"coordinate_system": {
  "units": "metres", "source_frame": "warehouse", "source_y_axis": "up",
  "source_yaw_units": "radians", "up_axis": "z",
  "axis_map": "three.x=world.x, three.y=-world.y, three.z=height",
  "yaw_rule": "rotation_z_deg = -degrees(world_yaw)"
}
```

## 4. API

### `GET /digital-twin`

Read-only, 200, JSON. GET only — there is no POST route, so no browser command
can reach the twin, let alone the robot through it.

| Key                   | Meaning                                                         |
| --------------------- | --------------------------------------------------------------- |
| `schema_version`      | `"1.0"`                                                         |
| `source`              | `LIVE` / `SIMULATION` / `UNAVAILABLE` (from the map, unchanged) |
| `coordinate_system`   | the published conversion above                                  |
| `geometry_disclaimer` | why the scene is schematic                                      |
| `floor`               | data-extent floor + `source: "data-extent"`                     |
| `waypoints`           | real named waypoints, with a display role                       |
| `zones`               | real `HazardZone` rectangles, extruded                          |
| `hazards`             | **placed hazards only** (real world location)                   |
| `unlocated`           | hazards with no world location, carried verbatim                |
| `route`               | the existing planned route, converted                           |
| `path`                | the bounded C9 trail — the browser keeps no history             |
| `robot`               | `position`, `rotation_z_deg`, `yaw_rad`, `source`, `model`      |
| `goal`                | the active navigation goal, converted                           |
| `safety`              | the existing `MapSafety` — displayed, never acted on            |
| `mission`             | surfaced from the C7 telemetry mission section                  |
| `renderer`            | backend declaration                                             |

## 5. The AMR model

A **procedural** model — no CAD asset, no external file:

- chassis box + deck
- four wheels at the chassis corners, each with a **hub** cap. The wheels are
  stood up on their axle: cylinders are built along `+z`, so a wheel drawn
  without the `tAxle()` rotation lies flat like a plate, which was the old
  model's biggest tell
- camera module on the front face, with a **lens barrel** — a _model_ of the C8
  sensor, never live imagery
- ultrasonic **mast + head**, so the sensor is visibly mounted rather than
  floating
- a manipulator **mount**, marked `"implemented": false` — no manipulator exists yet
- a status LED on the deck, and a white forward indicator, so heading is visible
  even from directly above

Dimensions are nominal, unmeasured, and describe a schematic AMR. The whole
model is assembled from primitives in the browser and uploaded as one vertex
buffer per frame.

## 6. Hazards: the C5/C9 rule holds

A hazard marker is drawn **only** for entries in `MapSnapshot.hazards`, which
C9 populates _only_ for events carrying a real world location. A detection that
exists solely as an image-space bounding box is passed through in `unlocated`
with a reason and **no coordinates**, so it can never be placed in 3D.

A genuine hazard at world `(0, 0)` _is_ placed. Confidence is carried through
unchanged and shown as a label.

## 7. Safety

The twin **cannot** command the robot, and this is enforced, not just intended:

- `amr/map/twin.py` imports only `math`, `dataclasses`, `typing` and the map
  snapshot module. A test greps its source for `RobotManager`, `Navigator`,
  `SafetyManager`, `serial`, `gpio`, `pwm`, `dispatch(` and fails if any appears.
- Repeated `GET /digital-twin` and `GET /map` requests write **zero** bytes to
  the mock serial transport.
- Safety state (`PROCEED` / `STOP` / `TURN` / `REPLAN`, E-STOP) is read and
  displayed. It only affects presentation — colouring, badges.
- The twin has no actuation controls: no forward/backward/rotate/stop buttons.

## 8. Dashboard

A **3D Digital Twin** card with source / safety / mission badges, the canvas, and
visualisation-only controls: orbit (drag), zoom (wheel), follow-robot, and
isometric / top / front / reset views, plus route / path / hazard / label toggles.

It is driven by the **existing 1 Hz dashboard poll** (`pollTwin()` is called from
the same `poll()` as the map), so the page still has a single polling loop.

## 9. Data sources and honesty

- `source` is inherited from the map. A mock stack wired with a navigator reports
  `SIMULATION`; a runtime with no pose at all reports `UNAVAILABLE` and shows no
  robot — a blank scene is never dressed up as live data.
- **The project contains no surveyed shelf, rack, boundary or static-obstacle
  geometry.** None is invented here. The floor spans the available data extent,
  is labelled `"source": "data-extent"`, and the panel repeats
  `geometry_disclaimer` on its face.
- A missing camera never breaks the twin.

## 10. Limitations

- No text geometry: labels live in an HTML legend, not as 3D sprites.
- Shading is per-face Lambert + hemisphere ambient, with distance fog and a
  contact shadow. There are **no** textures, no per-pixel normals, no specular
  or environment reflections, and the shadow is a stacked-disc approximation
  rather than a real shadow map. Geometry is still primitives only.
- No shelf/rack/obstacle meshes (none exist in the project — see §9).
- `implemented: false` on the manipulator mount is accurate: no arm exists.
- Hardware untested. See §11.

## 11. Testing status

**Software tested** — `tests/test_digital_twin.py` (37 tests) plus 14
`TestDigitalTwinApi` cases in `tests/test_web_server.py`, covering state
conversion, coordinates and all required yaw angles, the robot model, route,
goal, path, hazard placement (including the image-space rule), safety
pass-through, the read-only guarantee, API shape, and dashboard markup. The
served JavaScript is syntax-checked with `node --check`.

**Hardware tested: NO.** No Raspberry Pi, robot, camera or GPU was used; WebGL
was not exercised in a real browser here.

**Firmware tested: NO.** Firmware was not touched.
