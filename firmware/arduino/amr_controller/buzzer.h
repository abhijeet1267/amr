// buzzer.h
//
// Two-wire buzzer on A0 (used as a digital output; A0 == digital pin 14).
// The other wire goes to GND.
//
// WHY NOT tone(): on the Arduino UNO, `tone()` uses Timer2, and Timer2 also
// drives pin D11 — which in this pin chart is ENB, the RIGHT motor's PWM. Using
// tone() would corrupt right-wheel speed control. This module therefore drives
// the buzzer by toggling the pin with digitalWrite() at a chosen rate, which
// uses no timer and cannot interfere with motor PWM.
//
// HARDWARE NOT TESTED: no buzzer has been driven by this code. A passive buzzer
// makes a tone at the toggled frequency; a 3-wire "active" buzzer module with
// its own oscillator will instead click on/off (it sounds at its fixed pitch
// and ignores the toggle rate). Both are harmless.

#pragma once

#include <Arduino.h>

//: A0 used as a digital output (analog pin 0 == digital pin 14).
#define PIN_BUZZER A0

class Buzzer {
 public:
  static void begin();

  // Start toggling at `freqHz` (0 or negative -> stop). Only meaningful for a
  // passive buzzer. Non-blocking: the toggle advances in poll().
  static void beep(int freqHz);

  // A fixed number of toggles then silence, so a beep can be one command with
  // no follow-up. `durationMs` is real time; the toggle continues in poll().
  static void beepFor(int freqHz, unsigned long durationMs);

  static void stop();
  static bool isOn();

  // Call from the main loop; toggles the pin on schedule. Never blocks.
  static void poll(unsigned long now);

 private:
  static int  _freqHz;
  static bool _pinState;
  static unsigned long _halfPeriodUs;
  static unsigned long _lastToggleUs;
  static unsigned long _stopAtMs;  // 0 == run until told to stop
};