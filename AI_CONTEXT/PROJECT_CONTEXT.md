# PROJECT_CONTEXT — AMR (Autonomous Mobile Robot) Smart-Warehouse Platform

> **Read this first.** This directory (`AI_CONTEXT/`) is the shared memory for the
> multi-agent team. It is the contract between agents working from different
> machines. Update it in the same commit as your work.

---

## 1. What the project is

Design and development of a **modular Autonomous Mobile Robot (AMR) platform for
smart-warehouse automation**: a differential-drive robot with a safety-first,
layered control stack, plus warehouse task orchestration.

| Part | Role | Verified implementation |
|---|---|---|
| **Raspberry Pi** | Brain — web control, navigation, warehouse tasks, hazard policy | Python 3.9+, stdlib HTTP, PyYAML; `pyserial` optional |
| **Arduino UNO** | Reflexes — real-time motor drive, watchdog, hardware proximity stop | C++ firmware (`firmware/arduino/amr_controller/`) |
| **Drive** | Differential, 2× DC gear motor, L298N H-bridge | `amr/control/` |
| **Sensing** | 4× HC-SR04 ultrasonic (F/L/R/B), optional camera | `amr/sensors/`, `amr/camera/` |

**The load-bearing design rule:** every motion command funnels through one gated
API, `RobotManager`. `web/` and `warehouse/` cannot reach the motors any other
way. Safety can only ever *veto*, never be bypassed.

---

## 2. Repository map (verified)

```
config/            robot.yaml · safety.yaml · serial.yaml · warehouse.yaml · hazard.yaml
docs/              safety.md · serial_protocol.md · web_control.md · hazard.md
firmware/arduino/amr_controller/    .ino + motor_control/protocol/safety/ultrasonic (.h/.cpp)
raspberry_pi/
  amr/
    main.py            CLI entry point (--mock / --demo / --web / --config-dir)
    __init__.py        __version__
    robot/             RobotManager (the gate), RobotState, ModeController
    control/           DifferentialDrive, MotorDriver, ArduinoMotorDriver, clamp_speed
    communication/     protocol.py (single source of truth), ArduinoSerial, transport
    safety/            SafetyManager (Layer 3), SafetyDecision, SafetyAction
    hazard/            HazardManager (Layer 3.5), sources, event log  <-- newest layer
    sensors/           UltrasonicManager, UltrasonicReading
    navigation/        Navigator, LocalNavigator, Pose, Goal, NavResult
    warehouse/         WarehouseTaskManager, WarehouseMap, Task, Manipulator
    camera/            CameraManager (libcamera "pi" / "v4l2" / mock)
    web/               AMRWebApp — stdlib ThreadingHTTPServer, zero external assets
    mocks/             MockSerialTransport, MockMotorDriver, MockUltrasonicSensor, MockCamera
    logging/           setup_logging, get_logger, log_event (rotating file)
    utils/             load_config, AppConfig + per-area config dataclasses
  tests/               pytest suite
  pyproject.toml       packaging + [dev] extras
.github/workflows/ci.yml   pytest matrix (3.10/3.11/3.12) + advisory ruff
assets/            README diagrams (SVG)
```

Layer order (bottom → top): `communication → control → safety / hazard → sensors
→ robot → camera → navigation → warehouse → web`.

---

## 3. Conventions you MUST follow

These are enforced by the existing code; match them.

* **Python style** — `from __future__ import annotations` at the top of every
  module, `typing.Optional/Tuple/List` (not `X | None` in runtime positions),
  frozen dataclasses for value objects, `Enum` for vocabularies, a `to_dict()`
  for anything JSON-facing.
* **Docstrings** — every module opens with a substantial docstring explaining the
  design and *why*. Tests have module docstrings too.
* **Config** — no hardcoded tunables. Everything lives in `config/*.yaml`, is
  loaded by `amr/utils/config.py` into a dataclass, and is **validated
  fail-fast** with `ConfigError` (`_validate_*` functions).
* **Honest placeholders** — unknown hardware facts are `null` / `TODO_VERIFY` /
  `NOT_VERIFIED`, never invented numbers. `robot.yaml` geometry is `null`; the
  ultrasonic pins are `TODO_VERIFY`.
* **Testing** — `raspberry_pi/tests/test_<area>.py`. Hardware is never required:
  use `amr/mocks/`. Run `cd raspberry_pi && python -m pytest -q`.
* **Interfaces** — add new behaviour *behind* `RobotManager`, never by reaching
  into `MotorDriver` / `ArduinoSerial`. Prefer additive, opt-in changes with a
  default that preserves existing behaviour.

---

## 4. Ground rules (from CONTRIBUTING.md — non-negotiable)

* **Never bypass the safety layer.** `RobotManager` is the single gated entry
  point to the motors.
* **Fail safe.** Any new stop condition routes through
  `SafetyManager` / `ModeController`, ends in `SAFETY_STOP` with motors at zero,
  and **never auto-releases**.
* **Hardware is never required to test.** New behaviour needs unit tests on the
  mocks.
* **Keep the serial protocol stable.** The firmware and
  `amr/communication/protocol.py` share a documented text protocol
  (`docs/serial_protocol.md`). Change both sides together.
* **Keep it small and readable.** One class does one layer of the stack.

---

## 5. Multi-agent working agreement

* The repository is the source of truth. **Do not assume you are starting from
  zero** — read this directory, run `git status`, inspect the implementation.
* Do not overwrite another agent's work, rename public interfaces without
  checking dependents, or reorganise the repository.
* Pick an unassigned task from `TASK_BOARD.md`; mark it `[~]` before starting.
* Follow `READ → PLAN → IMPLEMENT → TEST → DOCUMENT → COMMIT → HANDOFF`, then
  update `HANDOFF.md` with what changed, tests run, known issues, the commit
  hash, and the recommended next task.
* **Honesty about test status is mandatory.** Clearly distinguish *tested*,
  *partially tested*, *not tested*, and *hardware-dependent*.

---

## 6. Hardware safety

This project drives a physical robot.

* Prefer simulation / dry-run (`--mock`) first. `python -m amr.main --mock --web`
  and `python -m amr.hazard` run the whole stack with no hardware.
* Keep the emergency stop available; never disable watchdogs or safety
  mechanisms for convenience.
* Do not assume a sensor is physically connected because software exists for it.
* Document hardware-dependent tests and never present them as verified.

---

## 7. Novelty direction

The project is extended with a **context-aware multi-hazard safety layer**:
gas/smoke, camera vision, fire/human detection, robot state, robot location and
navigation state aggregated into `NORMAL / WARNING / SLOW / STOP / EMERGENCY`,
with an auditable, location-tagged hazard event history feeding a future spatial
hazard visualisation. See `docs/hazard.md`.

**Do not claim** that basic navigation, RFID, camera streaming or obstacle
avoidance alone is novel.

---

## 8. Key commands

```bash
cd raspberry_pi
source .venv/bin/activate

python -m pytest -q                 # full suite (hardware-free)
python -m amr.main --mock --web     # web panel + mock stack
python -m amr.warehouse --mock      # scripted dock -> shelf -> station -> dock
python -m amr.hazard                # scripted hazard scenario, no hardware
```

Config overrides: `--config-dir <dir>` or `$AMR_CONFIG_DIR`. Logs honour
`$AMR_LOG_DIR`.

