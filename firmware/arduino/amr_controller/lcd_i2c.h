// lcd_i2c.h
//
// 16x2 character LCD on a PCF8574 I2C backpack (the common "HW-061"/"HW-61"
// module seen in the build photos). SDA=A4, SCL=A5, VCC=5V, GND=GND.
//
// No third-party library: this drives the backpack with the Arduino core's
// built-in `Wire` (I2C) library, so the firmware keeps its "no external
// dependencies" property. Only the HD44780 4-bit init sequence and the
// write/command/enable dance are implemented — nothing else.
//
// HARDWARE NOT TESTED: no LCD has been driven by this code. A missing display
// simply does not ACK on the bus; writes are best-effort and never block the
// control loop.

#pragma once

#include <Arduino.h>

//: Default PCF8574 backpack address (0x27). Change if your module is 0x3F.
#define LCD_I2C_ADDRESS 0x27
#define LCD_COLUMNS     16
#define LCD_ROWS        2

class LcdI2c {
 public:
  static void begin();

  static void clear();
  static void setCursor(uint8_t col, uint8_t row);

  // Write a string, truncated to the remaining columns on the row.
  static void print(const String& text);

  // Show two lines at once (row 0, row 1), each padded/truncated to 16 chars.
  static void showLines(const String& line0, const String& line1);

  // True when an I2C device answered at LCD_I2C_ADDRESS during begin().
  static bool present();

 private:
  static void writeNibble(uint8_t nibble, bool rs);
  static void send(uint8_t value, bool rs);
  static void command(uint8_t cmd);
  static void data(uint8_t value);
  static void pulseEnable(uint8_t value);

  static bool _present;
};