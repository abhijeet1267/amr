// motor_control.h
//
// Motor driver hardware abstraction layer (HAL).
//
// IMPORTANT (see docs/hardware.md and the hardware-assumption policy):
//   * The L298N ENA/ENB (PWM) wiring has NOT been verified yet.
//   * PWM speed control is therefore OFF by default (MOTOR_PWM_ENABLED 0),
//     which drives each side at fixed full speed based on the sign of the
//     commanded speed. This matches the already-tested F/B/L/R/S baseline.
//   * Do NOT change the pin numbers or enable PWM until you have confirmed
//     the actual L298N wiring (board photo of IN1-IN4 + ENA/ENB).
//
// The Pi never talks to pins directly; it sends MOVE/STOP over serial and this
// module is the only place that knows about motor pins.

#pragma once

#include <Arduino.h>

// ==== L298N PIN MAPPING — TODO: VERIFY HARDWARE PIN ========================
// Copy your known-good baseline pin numbers here. These placeholders are NOT
// asserted to be correct; set them from the wiring that already works.
#define PIN_IN1  5   // LEFT  group: forward
#define PIN_IN2  4   // LEFT  group: reverse
#define PIN_ENA  6   // LEFT  group: PWM (speed)      TODO: VERIFY
#define PIN_IN3  10  // RIGHT group: forward
#define PIN_IN4  9   // RIGHT group: reverse
#define PIN_ENB  8   // RIGHT group: PWM (speed)      TODO: VERIFY

// Set to 1 only AFTER verifying ENA/ENB. 0 = direction-only, full speed.
#define MOTOR_PWM_ENABLED   0
#define MOTOR_FULL_SPEED    255

class MotorControl {
 public:
  static void begin();          // configure pins, set safe (stopped) state
  static void stop();           // stop both sides (safe state)
  static void setLeft(int speed);   // -255 .. +255
  static void setRight(int speed);  // -255 .. +255
  static void setBoth(int left, int right);

  static bool anyMoving();
  static int  leftSpeed();
  static int  rightSpeed();
};
