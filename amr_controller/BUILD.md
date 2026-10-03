# Building AMR Controller

The complete Flutter source for the AMR Controller lives in `amr_controller/`.
The platform runners are committed; you only need the Flutter SDK and each
platform's own toolchain.

## Prerequisites

- **Flutter** stable (`>= 3.27.0`; the project was generated with 3.47.6)
- **Android**: Android SDK (platform 36 + build-tools 36) and a JDK 17.
  Set `ANDROID_HOME` and `JAVA_HOME`.
- **macOS / iOS**: a full Xcode install + CocoaPods.
- **Windows**: Visual Studio with the C++ desktop workload.
- **Linux**: `clang`, `cmake`, `ninja-build`, `pkg-config`, `libgtk-3-dev`.

## Build commands

```bash
cd amr_controller
flutter pub get

flutter build apk --release          # Android APK
flutter build appbundle --release     # Android App Bundle (.aab)
flutter build macos --release         # macOS .app
flutter build windows --release        # Windows
flutter build linux --release          # Linux
flutter build web --release            # Web
flutter build ios --release --no-codesign   # iOS .app (unsigned)
```

## Artifact locations

| Target | Output path |
|--------|-------------|
| Android APK | `build/app/outputs/flutter-apk/app-release.apk` |
| Android AAB | `build/app/outputs/bundle/release/app-release.aab` |
| macOS | `build/macos/Build/Products/Release/AMR Controller.app` |
| Windows | `build/windows/x64/runner/Release/` |
| Linux | `build/linux/x64/release/bundle/` |
| Web | `build/web/` |

## Automated CI

`.github/workflows/flutter-build.yml` builds every target that cannot be built
on a single host — Android, Windows, macOS, Linux, Web, and unsigned iOS — and
uploads each as a downloadable artifact. It fails on a real build error; there
is no swallowed step.

## Configuration notes (why they exist)

- **Android `INTERNET` + cleartext** (`AndroidManifest.xml`): the app talks to
  the robot's plain-`http://` server on the LAN. Cleartext is allowed to make
  teleop/telemetry reachable; it does **not** weaken the gated command path —
  every motion verb still routes through the robot's `RobotManager`/safety
  layer.
- **macOS/iOS network entitlement + ATS** (`*.entitlements`, `Info.plist`):
  same reason — outgoing network access to a cleartext LAN server. This is
  *not* `Access-Control-Allow-Origin: *`; the web build remains UI-only
  against the robot, untouched for browser security.