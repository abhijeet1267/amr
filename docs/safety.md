# Safety System

Safety **always takes priority over navigation and control.** The system uses a
**layered** design so that a failure at any one layer still leaves lower layers
able to stop the robot. Nothing may bypass safety to make a test pass.

> **Status of the thresholds:** `config/safety.yaml` is `status: NOT_VERIFIED`.
> Every distance is a configurable *test value* until it is physically measured
> and confirmed on the real robot. Do not trust the robot at speed until
> `status: VERIFIED`.

---

## Layer 1 — Arduino immediate hardware stop (last resort)

Runs **on the Arduino**, independent of the Pi. Two independent triggers:

1. **Communication watchdog** (Phase 2). If no valid command arrives for
   `watchdog_timeout_ms` (default **1000 ms**), all motors stop and
   `WATCHDOG TRIGGERED` is sent. The robot can therefore *never* keep driving
   indefinitely because the Pi crashed, rebooted, or the cable was pulled.
2. **Proximity stop.** When a *valid* ultrasonic reading is closer than its
   stop threshold, the Arduino stops the motors immediately:
   * `FRONT < front_stop_distance_cm` (default 20 cm)
   * `REAR  < rear_stop_distance_cm`  (default 20 cm)
   * `LEFT  < left_stop_distance_cm`  (default 15 cm)
   * `RIGHT < right_stop_distance_cm` (default 15 cm)

A reading of `-1` (no echo / clear) is **not** an obstacle and does **not**
stop the robot (otherwise a clear path would falsely halt it).

The watchdog is configurable at runtime with the `WDT <ms>` command and by
`config/safety.yaml`. It is armed only after the first valid command and is
re-armed on every valid command.

## Layer 2 — Pi receives sensor + status state

The Pi maintains a structured `RobotState` (see
[`AI_CONTEXT/ARCHITECTURE.md`](../AI_CONTEXT/ARCHITECTURE.md)) that includes the
latest sensor readings,
connection status, drive state and safety state. The Pi polls `STATUS` and
`SENSOR`, and handles unsolicited `WATCHDOG`/`SENSOR` lines.

## Layer 3 — High-level decisions

The Pi-side **safety manager** (`amr/safety/safety_manager.py`) decides, based on
`RobotState`, one of: `STOP`, `WAIT`, `TURN`, `REPLAN`. Higher-level software
(navigation, warehouse tasks) **must** query the safety manager before moving,
and must act on a `STOP` immediately.

> **Scope note:** aggressive autonomous obstacle avoidance is intentionally
> **NOT** implemented yet. Only immediate, deterministic safety stops.

---

## Safety state machine (Pi robot modes)

```
        +--------------------------------------------------+
        |                                                  |
        v                                                  |
      IDLE -------------------------------------------->   |
        |   +--> MANUAL                                  |
        +-------------------------------->               |
        |                                                |
        +--> AUTONOMOUS   (only if geometry/sensors OK)  |
        |                                                |
        +------------------------------------------------+
                     |
        (any safety trigger)
                     v
                 SAFETY_STOP
                     |
        (operator acknowledges)
                     v
                   IDLE
```

* Transitions **into** `SAFETY_STOP` are **deterministic**: any safety trigger
  (watchdog, proximity, connection loss, invalid critical sensor) forces it.
* Leaving `SAFETY_STOP` requires an explicit operator action (acknowledge).
* `ERROR` is used for non-safety faults (bad config, repeated comms failure)
  and also requires operator attention.

See `amr/robot/robot_state.py` for the concrete implementation.

---

## Emergency stop (always available)
* **Software E-stop** (web UI / API) → sends `STOP` and sets `SAFETY_STOP`.
* **Watchdog** → automatic on loss of commands.
* **Physical** → the robot must always be powered from the external supply so it
  can be disconnected. **Never** power the motors from the Pi 5V or the Arduino
  5V rail.

## Physical power rule
Motors are powered by the **L298N external supply**, never by the Raspberry Pi
5V or Arduino 5V. This is a hardware requirement, not a software one.
