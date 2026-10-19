// Prints the packet for fixed inputs; tests/test_firmware_host.py compares with the Python encoder.
#include <cstdio>
#include "telemetry.h"
#include "fall_detector.h"
using namespace rpm;
static void show(Telemetry t) {
  normalize(t); uint8_t b[16]; encode(t, b);
  for (int i = 0; i < 16; i++) printf("%02X", b[i]);
  printf("\n");
}
int main() {
  show({1, 0, 72, 98, 3670, F_SYNTH, 60});
  show({999, 65535, 250, 100, 4500, F_FALL | F_SYNTH, 4294967295u});
  show({7, 12, 0, 0, 3660, F_SYNTH | F_HRSPO2_FAULT, 120});
  show({2, 1, 80, 97, 100, F_SYNTH, 5});        // out-of-range temp -> normalized to TEMP_FAULT
  FallDetector f; bool ok = true;
  ok &= !f.update(0, 0, 1.0f, 0);
  ok &= !f.update(0, 0, 0.1f, 100);              // free-fall
  ok &= f.update(0, 0, 3.2f, 400);               // impact within 1 s -> fall
  ok &= f.active(500) && !f.active(11000);
  FallDetector g; g.update(0, 0, 0.1f, 0);
  ok &= !g.update(0, 0, 3.2f, 2000);             // impact too late
  FallDetector h; ok &= !h.update(0, 0, 3.2f, 100);  // impact without free-fall
  FallDetector stable;
  ok &= !stable.update(0, 0, 1.0f, 0, 0, 0, 0);
  ok &= !stable.update(0, 0, 1.0f, 0, 0, 0, 20);
  ok &= !stable.active(20);
  FallDetector suddenAccel;
  suddenAccel.update(0, 0, 1.0f, 0, 0, 0, 0);
  ok &= suddenAccel.update(1.8f, 0, 0, 0, 0, 0, 20);
  FallDetector suddenRotation;
  suddenRotation.update(0, 0, 1.0f, 0, 0, 0, 0);
  ok &= suddenRotation.update(0, 0, 1.0f, 250, 0, 0, 20);
  printf("FALL_OK=%d\n", ok ? 1 : 0);
}
