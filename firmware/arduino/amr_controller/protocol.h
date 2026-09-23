// protocol.h
//
// AMR Pi<->Arduino text protocol — firmware side.
// This implements the EXACT grammar tested by the Pi in
// raspberry_pi/amr/communication/protocol.py. Keep them in sync.
// Canonical spec: docs/serial_protocol.md
//
// Commands (Pi -> Arduino), newline terminated:
//   PING | STATUS | STOP | VERSION | SENSOR | WDT <ms>
//   MOVE L=<int> R=<int>        (-255 .. +255)
//   F | B | L | R | S           (legacy baseline, backward compatible)
//
// Responses (Arduino -> Pi):
//   PONG
//   ACK <verb> [args...]
//   ERR <code> [message...]     (code: PARSE | RANGE | UNKNOWN)
//   STATUS L=<int> R=<int> MODE=<str>
//   SENSOR F=<int> L=<int> R=<int> B=<int>
//   VERSION <semver>
//   WATCHDOG TRIGGERED          (unsolicited safety event)

#pragma once

#include <Arduino.h>

#define PROTOCOL_VERSION "1.0"
#define MIN_SPEED        (-255)
#define MAX_SPEED        (255)

// Error codes emitted in `ERR <code> ...`
#define ERR_PARSE   "PARSE"
#define ERR_RANGE   "RANGE"
#define ERR_UNKNOWN "UNKNOWN"

// Parsed form of one command line.
struct ProtocolResult {
  bool ok = false;
  String errorCode = "";          // set when ok == false

  // Which command was matched (at most one true).
  bool isPing = false;
  bool isVersion = false;
  bool isStop = false;
  bool isStatus = false;
  bool isSensor = false;
  bool isMove = false;
  bool isLegacy = false;
  bool isWdt = false;

  // Parsed payloads.
  int left = 0;
  int right = 0;
  char legacyChar = 0;
  int wdtMs = 0;
};

// True if a speed value is within the allowed range.
bool speedInRange(int value);

// Parse one command line (CR/LF already stripped) into a ProtocolResult.
// Never throws; unknown/malformed input sets ok=false with an errorCode.
ProtocolResult parseCommand(const String& line);
