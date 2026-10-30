// obstacle_warning.cpp
#include "obstacle_warning.h"
#include "buzzer.h"
#include "lcd_i2c.h"

static bool _warningActive = false;
static String _lastSide = "";

void checkObstacleWarning(int front, int left, int right, int rear) {
  // Check each face against the 10 cm threshold.
  // Only valid (positive) readings count. -1 = no echo (clear).
  String side = "";
  int minVal = 999;

  if (front > 0 && front < OBSTACLE_WARN_CM) { side = "FRONT"; minVal = front; }
  if (left > 0 && left < OBSTACLE_WARN_CM && left < minVal) { side = "LEFT"; minVal = left; }
  if (right > 0 && right < OBSTACLE_WARN_CM && right < minVal) { side = "RIGHT"; minVal = right; }
  if (rear > 0 && rear < OBSTACLE_WARN_CM && rear < minVal) { side = "REAR"; minVal = rear; }

  if (side.length() > 0) {
    // Obstacle detected < 10 cm on at least one side.
    _warningActive = true;
    _lastSide = side;

    // Sound buzzer at 1500 Hz (audible alarm, bounded).
    Buzzer::beep(1200);

    // Update LCD with obstacle warning and side.
    if (LcdI2c::present()) {
      char line1[17];
      snprintf(line1, sizeof(line1), "SIDE: %s <%dcm", side.c_str(), OBSTACLE_WARN_CM);
      LcdI2c::showLines("OBSTACLE ALERT!", String(line1));
    }
  } else if (_warningActive) {
    // Condition cleared — all sensors >= 10 cm.
    _warningActive = false;
    _lastSide = "";
    Buzzer::stop();

    if (LcdI2c::present()) {
      LcdI2c::showLines("PATH CLEAR", "ALL > 10cm");
    }
  }
}
