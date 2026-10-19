// Prototype fall heuristic: free-fall (|a| < 0.5 g) followed within 1 s by an impact (|a| > 2.5 g).
// Latches for 10 s. NOT validated (report target: >=95% on 50 falls + 100 non-falls - not yet measured).
#pragma once
#include <math.h>
#include <stdint.h>

namespace rpm {
class FallDetector {
 public:
  float freefall_g = 0.5f, impact_g = 2.5f;
  uint32_t window_ms = 1000, latch_ms = 10000;
  // Returns true exactly when a NEW fall is detected.
  bool update(float ax, float ay, float az, uint32_t now) {
    float m = sqrtf(ax * ax + ay * ay + az * az);
    if (m < freefall_g) { ff_ = now; haveFf_ = true; }
    if (haveFf_ && m > impact_g && (uint32_t)(now - ff_) <= window_ms) {
      haveFf_ = false; fallAt_ = now; haveFall_ = true; return true;
    }
    if (haveFf_ && (uint32_t)(now - ff_) > window_ms) haveFf_ = false;
    return false;
  }
  bool active(uint32_t now) const { return haveFall_ && (uint32_t)(now - fallAt_) < latch_ms; }
 private:
  uint32_t ff_ = 0, fallAt_ = 0; bool haveFf_ = false, haveFall_ = false;
};
}  // namespace rpm
