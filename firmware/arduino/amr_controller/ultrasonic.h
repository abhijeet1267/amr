// ultrasonic.h
//
// Four ultrasonic sensors: FRONT, LEFT, RIGHT, REAR (Phase 6).
//
// PIN MAP (applied from the final AMR pin chart, 2026-10-12):
//   FRONT  trig=D2  echo=D3
//   LEFT   trig=D4  echo=D5
//   RIGHT  trig=D6  echo=D7
//   REAR   trig=D8  echo=D9
// This is the chart that frees D4/D5 from the left motor, so no sensor shares a
// pin with a motor channel any more.
//
// A reading is a distance in cm. A value of -1 means "no usable echo"
// (timeout / clear). Valid close readings drive the Layer-1 safety stop.

#pragma once

#include <Arduino.h>

#define ULTRASONIC_ENABLED   1
#define ULTRASONIC_TELEMETRY 0   // 1 = periodically send unsolicited SENSOR lines

#define US_MAX_RANGE_CM 400
#define US_PULSE_TIMEOUT_US 20000  // ~3.4 m echo wait

// ==== SENSOR PIN MAPPING ===================================================
#define PIN_FRONT_TRIG  2
#define PIN_FRONT_ECHO  3
#define PIN_LEFT_TRIG   4
#define PIN_LEFT_ECHO   5
#define PIN_RIGHT_TRIG  6
#define PIN_RIGHT_ECHO  7
#define PIN_REAR_TRIG   8
#define PIN_REAR_ECHO   9

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