#!/usr/bin/env bash
# ============================================================================
# AMR — safe Pi bring-up for the APP ONLY (no Arduino, no motors, no sensors).
#
# This stack needs exactly ONE third-party package: PyYAML. Raspberry Pi OS
# already ships it (`python3-yaml`), so in practice this script installs
# nothing — it just finds a working Python, checks the camera, and starts the
# console in MOCK mode.
#
# What it does NOT do (on purpose):
#   * no sudo, no apt, no systemd, no boot changes
#   * no system-wide pip installs (no --break-system-packages)
#   * no GPIO, no serial, no motor or sensor access
#   * writes only inside $REPO (and only if a venv is needed)
#
# Mock mode runs the robot entirely in-process: it cannot command hardware,
# because none is connected. Safe to Ctrl-C; safe to re-run (idempotent).
#
# Usage:
#   ./pi_quickstart.sh              # check, then run the console
#   ./pi_quickstart.sh --setup      # check only, do not run
#   PORT=8081 ./pi_quickstart.sh    # another port
# ============================================================================
set -uo pipefail

REPO="${AMR_REPO:-$HOME/amr}"
PKG="$REPO/raspberry_pi"
PORT="${PORT:-8080}"
SETUP_ONLY=0
[ "${1:-}" = "--setup" ] && SETUP_ONLY=1

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()  { printf '   \033[32mOK\033[0m   %s\n' "$*"; }
warn(){ printf '   \033[33mWARN\033[0m %s\n' "$*"; }
die() { printf '   \033[31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }

printf '\033[1mAMR Pi bring-up — app + camera only, no robot hardware needed\033[0m\n'
printf 'repo: %s\nport: %s\n' "$REPO" "$PORT"

# ---------------------------------------------------------------- 1. layout --
say "1/4  Checking the code is in place"
[ -d "$PKG/amr" ] || die "no $PKG/amr — copy raspberry_pi/ and config/ into $REPO first (docs/DEPLOY.md §A2)"
[ -d "$REPO/config" ] || die "no $REPO/config — the stack needs it beside raspberry_pi/"
ok "code found:   $PKG"
ok "config found: $REPO/config"

# ---------------------------------------------------------------- 2. python --
say "2/4  Finding a Python that can run the stack (needs PyYAML only)"
PY=""
if command -v python3 >/dev/null 2>&1 \
   && python3 -c 'import yaml' >/dev/null 2>&1; then
  PY="$(command -v python3)"
  ok "system python3 has PyYAML — nothing to install"
  ok "using $PY ($(python3 --version 2>&1))"
else
  warn "system python3 cannot import yaml; falling back to a private venv"
  command -v python3 >/dev/null 2>&1 || die "python3 not found at all"
  if [ ! -x "$PKG/.venv/bin/python" ]; then
    python3 -m venv "$PKG/.venv" || die "could not create a venv"
    ok "created $PKG/.venv (inside the repo, nothing global)"
  else
    ok "re-using $PKG/.venv"
  fi
  "$PKG/.venv/bin/python" -m pip install --quiet --upgrade pip || true
  # [serial] adds pyserial, which is only needed once the Arduino is attached.
  "$PKG/.venv/bin/python" -m pip install --quiet -e "$PKG[serial]" \
    || die "pip install failed"
  PY="$PKG/.venv/bin/python"
  ok "installed the stack into the venv"
fi
"$PY" -c 'import yaml; print("   OK   PyYAML", yaml.__version__)' || die "PyYAML unusable"

# ---------------------------------------------------------------- 3. camera --
say "3/4  Camera check (independent of the robot)"
# Raspberry Pi renamed its camera CLI: `libcamera-still` (package
# `libcamera-apps`) is now `rpicam-still` (package `rpicam-apps`). Current
# Raspberry Pi OS ships the new name, older images the old one.
CAM=""
for c in rpicam-still libcamera-still; do
  if command -v "$c" >/dev/null 2>&1; then CAM="$c"; break; fi
done
if [ -n "$CAM" ]; then
  ok "$CAM present"
  if "$CAM" -n -t 500 -o /tmp/amr-cam-test.jpg >/dev/null 2>&1 \
     && [ -s /tmp/amr-cam-test.jpg ]; then
    ok "captured a test frame: /tmp/amr-cam-test.jpg ($(wc -c </tmp/amr-cam-test.jpg) bytes)"
    ok "the camera works — the app's Camera screen will show frames"
  else
    warn "$CAM exists but the capture failed."
    warn "usual causes: ribbon not seated, latch open, or the camera not enabled"
  fi
else
  warn "no camera CLI found (looked for rpicam-still and libcamera-still)."
  warn "to add it (the one step that needs sudo — run it yourself if you want it):"
  printf '        sudo apt update && sudo apt install -y rpicam-apps\n'
  warn "on older Raspberry Pi OS the package is 'libcamera-apps' instead"
  warn "the app works fine without a camera; the Camera screen stays offline"
fi
# The preferred path is the Python stack, which needs no CLI at all.
if python3 -c 'import picamera2' >/dev/null 2>&1; then
  ok "picamera2 is installed — the app will use it first"
else
  warn "picamera2 not installed (optional, but it is the preferred path):"
  printf '        sudo apt install -y python3-picamera2\n'
fi

# ---------------------------------------------------------------- 4. run -----
if [ "$SETUP_ONLY" = "1" ]; then
  say "Setup complete — not starting the console (--setup)"
  exit 0
fi

say "4/4  Starting the control stack in MOCK mode"
# `hostname -I` is Linux-only; never let its absence abort the script.
IP=""
if command -v hostname >/dev/null 2>&1; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi
printf '\n   Console : http://localhost:%s/command-center\n' "$PORT"
[ -n "${IP:-}" ] && printf '   LAN     : http://%s:%s/command-center\n' "$IP" "$PORT"
printf '   App     : enter %s and port %s in the AMR app\n' "${IP:-<pi-ip>}" "$PORT"
printf '\n   MOCK MODE — no hardware is touched. Ctrl-C to stop.\n\n'
cd "$PKG" || die "cannot cd into $PKG"
exec "$PY" -m amr.main --mock --web --port "$PORT"
