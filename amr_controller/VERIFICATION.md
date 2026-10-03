# Verification matrix

Factual record of what has been verified and how. Entries are only marked
VERIFIED where the stated evidence was actually produced; device and physical
items are deliberately NOT VERIFIED.

Evidence states used below: **COMPILED** (a build produced the artifact),
**RUNTIME VERIFIED** (launched + screens/interaction checked), **REAL ROBOT
VERIFIED** (the production client's HTTP reached the mock robot), **PHYSICAL
DEVICE VERIFIED** (ran on a real device/emulator) and **PHYSICAL ROBOT
VERIFIED** (a real physical robot was commanded). These are distinct levels and
are never conflated.

## Software verification (automated, reproducible)

| Capability | Evidence | Status |
|---|---|---|
| Flutter compilation | `flutter analyze` clean | VERIFIED |
| Dart test suite (models, shell) | `flutter test` green | VERIFIED |
| Flutter client → mock robot (real HTTP) | `test/client_integration_test.dart` — real `RobotApiService`/`RobotProvider` over real TCP sockets against `MockRobot` | VERIFIED |
| Connection state transition (disconnected → connected) | `test/client_integration_test.dart` `connection/` | VERIFIED |
| Motion command (MANUAL → forward/stop) | `test/client_integration_test.dart` `motion/` | VERIFIED |
| Invalid command handling (speed 400) | `test/client_integration_test.dart` `invalid command/` | VERIFIED |
| E-STOP safety path (SAFETY_STOP → motion veto) | `test/client_integration_test.dart` `E-STOP safety/` | VERIFIED |
| Telemetry parsing (incl. null-preservation) | `test/client_integration_test.dart` + `test/models_test.dart` | VERIFIED |
| UI → client → HTTP → robot → state → UI | `integration_test/connection_test.dart` — real `ConnectionScreen` ping flips the badge to "Connected" | VERIFIED (CI) |
| Full app shell on-device command flow | `integration_test/device_runtime_test.dart` — real `AmrControllerApp` shell: Connection + Teleop, MANUAL→forward→stop→E-STOP→veto over real HTTP | VERIFIED (Android emulator) |
| Web launch + render | browser run | VERIFIED |
| All 7 platform builds | `flutter-build.yml` CI + local APK/AAB/Web | VERIFIED (COMPILED) |

## Platform runtime verification

| Platform | Build | Runtime | Robot communication | Status |
|---|---|---|---|---|
| Android | release APK | **real emulator (API 35, arm64-v8a)** — installed, launched, `MainActivity` top-resumed, no fatal `logcat` entries | integration test reached MockRobot over real socket; command flow verified | **RUNTIME VERIFIED + REAL ROBOT VERIFIED (mock)** |
| macOS | CI `.app` | not launched (no full Xcode) | — | COMPILED |
| Windows | CI ZIP (`amr_controller.exe`) | not launched (no Windows host) | — | COMPILED |
| Linux | CI bundle | launch proven only by the CI integration test under xvfb | integration test reached MockRobot | PARTIAL — launch+connected proven; interactive use not verified |
| Web | local `build/web` | launched in Chrome | UI-only (browser CORS wall; not weakened) | RUNTIME VERIFIED (UI only) |
| iOS | CI unsigned `.app` | not launched (no device + signing) | — | COMPILED |

## Physical robot / hardware

| Capability | Evidence | Status |
|---|---|---|
| Android real-device runtime | Android 15 emulator (no physical phone) | **EMULATOR VERIFIED** — physical device NOT verified |
| iOS real-device runtime | no device + signing | NOT VERIFIED |
| macOS runtime launch | no full Xcode on this host | NOT VERIFIED |
| Windows runtime launch | no Windows host | NOT VERIFIED |
| Linux runtime launch | CI integration test only | PARTIAL |
| Physical robot control | no physical robot, no documented robot address/hardware | NOT VERIFIED |

## Reproduce

```bash
cd amr_controller
make test-e2e        # flutter analyze + flutter test (real-client integration)
```

The mock robot is `lib/testing/mock_robot.dart` (in-process `dart:io` server on
loopback). It re-implements the robot's exact HTTP contract and records every
request so tests can assert the client emitted the right method/path/body.

On-device runtime verification (Android emulator):

```bash
flutter test integration_test/connection_test.dart -d <device-id>
flutter test integration_test/device_runtime_test.dart -d <device-id>
```

The Linux UI integration test runs in CI:

```text
.github/workflows/flutter-build.yml  →  "integration test" job
```