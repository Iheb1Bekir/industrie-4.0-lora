#pragma once
#include "OneWire.h"
struct DallasTemperature { DallasTemperature(OneWire*) {} void begin() {} void setWaitForConversion(bool) {} int getDeviceCount() { return 1; }
  void requestTemperatures() {} float getTempCByIndex(int) { return 36.5f; } };
