// buzzer.cpp
//
// Timer-free buzzer: the pin is toggled by digitalWrite() from poll(), so no
// hardware timer (and therefore no Timer2 / D11 ENB conflict) is involved.
// See buzzer.h.

#include "buzzer.h"

int           Buzzer::_freqHz = 0;
bool          Buzzer::_pinState = false;
unsigned long Buzzer::_halfPeriodUs = 0;
unsigned long Buzzer::_lastToggleUs = 0;
unsigned long Buzzer::_stopAtMs = 0;

void Buzzer::begin() {
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);
}

void Buzzer::beep(int freqHz) {
  if (freqHz <= 0) { stop(); return; }
  if (freqHz > 20000) freqHz = 20000;   // keep the half-period sane
  _freqHz = freqHz;
  _halfPeriodUs = 1000000UL / (2UL * (unsigned long)freqHz);
  // Default to a bounded tone; beepFor() overrides with its own deadline.
  _stopAtMs = millis() + BUZZER_MAX_TONE_MS;
  _pinState = true;
  digitalWrite(PIN_BUZZER, HIGH);
  _lastToggleUs = micros();
}

void Buzzer::beepFor(int freqHz, unsigned long durationMs) {
  beep(freqHz);
  if (_freqHz > 0) _stopAtMs = millis() + durationMs;
}

void Buzzer::stop() {
  _freqHz = 0;
  _stopAtMs = 0;
  _pinState = false;
  digitalWrite(PIN_BUZZER, LOW);
}

bool Buzzer::isOn() { return _freqHz > 0; }

void Buzzer::poll(unsigned long now) {
  if (_freqHz <= 0) {
    // Defensive: an "active" buzzer sounds whenever the pin is HIGH, so an
    // idle buzzer must hold the pin LOW. Guarantees silence even if a command
    // left the pin high, and costs nothing when already low.
    if (_pinState) {
      _pinState = false;
      digitalWrite(PIN_BUZZER, LOW);
    }
    return;
  }
  if (_stopAtMs != 0 && now >= _stopAtMs) { stop(); return; }
  unsigned long us = micros();
  if ((unsigned long)(us - _lastToggleUs) >= _halfPeriodUs) {
    _pinState = !_pinState;
    digitalWrite(PIN_BUZZER, _pinState ? HIGH : LOW);
    _lastToggleUs = us;
  }
}