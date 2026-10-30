// obstacle_warning.h
// Trigger buzzer + LCD warning when any ultrasonic reading is < 10 cm.

#pragma once
#include <Arduino.h>

#define OBSTACLE_WARN_CM 10

void checkObstacleWarning(int front, int left, int right, int rear);
