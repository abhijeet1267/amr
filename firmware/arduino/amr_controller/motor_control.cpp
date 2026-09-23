// motor_control.cpp
//
// L298N motor HAL implementation. Direction from the sign of the speed;
// PWM magnitude only when MOTOR_PWM_ENABLED is 1.

#include "motor_control.h"

static bool _leftMoving = false;
static bool _rightMoving = false;
static int  _curLeft = 0;
static int  _curRight = 0;

// Drive one L298N channel. Direction is chosen by the sign of `speed`.
static void driveChannel(int pinFwd, int pinRev, int pinEn, int speed, bool& moving) {
  int mag = (speed < 0) ? -speed : speed;
  if (mag == 0) {
    digitalWrite(pinFwd, LOW);
    digitalWrite(pinRev, LOW);
    analogWrite(pinEn, 0);
    moving = false;
    return;
  }
  bool forward = (speed > 0);
  digitalWrite(pinFwd, forward ? HIGH : LOW);
  digitalWrite(pinRev, forward ? LOW : HIGH);
  int pwm = MOTOR_PWM_ENABLED ? mag : MOTOR_FULL_SPEED;
  if (pwm > MOTOR_FULL_SPEED) pwm = MOTOR_FULL_SPEED;
  analogWrite(pinEn, pwm);
  moving = true;
}

void MotorControl::begin() {
  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);
  pinMode(PIN_ENA, OUTPUT);
  pinMode(PIN_IN3, OUTPUT);
  pinMode(PIN_IN4, OUTPUT);
  pinMode(PIN_ENB, OUTPUT);
  stop();  // start in the safe state
}

void MotorControl::stop() {
  digitalWrite(PIN_IN1, LOW);
  digitalWrite(PIN_IN2, LOW);
  analogWrite(PIN_ENA, 0);
  digitalWrite(PIN_IN3, LOW);
  digitalWrite(PIN_IN4, LOW);
  analogWrite(PIN_ENB, 0);
  _leftMoving = false;
  _rightMoving = false;
  _curLeft = 0;
  _curRight = 0;
}

void MotorControl::setLeft(int speed) {
  if (speed > MOTOR_FULL_SPEED) speed = MOTOR_FULL_SPEED;
  if (speed < -MOTOR_FULL_SPEED) speed = -MOTOR_FULL_SPEED;
  driveChannel(PIN_IN1, PIN_IN2, PIN_ENA, speed, _leftMoving);
  _curLeft = speed;
}

void MotorControl::setRight(int speed) {
  if (speed > MOTOR_FULL_SPEED) speed = MOTOR_FULL_SPEED;
  if (speed < -MOTOR_FULL_SPEED) speed = -MOTOR_FULL_SPEED;
  driveChannel(PIN_IN3, PIN_IN4, PIN_ENB, speed, _rightMoving);
  _curRight = speed;
}

void MotorControl::setBoth(int left, int right) {
  setLeft(left);
  setRight(right);
}

bool MotorControl::anyMoving() { return _leftMoving || _rightMoving; }
int  MotorControl::leftSpeed()  { return _curLeft; }
int  MotorControl::rightSpeed() { return _curRight; }
