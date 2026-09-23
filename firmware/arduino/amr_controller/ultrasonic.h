// ultrasonic.h
//
// Four ultrasonic sensors: FRONT, LEFT, RIGHT, REAR (Phase 6).
//
// HARDWARE NOT WIRED YET — DO NOT treat the pin numbers below as real.
//   * ULTRASONIC_ENABLED is 0 by default, so the firmware compiles and runs
//     without sensors (readings are reported as -1 == invalid/no echo).
//   * Set the trig/echo pins from the actual wiring and flip the flag to 1
//     once documented. See docs/hardware.md.
//
// A reading is a distance in cm. A value of -1 means "no usable echo"
// (timeout / clear). Valid close readings drive the Layer-1 safety stop.

#pragma once

#include <Arduino.h>

#define ULTRASONIC_ENABLED   0
#define ULTRASONIC_TELEMETRY 0   // 1 = periodically send unsolicited SENSOR lines

#define US_MAX_RANGE_CM 400
#define US_PULSE_TIMEOUT_US 20000  // ~3.4 m echo wait

// ==== SENSOR PIN MAPPING — TODO: VERIFY HARDWARE PIN =======================
#define PIN_FRONT_TRIG 12
#define PIN_FRONT_ECHO 13
#define PIN_LEFT_TRIG   7
#define PIN_LEFT_ECHO   11
#define PIN_RIGHT_TRIG  2
#define PIN_RIGHT_ECHO  3
#define PIN_REAR_TRIG   4
#define PIN_REAR_ECHO   5

class Ultrasonic {
 public:
  static void begin();
  static void setThresholds(int front, int left, int right, int rear);
  static void setPollIntervalMs(long ms);

  static void readAll();
  static int  readFront();
  static int  readLeft();
  static int  readRight();
  static int  readRear();

  static bool pollDue(unsigned long now);
  // Layer-1: true when a VALID reading is closer than its stop threshold.
  static bool safetyStopNeeded();

  static String format();  // "SENSOR F=.. L=.. R=.. B=.."
};
