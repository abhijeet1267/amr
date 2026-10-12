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
//   ENV                         DHT11 temperature/humidity reading
//   GAS                         MQ gas sensor raw reading
//   LCD <line0>|<line1>         set the 16x2 LCD (up to 16 chars each)
//   BUZZ <freqHz> [<ms>]        buzzer tone (freq 0 = stop); optional duration
//
// Responses (Arduino -> Pi):
//   PONG
//   ACK <verb> [args...]
//   ERR <code> [message...]     (code: PARSE | RANGE | UNKNOWN)
//   STATUS L=<int> R=<int> MODE=<str>
//   SENSOR F=<int> L=<int> R=<int> B=<int>
//   ENV T=<int> H=<int>         (degC / %RH; -1 == not measured / invalid)
//   GAS RAW=<int>               (0..1023 ADC count; -1 == no pin assigned)
//   VERSION <semver>
//   WATCHDOG TRIGGERED          (unsolicited safety event)

#pragma once

#include <Arduino.h>

#define PROTOCOL_VERSION "1.1"
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
  bool isEnv = false;
  bool isGas = false;
  bool isLcd = false;
  bool isBuzz = false;

  // Parsed payloads.
  int left = 0;
  int right = 0;
  char legacyChar = 0;
  int wdtMs = 0;
  String lcdLine0 = "";           // LCD text (case preserved)
  String lcdLine1 = "";
  int buzzFreqHz = 0;             // 0 == stop
  long buzzMs = 0;                // 0 == no auto-stop
};

// True if a speed value is within the allowed range.
bool speedInRange(int value);

// Parse one command line (CR/LF already stripped) into a ProtocolResult.
// Never throws; unknown/malformed input sets ok=false with an errorCode.
ProtocolResult parseCommand(const String& line);