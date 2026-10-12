// dht11.h
//
// DHT11 temperature/humidity sensor (3-pin module) read on a single data line.
//
// PIN (from the final AMR pin chart, 2026-10-12): DATA = A1, used as a digital
// pin (A1 == digital pin 15 on the UNO). Power and ground go to 5V/GND.
//
// No third-party library: the DHT11 single-wire protocol is bit-banged here so
// the firmware keeps its "no external dependencies" property. The DHT11 updates
// at ~1 Hz, so the sensor is only read on an explicit `ENV` command, never in
// the main loop.
//
// HARDWARE NOT TESTED: no DHT11 has been read by this code. A failed or
// checksum-invalid read reports -1 for both values rather than a fake number.

#pragma once

#include <Arduino.h>

//: A1 used as a digital pin (analog pin 1 == digital pin 15).
#define PIN_DHT11_DATA A1

//: A DHT11 read is ~20 ms of bit timing; the sensor needs ~1 s between reads.
#define DHT11_READ_INTERVAL_MS 2000

class Dht11 {
 public:
  static void begin();

  // Read temperature (degC) and humidity (%RH). Returns true on a valid,
  // checksum-verified read; on any failure the outputs are set to -1.
  static bool read(int& temperatureC, int& humidityPct);

  static int  lastTemperatureC();  // -1 until a valid read
  static int  lastHumidityPct();   // -1 until a valid read
  static bool lastReadOk();

  // True when less than DHT11_READ_INTERVAL_MS has passed since the last read.
  static bool readingTooSoon(unsigned long now);

 private:
  static int  _temp;
  static int  _hum;
  static bool _ok;
  static unsigned long _lastReadMs;
};