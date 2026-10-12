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
//   * Read the DHT11 (temperature/humidity) and MQ gas sensor, drive the I2C
//     LCD and the buzzer.
//
// SAFETY: the robot powers on in a stopped state and NEVER auto-drives. It only
// moves in response to explicit MOVE/legacy commands, and always stops on
// watchdog timeout or a close obstacle. The environmental sensors (DHT11, gas),
// the LCD and the buzzer have NO path to the motors — they neither move the
// robot nor gate its motion.
//
// PIN MAP: applied from the final AMR pin chart (2026-10-12). See motor_control.h,
// ultrasonic.h, dht11.h, gas_sensor.h, lcd_i2c.h, buzzer.h.
//
// STATUS: IMPLEMENTED. Not compile-tested on this machine (no AVR toolchain);
// requires flashing to the UNO and hardware testing. See docs/setup_arduino.md.

#include <Arduino.h>
#include "protocol.h"
#include "motor_control.h"
#include "safety.h"
#include "ultrasonic.h"
#include "dht11.h"
#include "gas_sensor.h"
#include "lcd_i2c.h"
#include "buzzer.h"

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

// Build the single-line status shown on the LCD (best-effort, read-only).
static void refreshLcd() {
  if (!LcdI2c::present()) return;
  char line0[17];
  char line1[17];
  if (watchdogTripped) {
    snprintf(line0, sizeof(line0), "SAFETY STOP");
  } else {
    snprintf(line0, sizeof(line0), "MODE %s", driveMode());
  }
  snprintf(line1, sizeof(line1), "T%d H%d", Dht11::lastTemperatureC(),
           Dht11::lastHumidityPct());
  LcdI2c::showLines(String(line0), String(line1));
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
  } else if (r.isEnv) {
    int t = -1, h = -1;
    Dht11::read(t, h);
    Serial.print(F("ENV T="));
    Serial.print(t);
    Serial.print(F(" H="));
    Serial.println(h);
    refreshLcd();
  } else if (r.isGas) {
    Serial.print(F("GAS RAW="));
    Serial.println(GasSensor::readRaw());
  } else if (r.isLcd) {
    LcdI2c::showLines(r.lcdLine0, r.lcdLine1);
    Serial.println(F("ACK LCD"));
  } else if (r.isBuzz) {
    if (r.buzzMs > 0) {
      Buzzer::beepFor(r.buzzFreqHz, (unsigned long)r.buzzMs);
    } else {
      Buzzer::beep(r.buzzFreqHz);
    }
    Serial.print(F("ACK BUZZ "));
    Serial.println(r.buzzFreqHz);
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

  Dht11::begin();
  GasSensor::begin();
  LcdI2c::begin();
  Buzzer::begin();

  Serial.println(F("AMR FW READY v" PROTOCOL_VERSION));
  if (LcdI2c::present()) {
    LcdI2c::showLines("AMR READY", "v" PROTOCOL_VERSION);
  }
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
      Buzzer::beepFor(2000, 500);   // audible alert on safety stop
      watchdogTripped = true;
      Serial.println(F("WATCHDOG TRIGGERED"));
      refreshLcd();
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

  // 4) Buzzer: advance the toggle schedule (no timer, no D11 conflict).
  Buzzer::poll(now);

  delay(1);  // small yield
}