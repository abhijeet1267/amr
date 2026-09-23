// protocol.cpp
//
// Firmware implementation of the AMR serial protocol parser.
// Mirrors raspberry_pi/amr/communication/protocol.py.

#include "protocol.h"

bool speedInRange(int value) {
  return value >= MIN_SPEED && value <= MAX_SPEED;
}

// Parse a signed integer token. Returns 1 on success, 0 on failure.
static int parseSignedInt(const String& s, int& out) {
  if (s.length() == 0) return 0;
  int i = 0;
  bool negative = false;
  if (s.charAt(0) == '-') { negative = true; i = 1; }
  long value = 0;
  bool anyDigit = false;
  for (; i < (int)s.length(); i++) {
    char c = s.charAt(i);
    if (c < '0' || c > '9') return 0;  // invalid character -> parse fail
    value = value * 10 + (c - '0');
    if (value > 100000L) return 0;     // absurd, treat as invalid
    anyDigit = true;
  }
  if (!anyDigit) return 0;
  out = negative ? (int)(-value) : (int)value;
  return 1;
}

ProtocolResult parseCommand(const String& line) {
  ProtocolResult r;

  String s = line;
  s.trim();
  if (s.length() == 0) {
    return r;  // empty -> not ok, no action
  }

  String up = s;
  up.toUpperCase();

  if (up == "PING") { r.ok = true; r.isPing = true; return r; }
  if (up == "VERSION") { r.ok = true; r.isVersion = true; return r; }
  if (up == "STOP") { r.ok = true; r.isStop = true; return r; }
  if (up == "STATUS") { r.ok = true; r.isStatus = true; return r; }
  if (up == "SENSOR") { r.ok = true; r.isSensor = true; return r; }

  // Legacy single-character baseline commands (F/B/L/R/S).
  if (up.length() == 1) {
    char c = up.charAt(0);
    if (c == 'F' || c == 'B' || c == 'L' || c == 'R' || c == 'S') {
      r.ok = true; r.isLegacy = true; r.legacyChar = c; return r;
    }
  }

  // WDT <ms> : set the communication watchdog timeout at runtime.
  if (up.startsWith("WDT")) {
    String rest = s.substring(3);
    rest.trim();
    int ms = 0;
    if (parseSignedInt(rest, ms) == 1 && ms > 0 && ms < 60000) {
      r.ok = true; r.isWdt = true; r.wdtMs = ms; return r;
    }
    r.ok = false; r.errorCode = ERR_PARSE; return r;
  }

  // MOVE L=<int> R=<int>
  if (up.startsWith("MOVE")) {
    int li = up.indexOf("L=");
    int ri = up.indexOf("R=");
    if (li < 0 || ri < 0) { r.ok = false; r.errorCode = ERR_PARSE; return r; }

    String leftTok = up.substring(li + 2, ri);
    leftTok.trim();
    String rightTok = up.substring(ri + 2);
    rightTok.trim();

    int lv = 0, rv = 0;
    if (parseSignedInt(leftTok, lv) != 1 || parseSignedInt(rightTok, rv) != 1) {
      r.ok = false; r.errorCode = ERR_PARSE; return r;
    }
    if (!speedInRange(lv) || !speedInRange(rv)) {
      r.ok = false; r.errorCode = ERR_RANGE; return r;
    }
    r.ok = true; r.isMove = true; r.left = lv; r.right = rv; return r;
  }

  // Anything else is unknown.
  r.ok = false;
  r.errorCode = ERR_UNKNOWN;
  return r;
}
