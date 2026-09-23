// amr_controller.ino
//
// AMR low-level controller (Arduino UNO).
//
// Responsibilities:
//   * Speak the structured serial protocol to the Raspberry Pi (see protocol.h).
//   * Keep the already-working legacy F/B/L/R/S commands working (backward compat).
//   * Drive the L298N motor channels via the MotorControl HAL.
//   * Enforce the communication watchdog (Safety) -> STOP when the Pi goes silent.
//   * Poll the four ultrasonic sensors and enforce the Layer-1 hardware stop.
//
// SAFETY: the robot powers on in a stopped state and NEVER auto-drives. It only
// moves in response to explicit MOVE/legacy commands, and always stops on
// watchdog timeout or a close obstacle.
//
// STATUS: IMPLEMENTED. Not compile-tested on this machine (no AVR toolchain);
// requires flashing to the UNO and hardware testing. See docs/setup_arduino.md.

#include <Arduino.h>
#include "protocol.h"
#include "motor_control.h"
#include "safety.h"
#include "ultrasonic.h"

// Watchdog default (ms) — mirrors config/safety.yaml. Changeable at runtime
// with the `WDT <ms>` command.
#define DEFAULT_WATCHDOG_MS 1000

static bool watchdogTripped = false;

// Read one newline-terminated command line from Serial.
static String readLine() {
  String line;
  unsigned long lastActivity = millis();
  while (true) {
    if (Serial.available()) {
      char c = (char)Serial.read();
      if (c == '\n') { line.trim(); return line; }
      if (c != '\r') line.concat(c);
      lastActivity = millis();
    } else if ((unsigned long)(millis() - lastActivity) > 20) {
      line.trim();
      return line;  // may be empty
    }
  }
}

// Low-level firmware drive state reported in STATUS.
static const char* driveMode() {
  if (watchdogTripped) return "WATCHDOG";
  if (MotorControl.anyMoving()) return "RUNNING";
  return "STOPPED";
}

static void handleCommand(const String& line) {
  ProtocolResult r = parseCommand(line);

  if (r.ok) {
    watchdogTripped = false;  // link is alive
    Safety::noteCommand();
  }

  if (r.isPing) {
    Serial.println(F("PONG"));
  } else if (r.isVersion) {
    Serial.print(F("VERSION "));
    Serial.println(PROTOCOL_VERSION);
  } else if (r.isStop) {
    MotorControl.stop();
    Serial.println(F("ACK STOP"));
  } else if (r.isStatus) {
    Serial.print(F("STATUS L="));
    Serial.print(MotorControl.leftSpeed());
    Serial.print(F(" R="));
    Serial.print(MotorControl.rightSpeed());
    Serial.print(F(" MODE="));
    Serial.println(driveMode());
  } else if (r.isSensor) {
    Ultrasonic.readAll();
    Serial.println(Ultrasonic.format());
  } else if (r.isMove) {
    MotorControl.setBoth(r.left, r.right);
    Serial.print(F("ACK MOVE L="));
    Serial.print(r.left);
    Serial.print(F(" R="));
    Serial.println(r.right);
  } else if (r.isLegacy) {
    // Legacy baseline presets (keep the tested F/B/L/R/S behaviour).
    int l = 0, rr = 0;
    switch (r.legacyChar) {
      case 'F': l = 1;  rr = 1;  break;
      case 'B': l = -1; rr = -1; break;
      case 'L': l = -1; rr = 1;  break;
      case 'R': l = 1;  rr = -1; break;
      case 'S': l = 0;  rr = 0;  break;
    }
    MotorControl.setBoth(l, rr);
    Serial.print(F("ACK "));
    Serial.println(r.legacyChar);
  } else if (r.isWdt) {
    Safety::setTimeout(r.wdtMs);
    Serial.print(F("ACK WDT "));
    Serial.println(r.wdtMs);
  } else {
    Serial.print(F("ERR "));
    Serial.print(r.errorCode);
    Serial.println(F(" invalid"));
  }
}

void setup() {
  Serial.begin(9600);
  MotorControl.begin();          // safe (stopped) state
  Ultrasonic.begin();
  // NOTE: thresholds normally come from config/safety.yaml on the Pi. The
  // firmware uses these defaults until a runtime config command is added.
  Ultrasonic::setThresholds(20, 15, 15, 20);
  Safety::begin(DEFAULT_WATCHDOG_MS);
  MotorControl.stop();           // explicit safe state at boot
  Serial.println(F("AMR FW READY v" PROTOCOL_VERSION));
}

void loop() {
  unsigned long now = millis();

  // 1) Handle incoming command (a valid command resets the watchdog).
  if (Serial.available()) {
    String line = readLine();
    if (line.length() > 0) handleCommand(line);
  }

  // 2) Communication watchdog: stop if the Pi went silent.
  if (Safety::shouldStop(now)) {
    if (!watchdogTripped) {
      MotorControl.stop();
      watchdogTripped = true;
      Serial.println(F("WATCHDOG TRIGGERED"));
    }
  }

  // 3) Sensors: poll, optional telemetry, Layer-1 hardware stop.
  if (Ultrasonic::pollDue(now)) {
    Ultrasonic.readAll();
    if (ULTRASONIC_TELEMETRY) Serial.println(Ultrasonic.format());
    if (Ultrasonic::safetyStopNeeded()) {
      MotorControl.stop();
    }
  }

  delay(1);  // small yield
}
