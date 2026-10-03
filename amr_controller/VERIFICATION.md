# Verification matrix

Factual record of what has been verified and how. Entries are only marked
VERIFIED where the stated evidence was actually produced; device and physical
items are deliberately NOT VERIFIED.

## Software verification (automated, reproducible)

| Capability                                             | Evidence                                                                                                                          | Status              |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- | ------------------- |
| Flutter compilation                                    | `flutter analyze` clean                                                                                                           | VERIFIED            |
| Dart test suite (models, shell)                        | `flutter test` green                                                                                                              | VERIFIED            |
| Flutter client → mock robot (real HTTP)                | `test/client_integration_test.dart` — real `RobotApiService`/`RobotProvider` over real TCP sockets against `MockRobot`            | VERIFIED            |
| Connection state transition (disconnected → connected) | `test/client_integration_test.dart` `connection/`                                                                                 | VERIFIED            |
| Motion command (MANUAL → forward/stop)                 | `test/client_integration_test.dart` `motion/`                                                                                     | VERIFIED            |
| Invalid command handling (speed 400)                   | `test/client_integration_test.dart` `invalid command/`                                                                            | VERIFIED            |
| E-STOP safety path (SAFETY_STOP → motion veto)         | `test/client_integration_test.dart` `E-STOP safety/`                                                                              | VERIFIED            |
| Telemetry parsing (incl. null-preservation)            | `test/client_integration_test.dart` + `test/models_test.dart`                                                                     | VERIFIED            |
| UI → client → HTTP → robot → state → UI                | `integration_test/connection_test.dart` — real `ConnectionScreen` ping flips the badge to "Connected" (run in CI on Linux + xvfb) | VERIFIED (CI)       |
| Web launch + render                                    | browser run                                                                                                                       | VERIFIED            |
| All 7 platform builds                                  | `flutter-build.yml` CI + local APK/AAB/Web                                                                                        | VERIFIED (COMPILED) |

## Hardware / device verification

| Capability                  | Evidence                                                                                                     | Status                                                                                  |
| --------------------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| Android real-device runtime | no device/emulator                                                                                           | NOT VERIFIED                                                                            |
| iOS real-device runtime     | no device + signing                                                                                          | NOT VERIFIED                                                                            |
| macOS runtime launch        | no full Xcode on this host (CI compiles macOS but does not launch it)                                        | NOT VERIFIED                                                                            |
| Windows runtime launch      | CI builds the ZIP; no Windows host to launch it                                                              | NOT VERIFIED                                                                            |
| Linux runtime launch        | Linux build compiles; the _integration test_ runs the app's Linux runner in CI under xvfb (that IS a launch) | PARTIAL — the integration test proves launch-to-Connected; interactive use not verified |
| Physical robot control      | no physical robot                                                                                            | NOT VERIFIED                                                                            |

## Reproduce

```bash
cd amr_controller
make test-e2e        # flutter analyze + flutter test (real-client integration)
```

The mock robot is `test/helpers/mock_robot.dart` (in-process `dart:io` server on
loopback). It re-implements the robot's exact HTTP contract and records every
request so the tests can assert the client emitted the right method/path/body.
The integration UI test runs in CI:

```text
.github/workflows/flutter-build.yml  →  "integration test" job
```
