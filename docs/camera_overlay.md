# C13 — Camera + hazard overlays

C13 draws hazard bounding boxes **on the camera image** in the existing
dashboard. It is display-only: it reads a frame description and a list of
hazard events, and returns a description. It has no path to a motor, GPIO or
serial port, and it adds no write endpoint.

## Data flow

```
SimulatedVisionDetector / real detector
        │  VisionDetection (class, confidence, bbox, source, …)
        ▼
VisionHazardSource          (C5 — evidence only)
        ▼
HazardManager → HazardEvent (metadata["bbox"] = [x, y, w, h]; location=None)
        ▼
GET /camera/overlay          build_camera_overlay(frame, active_events)
        ▼
CameraOverlay (JSON)         space="image", units="pixels"
        ▼
Dashboard: SVG <rect> + label drawn 1:1 over the <img>
```

The overlay is built from the **same cached frame** that `GET /camera/frame`
serves, so a box always describes the picture actually on screen.

## The coordinate rule

This is the part C13 exists to protect.

* A detector's bounding box is **image space** — pixels. It is never a
  warehouse coordinate.
* C13 **reuses** the existing validated `VisionBoundingBox` from
  `amr.hazard.vision` rather than inventing a second box type. A test asserts
  they are the same object.
* `OverlayBox` has **no world-position field at all**, and the payload names the
  field `image_bbox` (not `bbox`) with an explicit `"space": "image"`.
* The payload publishes `"world_transform": null`. The project stores no camera
  calibration, so none is performed or implied.
* A source-level test fails if a helper named `image_to_world`,
  `metres_per_pixel`, `pixels_per_metre`, `ray_cast` or similar ever appears in
  `amr/camera/overlay.py`.

### The four buckets

An event lands in exactly one bucket, and the buckets are deliberately distinct:

| Bucket | Meaning | Drawn on image? |
|---|---|---|
| `boxes` | Has an image bbox **and** matches this camera | ✅ yes, in pixels |
| `world_located` | Has a real `location` — belongs on the C9 map | ❌ no |
| `without_bbox` | No usable image geometry | ❌ no |
| `other_source` | From a different camera | ❌ no |

A detection carrying **both** a world location and an image box goes to
`world_located`: the world position is the stronger fact, and the image box is
not smuggled in behind it. Tested explicitly.

## Camera identity (why `camera_id` exists)

`CameraFrame.source` names the **backend** (`"SimulatedCamera"`,
`"RaspberryPiCamera"`). `VisionDetection.source` is a **camera identity**
(`"camera_front"`). These are different things.

With several cameras live, painting `camera_rear` detections onto a
`camera_front` image would be a straightforward lie. The overlay therefore takes
an explicit `camera_id` and only draws events whose source matches it. When the
frame's source is unknown, the association is recorded as `other_source` rather
than assumed.

`camera_id` is declared in the existing `CameraConfig`:

```yaml
camera:
  enabled: true
  device: "pi"
  resolution: "1280x720"
  camera_id: "camera_front"   # the identity detections are stamped with
```

It defaults to `None` ("not declared"), in which case the overlay falls back to
the backend name — correct only for a single-camera deployment.

### Pre-existing bug found and fixed

`config/robot.yaml` places `camera:` as a **sibling** of `robot:`, but the
config loader read only `robot.camera`. Every camera setting in the shipped
config was therefore silently ignored and the dataclass defaults were used
instead. This predates C13 (verified against the C7 baseline). Both layouts are
now accepted, with a regression test asserting the shipped file is honoured.

## Simulated scenarios

C5's named scenarios carried **no bbox at all**, so C13 added four that
exercise image geometry. All are simulation input and imply no accuracy:

| Scenario | Purpose |
|---|---|
| `person_bbox` | One person, 640×480 frame |
| `bbox_multiple` | Three hazards at different positions |
| `bbox_partially_outside` | A box overhanging the right edge |
| `bbox_world_and_image` | Both spaces at once, to prove separation |

The twelve original scenarios are unchanged and still asserted present.

## API

`GET /camera/overlay` → **always 200**, even with no camera. A camera-less
deployment gets a valid empty schema rather than an error.

```json
{
  "schema_version": "1.0", "space": "image", "units": "pixels",
  "world_transform": null,
  "image": {"width": 640, "height": 480, "camera_id": "camera_front",
            "backend": "RaspberryPiCamera", "frame_id": 1245,
            "timestamp": 1700000000.0, "status": "LIVE"},
  "boxes": [{"kind": "PERSON", "severity": "WARNING", "confidence": 0.91,
             "label": "PERSON", "image_bbox": {"x":120,"y":140,
                                               "width":90,"height":180},
             "space": "image", "fully_visible": true, "color": "#38bdf8"}],
  "box_count": 1, "drawable": true,
  "world_located": [], "without_bbox": [], "other_source": []
}
```

## Dashboard

