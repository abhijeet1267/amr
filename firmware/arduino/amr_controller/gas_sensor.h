// gas_sensor.h
//
// MQ-series analog gas sensor (e.g. MQ-2).
//
// PIN: NONE ASSIGNED. The final AMR pin chart (2026-10-12) uses all 20 usable
// UNO pins, so the MQ sensor's analog output has no home yet. Rather than
// invent a pin (which the project forbids), this module ships with the read
// path present but DISABLED:
//
//   * `GAS_ENABLED 0` and `PIN_GAS_AO -1` mean the firmware never touches a pin.
//   * A `GAS` command therefore reports `-1` (== "not measured") and the Pi
//     shows the value as UNAVAILABLE, never as a fake 0 ppm.
//
// To wire it later: free an analog pin (move the buzzer to an I2C expander, or
// drop it), set PIN_GAS_AO to that pin and GAS_ENABLED to 1, then re-flash.
//
// The raw value is the 10-bit ADC count (0..1023). It is NOT calibrated to ppm:
// an MQ sensor's ppm output is gas-specific and needs a reference calibration,
// so this firmware reports the raw ADC count and the Pi labels the unit `raw`.

#pragma once

#include <Arduino.h>

//: Set to 1 only after an analog pin is assigned and the sensor is wired.
#define GAS_ENABLED 0
//: The analog input pin, or -1 when unassigned (the shipped state).
#define PIN_GAS_AO (-1)

class GasSensor {
 public:
  static void begin();

  // Raw 10-bit ADC reading (0..1023), or -1 when disabled/unassigned.
  static int readRaw();

  static int lastRaw();
};