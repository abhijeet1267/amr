# AMR Controller

A cross-platform Flutter client for the **AMR** (Autonomous Mobile Robot). It
connects over Wi-Fi/LAN to the robot's Python web server at
`http://<ROBOT_IP>:8080` and gives an operator a live directory, teleoperation
joystick, telemetry read-out and a guarded E-STOP from macOS, Windows, Android
and iOS — all in the same slate/cyan instrument palette as the robot's own
Command Center.

## Run it

This is a complete Flutter application — the platform runners are committed, so
a fresh clone needs only the SDK and a dependency install:

```bash
cd amr_controller
flutter pub get
flutter run
```

To produce installable builds:

```bash
flutter build apk --release      # Android (needs the Android SDK)
flutter build ios                # iOS (needs Xcode on macOS)
flutter build macos              # macOS app
flutter build windows            # Windows (from a Windows host)
```

The app is **verified to compile clean**: `flutter analyze` reports "No issues
found" and `flutter test` passes.

Then point it at a running robot:

```bash
cd raspberry_pi
source .venv/bin/activate
python -m amr.main --mock --web     # prints http://localhost:8080
```

…and enter that address (or the Pi's LAN IP) on the **Connection** screen.

> **Web build note.** `flutter build web` compiles, but the robot's Python
> server intentionally sends **no CORS headers** and does not answer
> `OPTIONS`. That means a browser-hosted build cannot reach it cross-origin —
> and deliberately so: granting `Access-Control-Allow-Origin` to arbitrary
> origins would let any website an operator visits `POST /command` and move
> the robot, bypassing the web panel's single-gated-command guarantee. Use the
> **native** desktop/mobile builds (which use the OS HTTP stack, not a
> browser's same-origin policy) to actually drive the robot.

## What it talks to

The client speaks the robot's real HTTP contract, verified against
`raspberry_pi/amr/web/server.py` — nothing is guessed:

| Call   | Endpoint              | Used for                                                                                                |
| ------ | --------------------- | ------------------------------------------------------------------------------------------------------- |
| `GET`  | `/applications/state` | the 24 interface cards                                                                                  |
| `GET`  | `/telemetry`          | battery / speed / ultrasonic / mode                                                                     |
| `GET`  | `/health`             | the ping / connection check                                                                             |
| `GET`  | `/status`             | raw robot snapshot                                                                                      |
| `POST` | `/command`            | `forward` / `backward` / `turn_left` / `turn_right` / `rotate_left` / `rotate_right` / `stop` / `estop` |

Two honesty notes carried straight from the robot's own docs:

- **No battery sensor and no temperature sensor exist yet.** Those tiles read
  `no sensor`, never a fabricated number — `null` is "not measured", `0` is
  "measured as zero", and the app never conflates them.
- Every motion command is gated by the robot's `RobotManager`/safety layer. The
  app's `POST /command` is the _same_ single path as the web control panel; a
  safety veto returns HTTP 400 and the robot does not move.

## Layout

- **Desktop (macOS/Windows):** `NavigationRail` split view — Applications,
  Teleop, Connection.
- **Mobile (Android/iOS):** bottom `NavigationBar` with the same destinations.
- **Teleop** has an **Idle / Manual / Autonomous** selector above the stick,
  mirroring the web panel: the robot boots in `IDLE` and refuses motion until
  the operator selects `MANUAL`, and after an E-STOP its state machine only
  accepts a reset back to `IDLE` — the selector and its feedback make that
  two-step release visible.
- The **E-STOP** is reachable from the Teleop screen at all times (long-press
  to arm, release to fire) and every motion command is confirmed with a
  readable result.

## Structure

```
lib/
  main.dart                        entry, theme, responsive shell
  models/app_state.dart            registry + telemetry data models
  services/robot_api_service.dart  REST client (http package)
  providers/robot_provider.dart    state + polling + command path
  screens/connection_screen.dart   host/port, ping, auto-reconnect
  screens/applications_hub_screen.dart
  screens/teleop_screen.dart       joystick + D-pad + telemetry + E-STOP
  widgets/app_card.dart            one hub card
  widgets/joystick_widget.dart     pointer-driven virtual joystick
  theme/theme.dart                 slate/cyan palette + status colours
```
