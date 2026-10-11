#!/usr/bin/env bash
#
# health_check.sh — one-shot hardware/link health check for the AMR.
#
# Referenced by config/serial.yaml. Run it from the repository root (or anywhere;
# it locates itself) before trusting a hardware bring-up:
#
#   tools/health_check.sh
#   tools/health_check.sh --port /dev/amr_arduino --url http://localhost:8080
#   tools/health_check.sh --no-web          # serial + camera only
#
# It checks, independently:
#   1. serial port discovery   (stable by-id / udev symlink / ttyACM / ttyUSB)
#   2. the firmware link        (PING -> PONG, VERSION, STATUS, SENSOR)
#   3. the camera               (libcamera-still capture, or /dev/video*)
#   4. the running web stack    (GET /health)
#
# Exit code: 0 if nothing FAILED, 1 otherwise. SKIPs never fail the run.
#
# It is read-only: it opens the serial port, captures one camera frame to a temp
# file, and issues one HTTP GET. It never commands motion.

set -u

PORT=""
URL="http://localhost:8080"
DO_SERIAL=1
DO_CAMERA=1
DO_WEB=1
TIMEOUT=2

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --port)   PORT="${2:-}"; shift 2 ;;
    --url)    URL="${2:-}";  shift 2 ;;
    --no-serial) DO_SERIAL=0; shift ;;
    --no-camera) DO_CAMERA=0; shift ;;
    --no-web)    DO_WEB=0;    shift ;;
    -h|--help)   usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 2 ;;
  esac
done

PASS=0; FAIL=0; SKIP=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }
skip() { printf '  \033[33mSKIP\033[0m  %s\n' "$1"; SKIP=$((SKIP+1)); }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$1"; }

PY="$(command -v python3 || true)"

# --------------------------------------------------------------------------- #
# 1. Serial port discovery
# --------------------------------------------------------------------------- #
discover_port() {
  # Prefer an explicit override, then a stable by-id name, then the udev
  # symlink this repo documents, then the raw tty nodes.
  if [ -n "$PORT" ]; then echo "$PORT"; return; fi
  for p in /dev/serial/by-id/*Arduino* /dev/serial/by-id/*arduino* \
           /dev/amr_arduino; do
    [ -e "$p" ] && { echo "$p"; return; }
  done
  for p in /dev/ttyACM* /dev/ttyUSB*; do
    [ -e "$p" ] && { echo "$p"; return; }
  done
  echo ""
}

hdr "1. Serial port"
DISC="$(discover_port)"
if [ "$DO_SERIAL" -eq 0 ]; then
  skip "serial checks disabled (--no-serial)"
elif [ -n "$DISC" ]; then
  ok "found serial port: $DISC"
else
  bad "no serial port found (/dev/ttyACM* or /dev/ttyUSB*) — is the UNO plugged in?"
fi

# --------------------------------------------------------------------------- #
# 2. Firmware link
# --------------------------------------------------------------------------- #
hdr "2. Firmware link"
if [ "$DO_SERIAL" -eq 0 ]; then
  skip "serial checks disabled"
elif [ -z "$DISC" ]; then
  skip "no port to talk to"
elif [ -z "$PY" ]; then
  bad "python3 not found; cannot probe the serial link"
else
  "$PY" - "$DISC" <<'PY'
import sys
port = sys.argv[1]
try:
    import serial
except ImportError:
    print("  \033[31mFAIL\033[0m  pyserial not installed (pip install -e \".[serial]\")")
    sys.exit(1)
try:
    s = serial.Serial(port, 9600, timeout=1.5)
except Exception as exc:                       # noqa: BLE001
    print(f"  \033[31mFAIL\033[0m  cannot open {port}: {exc}")
    sys.exit(1)

import time
time.sleep(2)                                   # the UNO resets on open
s.reset_input_buffer()

def send(cmd):
    s.write((cmd + "\n").encode())
    return s.readline().decode(errors="replace").strip()

checks = [
    ("PING",    lambda r: r == "PONG",            "liveness (PONG)"),
    ("VERSION", lambda r: r.startswith("VERSION"),"protocol version"),
    ("STATUS",  lambda r: r.startswith("STATUS"), "motor/drive state"),
    ("SENSOR",  lambda r: r.startswith("SENSOR"), "ultrasonic report"),
]
failed = 0
for cmd, ok_fn, label in checks:
    got = send(cmd)
    if ok_fn(got):
        print(f"  \033[32mPASS\033[0m  {label:24} -> {got}")
    else:
        print(f"  \033[31mFAIL\033[0m  {label:24} -> {got!r}")
        failed += 1
s.close()
sys.exit(1 if failed else 0)
PY
  if [ $? -eq 0 ]; then PASS=$((PASS+4)); else FAIL=$((FAIL+1)); fi
fi

# --------------------------------------------------------------------------- #
# 3. Camera
# --------------------------------------------------------------------------- #
hdr "3. Camera"
if [ "$DO_CAMERA" -eq 0 ]; then
  skip "camera checks disabled (--no-camera)"
elif command -v libcamera-still >/dev/null 2>&1; then
  TMP="$(mktemp -t amr_frame.XXXXXX.jpg)"
  if libcamera-still -n -t 200 -o "$TMP" >/dev/null 2>&1 && [ -s "$TMP" ]; then
    ok "libcamera-still captured a frame ($(wc -c <"$TMP" | tr -d ' ') bytes)"
  else
    bad "libcamera-still present but captured nothing (ribbon / enablement?)"
  fi
  rm -f "$TMP"
elif ls /dev/video* >/dev/null 2>&1; then
  ok "V4L2 device present: $(ls /dev/video* | tr '\n' ' ') (set camera.device: v4l2)"
else
  bad "no camera: libcamera-still missing and no /dev/video* (see docs/setup_raspberry_pi.md)"
fi

# --------------------------------------------------------------------------- #
# 4. Web stack
# --------------------------------------------------------------------------- #
hdr "4. Web stack"
if [ "$DO_WEB" -eq 0 ]; then
  skip "web checks disabled (--no-web)"
elif command -v curl >/dev/null 2>&1; then
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$URL/health" || true)"
  if [ "$CODE" = "200" ]; then
    ok "GET $URL/health -> 200"
  elif [ -n "$CODE" ] && [ "$CODE" != "000" ]; then
    bad "GET $URL/health -> HTTP $CODE"
  else
    bad "no response from $URL — is 'python -m amr.main --web' running?"
  fi
else
  skip "curl not installed; cannot check the web stack"
fi

# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
hdr "Summary"
printf '  %d passed, %d failed, %d skipped\n' "$PASS" "$FAIL" "$SKIP"
if [ "$FAIL" -eq 0 ]; then
  printf '  \033[32mAll checks passed.\033[0m\n'
  exit 0
fi
printf '  \033[31m%d check(s) failed\033[0m — see docs/hardware.md §12 for common causes.\n' "$FAIL"
exit 1
