# Gripper manipulator (C16)

Status: **Driver implemented, unit-tested, opt-in.** No hardware ships here.

The warehouse AMR can tell you it picked a box. What C16 adds is the driver
that would make that claim *true* on real hardware: an actuator contract, a
confirm-first end-effector driver, a config backend, and a fail-fast factory
that refuses to run the gripper backend without injected I/O.

> **No gripper hardware exists in this repository.** There is no servo, no arm,
> no motor driver, no firmware verb and no serial command for an end effector.
> Everything below is validated against a fake actuator in
> `raspberry_pi/tests/test_warehouse.py`. **No physical gripper has ever been
> moved by this code**, and nothing here claims anything about real I/O
> timings, jaw force, limit-switch behaviour or feedback latency.

## Where this fits

```
make_manipulator("gripper", actuator)  ->  GripperManipulator  ->  GripperActuator
   (config: warehouse.manipulator)          (carry state,           (your I/O:
                                             confirm-first rules)     servo lib, GPIO,
                                                                        serial verb, ...)

WarehouseTaskManager.create(..., gripper_actuator=...)   <-- the injection point
```

`GripperActuator` is injected the same way `amr.hazard.sources.HazardSource` and
`amr.rfid.reader.RfidReader` are: the driver never talks to a bus itself, so
the whole path is testable with nothing plugged in.

## The actuator contract (`GripperActuator`)

```python
def close(self) -> bool: ...    # True only on hardware confirmation
def open(self) -> bool: ...     # True only on hardware confirmation
def holding(self) -> Optional[bool]: ...   # presence sensor, None if absent
```

* `close()` / `open()` return `True` **only when the hardware confirms the
  motion completed** — a limit switch, an encoder, current sense. Sending the
  command is not confirmation; that distinction is the whole reason this
  backend exists.
* `holding()` is a cross-check that may legitimately be `None` on a gripper
  with no presence sensor. It is also allowed to be *missing entirely* — the
  driver feature-detects it.

## The driver (`GripperManipulator`)

Implements the existing `Manipulator` protocol, so it drops into the existing
task pipeline with no changes to `PICK` / `PLACE` handling.

Honest-failure rules (do not weaken — each has a test):

| Situation | Result |
|---|---|
| `close()` / `open()` returns `False` (not confirmed) | action fails, `"... not confirmed by actuator"` |

## Configuration

```yaml
warehouse:
  manipulator: "mock"   # "null" | "mock" (default) | "gripper"
```

| Backend | Behaviour |
|---|---|
| `null` | `NullManipulator` — no end-effector, pick/place are no-ops that report success |
| `mock` | `MockManipulator` — records picks/places; **the shipped default** |
| `gripper` | `GripperManipulator`; **requires an injected actuator** |

**No silent fallback.** `make_manipulator("gripper")` with no actuator raises
`ValueError`, and an unknown backend name raises too — previously both quietly
produced a mock, which would let an operator believe real hardware was picking
while nothing moved. `MANIPULATOR_BACKENDS` is the single source of truth
shared by the factory, config validation and this page.

Because the shipped `config/warehouse.yaml` still says `manipulator: "mock"`,
an existing deployment behaves exactly as before until an operator opts in.

## Wiring it up

```python
from amr.utils.config import load_config
from amr.warehouse.task_manager import WarehouseTaskManager

class MyActuator:                      # whatever drives your hardware
    def close(self) -> bool:  ...      # True only when confirmed
    def open(self) -> bool:   ...
    def holding(self):         ...

mgr, wh = WarehouseTaskManager.create(
    load_config(),
    gripper_actuator=MyActuator(),     # the injected I/O
)
```

Config validation rejects an unknown `manipulator` value at startup
(`ConfigError`), before the robot is allowed to move.

## Tests

`raspberry_pi/tests/test_warehouse.py` covers the contract rules above, the
factory's refuse-to-degrade behaviour, the manager's error propagation, and a
full pick → place → return cycle against a stateful fake actuator (the real
task pipeline, safety gate and dock return included). `test_config.py` covers
backend validation. **Hardware is not tested and cannot be tested here.**

## What a real implementation still needs

1. **An actuator** wrapping the actual I/O — a servo/GPIO library, or a new
   firmware verb in `docs/serial_protocol.md` (the protocol currently has no
   end-effector command).
2. **A confirmation source** — limit switch, encoder or current sense, so
   `close()`/`open()` can honestly return `True`.
3. **A presence sensor** for `holding()`, optional but strongly preferred: it
   is what distinguishes "the jaws moved" from "the jaws moved onto a box".
4. **Timing and safety review** — approach speed, jaw force, and what happens
   when a pick fails mid-cycle. None of this is modelled here.

| `holding()` says `False` right after a confirmed close | pick fails — closed on nothing is not a pick |
| `holding()` says `True` right after a confirmed open | place fails — open while still gripping is not a place |
| `place()` asked for a different `payload_id` than the one carried | place fails **before the jaws move** — the carried box is not dropped at the wrong station |
| pick while already carrying | fails, `"already carrying ..."` |
| place while empty | fails, `"not carrying anything"` |
| actuator method raises | caught; the action reports `False` with the exception text in `last_error` — hardware never crashes the task loop |
| `holding()` itself raises or is absent | degrades to confirmation-only (never blocks a good pick) |

Every refusal records a human-readable reason in `last_error`, which
`WarehouseTaskManager` copies onto the failing `Task` — an unexplained failed
pick is useless to whoever has to debug it.

`reset()` clears only the *local* carry state. It is an operator action and
never a claim that the physical jaws opened.
