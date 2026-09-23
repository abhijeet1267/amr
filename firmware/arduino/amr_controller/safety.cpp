// safety.cpp

#include "safety.h"

long          Safety::_timeoutMs = 1000;
unsigned long Safety::_lastCommandMs = 0;
bool          Safety::_armed = false;

void Safety::begin(long timeoutMs) {
  if (timeoutMs > 0) _timeoutMs = timeoutMs;
  _lastCommandMs = millis();
  _armed = false;  // not armed until the first valid command arrives
}

void Safety::setTimeout(long ms) {
  if (ms > 0 && ms < 60000) _timeoutMs = ms;
}

void Safety::noteCommand() {
  _lastCommandMs = millis();
  _armed = true;
}

bool Safety::shouldStop(unsigned long now) {
  if (!_armed) return false;
  // Unsigned subtraction wraps correctly across the millis() rollover.
  return (unsigned long)(now - _lastCommandMs) > (unsigned long)_timeoutMs;
}

bool Safety::armed() { return _armed; }
long Safety::timeoutMs() { return _timeoutMs; }
