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

> **Scope note (updated by C6):** immediate, deterministic safety stops have
> always been the priority. C6 now *additionally* activates `TURN`/`REPLAN` for
> **non-blocking** obstacles. It never applies to a critical/emergency
> condition, and it cannot turn a `STOP` or `WAIT` into motion — see
> [C6 obstacle avoidance](#c6--obstacle-avoidance) below.

---

## C6 — obstacle avoidance

> **Software / simulation only.** No physical robot, no camera, no ultrasonic
> hardware and no Arduino were involved. Every threshold in
> `config/safety.yaml` under `safety.avoidance` is a **NOT_VERIFIED** software
> default and must be measured before any real use. Avoidance is `enabled: false`
> by default.

### Control flow

```
        vision / ultrasonic evidence
                  |
        HazardManager (Layer 3.5)
        severity + confidence gate
                  |
       CRITICAL?  ---- yes ---->  STOP / EMERGENCY  ──>  RobotManager  (unchanged)
                  | no
        WARNING (non-blocking)
                  |
        report_from_hazard()  ->  ObstacleReport
                  |
        AvoidancePolicy.decide( Layer-3 verdict , obstacle , clearance )
                  |
   STOP/WAIT from Layer 3 ----------> returned unchanged  (never upgraded)
                  | PROCEED
                  |
      +-----------+------------+
      |                        |
   TURN  (a side is         REPLAN  (heading cannot be
         proven clear)              reasoned safely)
      |                        |
   bounded arc            hold + retry (budgeted)
      |                        |
      +-----------+------------+
                  |
        LocalNavigator -> command(l, r)  [the ONE existing egress]
                  |
        RobotManager.move() -> existing gate
```

### Safety priority

The ordering above is the whole safety argument, and it is enforced in code:

1. **`SafetyManager.check()` returns the Layer-3 verdict first.** If it is
   `STOP`, the avoidance policy returns `STOP` immediately — TURN/REPLAN are
   never even evaluated. `WAIT` is likewise returned unchanged.
2. **A critical obstacle never reaches avoidance at all.** It raises
   `STOP`/`EMERGENCY` in the hazard layer, which blocks motion in
   `RobotManager` before navigation is asked for a command. This path is
   byte-for-byte unchanged from before C6.
3. **Only a non-blocking (`WARNING`) obstacle is avoidable.** That is exactly
   the case where the robot is allowed to move at all, so acting on it cannot
   weaken any existing guarantee.
4. **The navigator has no motor access.** Manoeuvre commands are ordinary
   wheel commands emitted through the same `command()` callback, so they pass
   through the same `RobotManager` gate (mode, E-STOP, speed bounds) as before.
   C6 adds no second path to the motors, GPIO or Arduino.

### Turning

A turn is only proposed when the *target* side is **known clear** — its measured
clearance must exceed `open_clearance_m`. The roomier side wins for a front
obstacle. With no clearance feed, an unknown side, or a `NaN` reading, the
policy **replans instead of guessing a heading**. An obstacle on the left
steers right, and vice versa.

### Loop guard

`max_replans` bounds the attempts spent on a *single* obstacle episode. When it
is exhausted the navigator sets `NavStatus.FAILED` and commands zero, rather
than manoeuvring forever. The budget resets when the obstacle clears, so a new
obstacle gets a fresh allowance while one persistent obstacle cannot loop.

### Configuration

```yaml
safety:
  avoidance:
    enabled: false          # off by default; pre-C6 behaviour when false
    max_replans: 3          # per-episode budget, then FAILED
    turn_speed_scale: 0.5   # NOT_VERIFIED software default
    turn_duration_s: 0.6    # NOT_VERIFIED software default
    open_clearance_m: 1.0   # NOT_VERIFIED software default
```

### Wiring

`LocalNavigator` takes optional `avoidance`, `obstacle_provider`,
`clearance_provider` and `decision_provider` callables. **All default to
`None`**, in which case the navigator behaves exactly as it did before C6 and no
provider is ever called. This is why the existing warehouse, C2 web and C5
vision tests are unaffected.

### Known limitations

* Turn geometry is a fixed timed arc, not a closed-loop controller; it does not
  re-plan from feedback as a real localiser would.
* No map, no global path planner and no cost map: `REPLAN` retries the existing
  straight-line approach, it does not compute a different route.
* Clearance comes from a provider that is not yet wired to the ultrasonic
  manager, so in the default configuration avoidance always replans.
* Nothing here has been run on hardware.


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
