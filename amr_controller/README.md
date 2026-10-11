# AMR Controller

A cross-platform Flutter client for the **AMR** (Autonomous Mobile Robot). It
connects over Wi-Fi/LAN to the robot's Python web server at
`http://<ROBOT_IP>:8080` and gives an operator a live directory, teleoperation
joystick, telemetry read-out and a guarded E-STOP from macOS, Windows, Android
and iOS — in a clean light control-room theme (white panels on a neutral
canvas, a single restrained engineering-blue accent, status colours that
always print their text).

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

Android release builds are signed with a local keystore:
`android/app/amr-release.keystore` (alias `amr`), configured through
`android/key.properties` — both gitignored, so a fresh clone falls back to the
debug key and still builds a runnable APK.

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

### Desktop build requirements

The platform runners are committed, so each target builds on its own OS:

| Target | Host | Needs |
| ------ | ---- | ----- |
| macOS | macOS | Full **Xcode** (`xcode-select --install` is *not* enough) + CocoaPods |
| Windows | Windows | **Visual Studio** with the "Desktop development with C++" workload |
| Linux | Linux | `clang cmake ninja-build pkg-config libgtk-3-dev` |
| iOS | macOS | Full Xcode + an Apple signing identity |

Flutter cannot cross-compile these: a macOS `.app` cannot be produced on
Windows or Linux, and a Windows `.exe` cannot be produced on macOS.

## First-run setup (every platform)

A fresh install does **not** drop the operator straight into the console. It
opens a four-step **setup wizard** — the same gate on Android, macOS, Windows,
Linux and the web:

1. **Welcome** — what the robot needs (power, same network, server running) and
   the safety rules, before anything is touched.
2. **Connect** — enter the robot's address and run a **connection test**. Every
   endpoint (`/health`, `/status`, `/telemetry`, `/map`, `/heatmap`,
   `/camera/status`, …) is probed **individually**, so a failure says *which*
   part of the robot is down and how to fix it, instead of one opaque "failed".
3. **Checks** — a **preflight** listing *fatal* conditions (no connection,
   Pi↔Arduino link down, E-STOP latched, obstacle too close, battery critical)
   and warnings (camera offline, high latency), then **live sensor readings**:
   front/left/right/rear, battery, mode, speed. "Next" is blocked while a fatal
   condition stands.
4. **Ready** — a summary, then into the Command Center.

A `-1` ultrasonic reading is shown as **clear** (no echo), never as `0 cm`, and
an absent sensor reads `n/a` — the same honesty rule the backend uses.

Re-run it any time from **Connection → "Run setup again"**.

## What it talks to

The client speaks the robot's real HTTP contract, verified against
`raspberry_pi/amr/web/server.py` — nothing is guessed:

| Call   | Endpoint              | Used for                                                                                                |
| ------ | --------------------- | ------------------------------------------------------------------------------------------------------- |
| `GET`  | `/applications/state` | the 25 interface cards                                                                                  |
| `GET`  | `/telemetry`          | battery / speed / ultrasonic / mode                                                                     |
| `GET`  | `/health`             | the ping / connection check                                                                             |
| `GET`  | `/status`             | raw robot snapshot                                                                                      |
| `GET`  | `/map`                | the Map screen: pose, route, trail, hazards, zones                                                       |
| `GET`  | `/heatmap`            | the Heat map screen: hazard + traffic density grids (C19)                                                |
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
  main.dart                        entry, theme, first-run gate, responsive shell
  models/app_state.dart            registry + telemetry data models
  models/robot_data.dart           map / camera / connectivity / heat-map models
  services/robot_api_service.dart  REST client (http package)
  providers/robot_provider.dart    state + polling + command path + preflight
  features/setup/setup_wizard.dart first-run setup, connection test, preflight
  features/heatmap/heatmap_screen.dart   hazard + traffic density (C19)
  screens/connection_screen.dart   host/port, ping, auto-reconnect
  screens/applications_hub_screen.dart
  screens/teleop_screen.dart       joystick + D-pad + telemetry + E-STOP
  widgets/app_card.dart            one hub card
  widgets/joystick_widget.dart     pointer-driven virtual joystick
  theme/theme.dart                 light industrial palette + status colours
```
