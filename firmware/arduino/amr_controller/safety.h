// safety.h
//
// Arduino-side communication watchdog (Phase 2).
//
// If the Raspberry Pi stops sending valid commands for `timeoutMs`, the
// watchdog trips and the caller stops the motors. This guarantees the robot
// never keeps driving indefinitely because the Pi crashed or the cable was
// pulled. The default (1000 ms) mirrors config/safety.yaml; it can also be
// changed at runtime with the `WDT <ms>` command.

#pragma once

#include <Arduino.h>

class Safety {
 public:
  static void begin(long timeoutMs);
  static void setTimeout(long ms);
  static void noteCommand();                 // call on every VALID command
  static bool shouldStop(unsigned long now); // true if the Pi went silent
  static bool armed();
  static long timeoutMs();

 private:
  static long         _timeoutMs;
  static unsigned long _lastCommandMs;
  static bool         _armed;
};
