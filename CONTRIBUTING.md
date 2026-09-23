# Contributing to AMR

Thanks for helping make the robot safer and smarter. A few ground rules keep the
stack testable and the hardware safe.

## Development setup

```bash
cd raspberry_pi
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run the tests

```bash
cd raspberry_pi
python -m pytest -q
```

The whole suite runs against the **mock transport and mock motor driver** — no
hardware, no `pyserial` device, no camera required. If `opencv-python`/`numpy`
are installed the two camera tests run; otherwise they skip gracefully. The suite
must stay green on Python 3.10 – 3.12 (see `.github/workflows/ci.yml`).

## Ground rules

- **Never bypass the safety layer.** `RobotManager` is the single gated entry
  point to the motors. Add new motion behind it, not by reaching into
  `MotorDriver` / `ArduinoSerial` directly.
- **Fail safe.** Any new stop condition should route through
  `SafetyManager`/`ModeController` so the robot ends in `SAFETY_STOP`, motors at
  zero, and never auto-releases.
- **Hardware is never required to test.** New behaviour must be covered by unit
  tests using the mocks under `amr/mocks/`.
- **Keep the serial protocol stable.** The Arduino firmware and the Pi parser
  (`amr/communication/protocol.py`) share a documented text protocol — see
  `docs/serial_protocol.md`. Change both sides together.
- **Keep it small and readable.** One class does one layer of the stack.

## Commit & PR

- Conventional, scoped subjects: `safety: clamp standoff to non-negative`.
- Every PR that touches `amr/` should run the full test suite locally.
- Update `docs/` and this README when behaviour or the protocol changes.
