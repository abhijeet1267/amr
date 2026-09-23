// ultrasonic.cpp

#include "ultrasonic.h"

static int          _front = -1, _left = -1, _right = -1, _rear = -1;
static unsigned long _lastPoll = 0;
static long         _pollInterval = 100;
static int          _thF = 20, _thL = 15, _thR = 15, _thB = 20;

void Ultrasonic::begin() {
  if (!ULTRASONIC_ENABLED) return;
  pinMode(PIN_FRONT_TRIG, OUTPUT); pinMode(PIN_FRONT_ECHO, INPUT);
  pinMode(PIN_LEFT_TRIG,   OUTPUT); pinMode(PIN_LEFT_ECHO,   INPUT);
  pinMode(PIN_RIGHT_TRIG,  OUTPUT); pinMode(PIN_RIGHT_ECHO,  INPUT);
  pinMode(PIN_REAR_TRIG,   OUTPUT); pinMode(PIN_REAR_ECHO,   INPUT);
  _lastPoll = millis();
}

void Ultrasonic::setThresholds(int front, int left, int right, int rear) {
  if (front > 0)  _thF = front;
  if (left > 0)   _thL = left;
  if (right > 0)  _thR = right;
  if (rear > 0)   _thB = rear;
}

void Ultrasonic::setPollIntervalMs(long ms) {
  if (ms >= 20) _pollInterval = ms;
}

static int readOne(int trig, int echo) {
  if (!ULTRASONIC_ENABLED) return -1;
  digitalWrite(trig, LOW);
  delayMicroseconds(2);
  digitalWrite(trig, HIGH);
  delayMicroseconds(10);
  digitalWrite(trig, LOW);
  long duration = pulseIn(echo, HIGH, (unsigned long)US_PULSE_TIMEOUT_US);
  if (duration == 0) return -1;          // no echo -> clear / timeout
  int cm = (int)(duration / 58);         // ~ 343 m/s round trip
  if (cm <= 0 || cm > US_MAX_RANGE_CM) return -1;
  return cm;
}

void Ultrasonic::readAll() {
  _front = readOne(PIN_FRONT_TRIG, PIN_FRONT_ECHO);
  _left  = readOne(PIN_LEFT_TRIG,   PIN_LEFT_ECHO);
  _right = readOne(PIN_RIGHT_TRIG,  PIN_RIGHT_ECHO);
  _rear  = readOne(PIN_REAR_TRIG,   PIN_REAR_ECHO);
  _lastPoll = millis();
}

int Ultrasonic::readFront() { return _front; }
int Ultrasonic::readLeft()   { return _left; }
int Ultrasonic::readRight()  { return _right; }
int Ultrasonic::readRear()   { return _rear; }

bool Ultrasonic::pollDue(unsigned long now) {
  if (!ULTRASONIC_ENABLED) return false;
  return (unsigned long)(now - _lastPoll) >= (unsigned long)_pollInterval;
}

bool Ultrasonic::safetyStopNeeded() {
  // Only valid (positive) readings can trigger a Layer-1 stop. A -1 (no echo)
  // means "clear", not "obstacle", so it does NOT stop the robot.
  if (!ULTRASONIC_ENABLED) return false;
  if (_front > 0 && _front < _thF) return true;
  if (_rear  > 0 && _rear  < _thB) return true;
  if (_left  > 0 && _left  < _thL) return true;
  if (_right > 0 && _right < _thR) return true;
  return false;
}

String Ultrasonic::format() {
  String out;
  out.reserve(32);
  out.concat("SENSOR F=");
  out.concat(_front);
  out.concat(" L=");
  out.concat(_left);
  out.concat(" R=");
  out.concat(_right);
  out.concat(" B=");
  out.concat(_rear);
  return out;
}
