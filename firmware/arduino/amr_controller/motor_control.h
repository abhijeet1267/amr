// motor_control.h
//
// Motor driver hardware abstraction layer (HAL).
//
// PIN MAP (applied from the final AMR pin chart, 2026-10-12):
//   IN1=D12  IN2=D13  ENA=D10 (PWM)
//   IN3=A3   IN4=A2   ENB=D11 (PWM)
// This clears the two faults docs/COMPONENTS.md flagged:
//   * ENB moved off D8 (not PWM-capable) onto D11, which IS PWM-capable.
//   * the rear ultrasonic no longer collides with the left motor (D4/D5).
//
// PWM is enabled here because ENA/ENB now sit on real PWM pins. If you have
// NOT removed the L298N ENA/ENB jumper caps, set MOTOR_PWM_ENABLED back to 0 —
// with the jumpers fitted the driver ignores the PWM pin and the wheels run at
// full speed regardless.
//
// The Pi never talks to pins directly; it sends MOVE/STOP over serial and this
// module is the only place that knows about motor pins.

#pragma once

#include <Arduino.h>

// ==== L298N PIN MAPPING ====================================================
#define PIN_IN1  12  // LEFT  group: forward
#define PIN_IN2  13  // LEFT  group: reverse   (D13 also drives the onboard LED)
#define PIN_ENA  10  // LEFT  group: PWM (speed)  — D10 is PWM-capable
#define PIN_IN3  A3  // RIGHT group: forward   (used as a digital output)
#define PIN_IN4  A2  // RIGHT group: reverse   (used as a digital output)
#define PIN_ENB  11  // RIGHT group: PWM (speed) — D11 is PWM-capable

// Set to 0 for direction-only, full speed (the pre-chart baseline behaviour).
#define MOTOR_PWM_ENABLED   1
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