// Prototype motion heuristic: free-fall followed by impact, sudden acceleration change,
// or rapid rotation. Latches for 10 s; thresholds need validation on target hardware.
#pragma once
#include <math.h>
#include <stdint.h>

namespace rpm {
class FallDetector {
 public:
  float freefall_g = 0.5f, impact_g = 2.5f;
  float rapid_delta_g = 0.35f, rapid_rotation_dps = 90.0f;
  uint32_t window_ms = 1000, latch_ms = 10000;

  // Legacy acceleration-only path, preserving free-fall plus impact detection.
  bool update(float ax, float ay, float az, uint32_t now) {
    return updateMotion_(ax, ay, az, 0, 0, 0, now, false);
  }

  // Returns true exactly when a NEW fall or abrupt-motion event is detected.
  bool update(float ax, float ay, float az, float gx, float gy, float gz, uint32_t now) {
    return updateMotion_(ax, ay, az, gx, gy, gz, now, true);
  }

  bool active(uint32_t now) const { return haveFall_ && (uint32_t)(now - fallAt_) < latch_ms; }

 private:
  bool updateMotion_(float ax, float ay, float az, float gx, float gy, float gz,
                     uint32_t now, bool detectAbruptMotion) {
    float m = sqrtf(ax * ax + ay * ay + az * az);
    if (m < freefall_g) { ff_ = now; haveFf_ = true; }
    if (haveFf_ && m > impact_g && (uint32_t)(now - ff_) <= window_ms) {
      haveFf_ = false;
      return latch_(now);
    }
    if (haveFf_ && (uint32_t)(now - ff_) > window_ms) haveFf_ = false;

    bool abruptMotion = false;
    if (detectAbruptMotion) {
      if (havePrevious_) {
        float dx = ax - previousAx_, dy = ay - previousAy_, dz = az - previousAz_;
        float accelerationDelta = sqrtf(dx * dx + dy * dy + dz * dz);
        float rotation = sqrtf(gx * gx + gy * gy + gz * gz);
        abruptMotion = accelerationDelta >= rapid_delta_g || rotation >= rapid_rotation_dps;
      }
      previousAx_ = ax; previousAy_ = ay; previousAz_ = az;
      havePrevious_ = true;
    }
    return abruptMotion && latch_(now);
  }

  bool latch_(uint32_t now) {
    fallAt_ = now;
    haveFall_ = true;
    return true;
  }

  uint32_t ff_ = 0, fallAt_ = 0; bool haveFf_ = false, haveFall_ = false;
  float previousAx_ = 0, previousAy_ = 0, previousAz_ = 0;
  bool havePrevious_ = false;
};
}  // namespace rpm
