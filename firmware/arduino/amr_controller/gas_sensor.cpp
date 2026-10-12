// gas_sensor.cpp

#include "gas_sensor.h"

static int _lastRaw = -1;

void GasSensor::begin() {
#if GAS_ENABLED && (PIN_GAS_AO >= 0)
  // Analog pins need no pinMode; nothing to configure.
#endif
}

int GasSensor::readRaw() {
#if GAS_ENABLED && (PIN_GAS_AO >= 0)
  _lastRaw = analogRead(PIN_GAS_AO);
#else
  _lastRaw = -1;  // no pin assigned: "not measured", never a fake value
#endif
  return _lastRaw;
}

int GasSensor::lastRaw() { return _lastRaw; }