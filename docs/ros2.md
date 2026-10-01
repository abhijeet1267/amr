# ROS 2 bridge (C18)

> **No ROS installation exists in this repository.** Zero `rclpy` imports
> anywhere — not in `ros2/`, not in the core `amr` stack, not in CI. Every
> "message" below is a plain Python dict shaped like its ROS counterpart; **no
> topic has ever been published or received by this code.** The `rclpy` node
> that would own real publishers/subscribers (`ros2/amr_bringup`) is **not
> built yet**.

## What this is

The seam where the dependency-free AMR stack meets ROS 2: pure translation
functions in `ros2/bridge.py`.

```
outbound:  TelemetrySnapshot -> geometry_msgs/PoseStamped-shaped dict
           HazardStatus      -> diagnostic_msgs/DiagnosticStatus-shaped dict
inbound:   geometry_msgs/PoseStamped-shaped dict -> amr.navigation.Goal
```

Because the functions speak plain dicts, the core stack keeps importing with
no ROS installed — C18's hard rule. The eventual `rclpy` node does nothing but
`msg = dict(...)` / `pub.publish(msg)` on top of these functions; all the
translation logic is here, where it can be unit tested without ROS.

## Hard rules

1. **Optional.** No `import rclpy` / `ament` / `colcon` anywhere in `ros2/` or
   `raspberry_pi/amr/` — asserted by `tests/test_ros_bridge.py`.
2. **Not a control path.** The bridge never references `RobotManager`, the
   serial transport, a motor driver, or `POST /command` — also asserted by the
   tests. Inbound goals are handed to the **existing** warehouse task queue
   (`WarehouseTaskManager.submit_move`), so Layer-3 safety still gates every
   motion command. A ROS goal cannot bypass the safety layer any more than the
   web panel can.

## API (`ros2/bridge.py`)

| Function | Direction | Payload |
|---|---|---|
| `pose_stamped_from_snapshot(snapshot)` | outbound | `{"header": {"frame_id": "map", ...}, "pose": {"position": {...}, "orientation": {...quaternion...}}}` |
| `hazard_to_diagnostic(status)` | outbound | `{"name": "amr_hazard", "level": 0..3, "message": ..., "values": [...]}` (diagnostic_msgs shape) |
| `goal_from_pose_stamped(msg, name="ros_goal")` | inbound | `PoseStamped`-shaped dict → `amr.navigation.Goal`; raises `ValueError` when there is no usable position |
| `pose_stamped_to_goal(msg, name)` | inbound | backwards-compatible alias |

Constants: `MAP_FRAME = "map"`, `BASE_FRAME = "base_link"`,
`BRIDGE_SCHEMA_VERSION = "1.0"`, and `DIAGNOSTIC_OK/WARN/ERROR/STALE`.

### Honesty rules preserved by the translators

* A position that no sensor produced stays `None` in the outbound message —
  the same never-fabricate-a-number rule as the telemetry contract (NaN/inf
  are coerced to `None` too).
* An unreadable quaternion on an inbound goal degrades to yaw `0.0` with a
  note appended to the goal's name; a missing/non-finite **position** raises,
  because navigating to a fabricated coordinate is never acceptable.
* An unknown hazard state maps to `DIAGNOSTIC_STALE`, never to `OK`.
* `HazardState` STOP/EMERGENCY map to `DIAGNOSTIC_ERROR` with
  `blocks_motion=true`, mirroring `HazardState.blocks_motion` (the mapping is
  asserted against the real enum in the tests).

## What is deliberately missing

* **No node, no topics, no `ros2/amr_bringup` package.** Building it requires
  a ROS installation this repository does not have; pretending otherwise
  would be a claim, not a delivery.
* No `nav_msgs/Path`, no `tf2` broadcaster, no `sensor_msgs` — the bridge
  publishes/absorbs only what the existing stack can honestly supply.
* Goals are not subscribed anywhere yet; `goal_from_pose_stamped` is the
  tested seam a future subscriber will call.

## Tests

`raspberry_pi/tests/test_ros_bridge.py` (25 tests), all with no ROS:

* outbound PoseStamped translation (missing coords stay `None`, NaN/inf
  degrade, quaternion round-trip),
* outbound diagnostic mapping for every `HazardState`,
* inbound goal parsing (valid, rejected, degraded cases),
* the optionality contract (no ROS import in `ros2/` or `amr/`),
* the no-control-path rule (bridge sources reference no motor/serial/command
  API).

## Reproduce

```bash
cd raspberry_pi
python -m pytest tests/test_ros_bridge.py
```

No ROS, no hardware, no network needed.

---

# Future: `ros2/amr_bringup` (not built)

The task board's end state for C18 — a thin `rclpy` node that publishes
`RobotState` / `HazardStatus` and subscribes to goals — lives here when someone
with a ROS installation builds it. It must:

1. import only `ros2.bridge` from this repository (the core `amr` package must
   not gain a ROS dependency),
2. hand inbound goals to `WarehouseTaskManager.submit_move` — never drive the
   navigator or `RobotManager` directly,
3. keep working with ROS absent: `import amr` must not require `rclpy`.

Until that package exists, this document and `ros2/bridge.py` are the whole
of the ROS integration, and nothing more should be claimed.
