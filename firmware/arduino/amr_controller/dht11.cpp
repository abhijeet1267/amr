// dht11.cpp
//
// Bit-banged DHT11 reader. Standard single-wire protocol:
//   host pulls the line low >=18 ms, releases, then the sensor answers with
//   40 bits (16 humidity, 16 temperature, 8 checksum), MSB first.
//
// Timing is tight and this has NOT been run on hardware — see dht11.h.

#include "dht11.h"

int           Dht11::_temp = -1;
int           Dht11::_hum = -1;
bool          Dht11::_ok = false;
unsigned long Dht11::_lastReadMs = 0;

void Dht11::begin() {
  pinMode(PIN_DHT11_DATA, INPUT_PULLUP);
}

bool Dht11::readingTooSoon(unsigned long now) {
  return (unsigned long)(now - _lastReadMs) < DHT11_READ_INTERVAL_MS;
}

// Wait for the line to reach `level`, giving up after `timeoutUs`.
static bool waitFor(int level, unsigned long timeoutUs) {
  unsigned long start = micros();
  while (digitalRead(PIN_DHT11_DATA) != level) {
    if ((unsigned long)(micros() - start) > timeoutUs) return false;
  }
  return true;
}

bool Dht11::read(int& temperatureC, int& humidityPct) {
  uint8_t data[5] = {0, 0, 0, 0, 0};

  // Start signal: hold low >=18 ms, then release and wait for the response.
  pinMode(PIN_DHT11_DATA, OUTPUT);
  digitalWrite(PIN_DHT11_DATA, LOW);
  delay(20);
  digitalWrite(PIN_DHT11_DATA, HIGH);
  delayMicroseconds(30);
  pinMode(PIN_DHT11_DATA, INPUT_PULLUP);

  // Sensor response: ~80 us low, then ~80 us high.
  if (!waitFor(LOW, 200) || !waitFor(HIGH, 200) || !waitFor(LOW, 200)) {
    _ok = false; _temp = -1; _hum = -1; _lastReadMs = millis();
    temperatureC = -1; humidityPct = -1;
    return false;
  }

  // 40 data bits: each is ~50 us low, then a high whose length is the value.
  for (int i = 0; i < 40; i++) {
    if (!waitFor(HIGH, 200)) {
      _ok = false; _temp = -1; _hum = -1; _lastReadMs = millis();
      temperatureC = -1; humidityPct = -1;
      return false;
    }
    unsigned long highStart = micros();
    if (!waitFor(LOW, 200)) {
      _ok = false; _temp = -1; _hum = -1; _lastReadMs = millis();
      temperatureC = -1; humidityPct = -1;
      return false;
    }
    unsigned long highUs = (unsigned long)(micros() - highStart);
    data[i / 8] <<= 1;
    if (highUs > 40) data[i / 8] |= 1;  // ~70 us == 1, ~26 us == 0
  }

  uint8_t checksum = (uint8_t)(data[0] + data[1] + data[2] + data[3]);
  if (checksum != data[4]) {
    _ok = false; _temp = -1; _hum = -1; _lastReadMs = millis();
    temperatureC = -1; humidityPct = -1;
    return false;
  }

  _hum = data[0];        // DHT11: integer %RH
  _temp = data[2];       // DHT11: integer degC (fraction byte data[3] is 0)
  _ok = true;
  _lastReadMs = millis();
  temperatureC = _temp;
  humidityPct = _hum;
  return true;
}

int  Dht11::lastTemperatureC() { return _temp; }
int  Dht11::lastHumidityPct()  { return _hum; }
bool Dht11::lastReadOk()       { return _ok; }