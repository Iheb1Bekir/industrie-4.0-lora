#pragma once
#include <Arduino.h>
struct TwoWire { void begin(int, int) {} void beginTransmission(int) {} int write(uint8_t) { return 1; } int endTransmission(bool = true) { return 0; }
  int requestFrom(uint8_t, uint8_t n) { return n; } int read() { return 0; } };
static TwoWire Wire;
