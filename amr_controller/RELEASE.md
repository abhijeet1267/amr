# AMR Controller — release notes

Cross-platform operator client for the AMR robot. Connects over Wi-Fi/LAN to
the robot's Python web server at `http://<ROBOT_IP>:8080`.

## Artifacts

Artifacts are produced by `.github/workflows/flutter-build.yml` (CI) and, where
the host allows, locally. Naming is stable:

```text
AMR_Controller_Android.apk        Android (arm64-v8a, armeabi-v7a, x86_64)
AMR_Controller_Android.aab        Android App Bundle (Play Store)
AMR_Controller_macOS.zip          macOS .app
AMR_Controller_Windows.zip        Windows
AMR_Controller_Linux.tar.gz       Linux
AMR_Controller_Web.zip            Web (UI-only against the robot — see below)
AMR_Controller_iOS_unsigned.zip   iOS .app, unsigned
```

## Evidence levels

This project distinguishes what was actually verified:

- **COMPILED** — a build command produced the artifact.
- **RUNTIME VERIFIED** — the app was launched and its screens checked.
- **ROBOT COMMUNICATION VERIFIED** — the app talked to the mock/real robot.
- **PHYSICAL ROBOT VERIFIED** — commands reached a physical robot.

No level is claimed that was not actually performed.

## Web + robot (CORS)

The web build compiles and renders, but it **cannot** reach the robot
cross-origin: the robot's Python server sends no CORS headers and does not
answer `OPTIONS`. This is deliberate and will not be "fixed" with
`Access-Control-Allow-Origin: *` — granting that would let any website an
operator visits `POST /command` and move the robot, defeating the web panel's
single-gated-command guarantee. Use the native desktop/mobile builds to drive
the robot.

## Installing

- **Android**: enable "install unknown apps" and open `AMR_Controller_Android.apk`,
  or install the `.aab` via `bundletool` / Play Console.
- **macOS**: unzip, drag `AMR Controller.app` to Applications. First launch:
  right-click → Open (the app is not notarized).
- **Windows**: unzip and run `amr_controller.exe`.
- **Linux**: extract the tarball and run `./amr_controller`.
- **Web**: unzip and serve `build/web` with any static server; it renders the UI.

## Signing

macOS/iOS/Windows builds are **unsigned**. iOS `.app` is produced with
`--no-codesign` and cannot be installed on a device without a signing identity
and provisioning profile. No signing or notarization is claimed.