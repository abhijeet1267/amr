// lcd_i2c.cpp
//
// Minimal HD44780-over-PCF8574 driver. Wiring inside the backpack (standard
// `LiquidCrystal_I2C` mapping), bit -> PCF8574 pin:
//   P0 = RS, P1 = RW, P2 = E, P3 = backlight, P4..P7 = D4..D7
//
// See lcd_i2c.h — no third-party library, Wire (built-in) only.

#include "lcd_i2c.h"
#include <Wire.h>

bool LcdI2c::_present = false;

#define LCD_BIT_RS  0x01
#define LCD_BIT_RW  0x02
#define LCD_BIT_E   0x04
#define LCD_BIT_BL  0x08

void LcdI2c::begin() {
  Wire.begin();
  Wire.beginTransmission(LCD_I2C_ADDRESS);
  _present = (Wire.endTransmission() == 0);
  if (!_present) return;

  delay(50);  // HD44780 needs >40 ms after power-up before init

  // 4-bit init sequence (the documented HD44780 dance).
  writeNibble(0x03, false); delay(5);
  writeNibble(0x03, false); delayMicroseconds(150);
  writeNibble(0x03, false); delayMicroseconds(150);
  writeNibble(0x02, false); delayMicroseconds(150);  // 4-bit mode

  command(0x28);  // function set: 4-bit, 2 lines, 5x8 dots
  command(0x0C);  // display on, cursor off, blink off
  command(0x06);  // entry mode: increment, no shift
  clear();
}

void LcdI2c::pulseEnable(uint8_t value) {
  Wire.beginTransmission(LCD_I2C_ADDRESS);
  Wire.write(value | LCD_BIT_E);
  Wire.endTransmission();
  delayMicroseconds(1);
  Wire.beginTransmission(LCD_I2C_ADDRESS);
  Wire.write(value & ~LCD_BIT_E);
  Wire.endTransmission();
  delayMicroseconds(50);
}

void LcdI2c::writeNibble(uint8_t nibble, bool rs) {
  uint8_t value = (uint8_t)((nibble << 4) | LCD_BIT_BL);
  if (rs) value |= LCD_BIT_RS;
  pulseEnable(value);
}

void LcdI2c::send(uint8_t value, bool rs) {
  if (!_present) return;
  writeNibble((uint8_t)(value >> 4), rs);
  writeNibble((uint8_t)(value & 0x0F), rs);
}

void LcdI2c::command(uint8_t cmd) { send(cmd, false); }
void LcdI2c::data(uint8_t value)  { send(value, true); }

void LcdI2c::clear() {
  command(0x01);
  delay(2);  // clear needs ~1.5 ms
}

void LcdI2c::setCursor(uint8_t col, uint8_t row) {
  uint8_t addr = (uint8_t)(col + (row == 0 ? 0x00 : 0x40));
  command((uint8_t)(0x80 | addr));
}

void LcdI2c::print(const String& text) {
  for (unsigned int i = 0; i < text.length(); i++) {
    data((uint8_t)text.charAt(i));
  }
}

// Pad or truncate to exactly LCD_COLUMNS characters, then write at a row start.
static void writeRow(uint8_t row, const String& text) {
  String padded = text;
  if (padded.length() > LCD_COLUMNS) padded = padded.substring(0, LCD_COLUMNS);
  while (padded.length() < LCD_COLUMNS) padded += " ";
  LcdI2c::setCursor(0, row);
  LcdI2c::print(padded);
}

void LcdI2c::showLines(const String& line0, const String& line1) {
  if (!_present) return;
  writeRow(0, line0);
  writeRow(1, line1);
}

bool LcdI2c::present() { return _present; }