The camera card gained an SVG overlay layer positioned over the image, plus an
`Overlays` count and a note explaining anything that could *not* be drawn
("2 world-located: on the 2D map", "1 from another camera"). The overlay rides
the **existing 1 Hz tick** — there is no second timer, and a test asserts it.

## Safety

- Display-only. No new POST route; `POST /command` remains the only actuator path.
- A source-level test parses `amr/camera/overlay.py` and fails if it imports
  `serial`, `RPi`, `gpio`, `smbus`, `socket` or `threading`, or contains
  actuator vocabulary.
- A runtime test asserts repeated overlay/frame/status reads write **zero** bytes
  to the mock serial transport.
- The overlay cannot trigger motion, replanning, or a mission change.

## Limitations

- **Hardware tested: no.** Software/mock only; no physical camera was used and
  no detection accuracy is claimed.
- No camera calibration exists, so image→world conversion is genuinely absent
  by design. A world-located hazard still reaches the C9 map through its
  `location`.
- The legacy `CameraManager` path serves JPEG but exposes no `CameraFrame`
  metadata, so the overlay reports null dimensions there rather than guessing.
- Overlays are drawn from the *latest* event snapshot; there is no per-frame
  tracking or temporal smoothing.
- Multi-camera support is modelled (source matching) but the runtime currently
  exposes a single camera.

---

# C15b — Real camera backend

C15b adds **real camera acquisition** behind the existing `VisionDetector`
protocol. It is the "Stage A" of vision: frames come from an actual camera;
object-detection inference is deliberately *not* bundled.

## Architecture

```
CameraSource                       (amr.camera.frame — already existed, C8)
   ├── SimulatedCameraSource       deterministic, no hardware
   ├── RaspberryPiCameraSource     picamera2 → libcamera-still → none
   └── UnavailableCameraSource     explicit "no camera"
        │
        ▼  CameraFrame (timestamp, width, height, frame_id, source, status)
   CameraFrameDetector             (new — amr/camera/detector.py)
        │  .detect() → [VisionDetection]
        ▼
   VisionHazardSource(frame_provider=camera.read)     (extended, not duplicated)
        │
        ▼
   HazardManager → HazardEvent → safety / navigation / telemetry / dashboard
```

The camera backend only acquires frames. It makes **no** hazard, safety or
navigation decision, and the whole path is display- and evidence-only.

## No ML dependency

`CameraFrameDetector` takes an **optional** `inference(frame)` callable. With
none supplied it reports `inference_configured: false` and returns no
detections. That is the honest state: a camera that is not wired to a model
must not pretend to see hazards. No YOLO, Torch, TensorFlow, OpenCV-DNN or
model weights were added, and `import amr.camera` pulls in none of them — a
test asserts that in a subprocess.

Supplying a model later is a config change plus a callable; the hazard pipeline
downstream is untouched.

## Configuration

`camera.resolution` is now actually honoured. It was previously read from
`cam_cfg.width` / `cam_cfg.height`, which `CameraConfig` does not define, so
the setting was silently discarded and every camera opened at the 640x480
fallback. `amr.main.parse_resolution()` accepts `"1280x720"`, `"1280X720"`,
`"640*480"` and a bare number, and falls back safely on nonsense.

| Key | Meaning |
|---|---|
| `camera.enabled` | when false, `build_frame_detector()` returns `None` |
| `camera.resolution` | `"WIDTHxHEIGHT"`, applied to both backends |
| `camera.camera_id` | source identity carried into detections (e.g. `camera_front`) |

## Image space is still image space

The C13 rule is unchanged and explicitly tested end-to-end: a detection's bbox
is stored in `metadata["bbox"]` in image pixels alongside
`metadata["image_size"]`, and `HazardEvent.location` stays `None`. No
image→world conversion is performed or implied, because the project stores no
camera calibration.

## Graceful degradation

Without `picamera2` the Pi backend reports `UNAVAILABLE` and names why
(`picamera2 unavailable: No module named 'picamera2'`). `start()`/`stop()` are
idempotent and never raise, so a missing camera cannot stop the runtime. A
frame may still be returned, but it is flagged `UNAVAILABLE` with null
dimensions and can never masquerade as real imagery.

A failing detector yields a `ROBOT_FAULT` / `WARNING` reading — deliberately
*not* `ERROR`/`STOP`, because a camera problem must not by itself halt a robot
that is otherwise safe to drive.

## Hardware status

**Camera hardware: NOT TESTED.**

- The development machine has no `picamera2`; the Pi path was verified only in
  its unavailable state.
- The Pi Camera V2 8MP uses the 15-pin connector while the Raspberry Pi 5 uses
  the smaller one, so a **15-pin → 22-pin adapter** is required. That has not
  been fitted, and no frame has ever been captured from the physical sensor.
- No inference model is bundled, so no detection accuracy of any kind is
  claimed — the confidence figures in the tests are inputs to the pipeline,
  not measurements of model performance.

