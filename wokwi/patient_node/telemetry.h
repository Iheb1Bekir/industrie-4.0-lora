// 16-byte telemetry packet v1 (big-endian). Layout documented in gateway/telemetry.py - keep both in sync.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace rpm {
enum : uint8_t { F_FALL = 1, F_SYNTH = 2, F_HRSPO2_FAULT = 4, F_TEMP_FAULT = 8, F_IMU_FAULT = 16 };
static const size_t PACKET_LEN = 16;
static const uint8_t PROTO_VERSION = 1;
static const int16_t TEMP_INVALID = -32768;

struct Telemetry {
  uint16_t pid;       // 1..999
  uint16_t seq;
  uint8_t hr;         // bpm
  uint8_t spo2;       // %
  int16_t temp_x100;  // 0.01 degC
  uint8_t flags;
  uint32_t uptime_s;
};

inline uint16_t crc16(const uint8_t* d, size_t n) {  // CRC-16/CCITT-FALSE
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < n; i++) {
    crc ^= (uint16_t)d[i] << 8;
    for (int b = 0; b < 8; b++) crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
  }
  return crc;
}

// Out-of-range values are converted into fault flags so every packet stays decodable by the gateway.
inline void normalize(Telemetry& t) {
  if (t.flags & F_HRSPO2_FAULT || t.hr < 20 || t.hr > 250 || t.spo2 < 50 || t.spo2 > 100) {
    t.flags |= F_HRSPO2_FAULT; t.hr = 0; t.spo2 = 0;
  }
  if (t.flags & F_TEMP_FAULT || t.temp_x100 < 2000 || t.temp_x100 > 4500) {
    t.flags |= F_TEMP_FAULT; t.temp_x100 = TEMP_INVALID;
  }
  t.flags &= 0x1F;
}

inline void encode(const Telemetry& t, uint8_t out[16]) {
  out[0] = PROTO_VERSION;
  out[1] = t.pid >> 8; out[2] = t.pid & 0xFF;
  out[3] = t.seq >> 8; out[4] = t.seq & 0xFF;
  out[5] = t.hr; out[6] = t.spo2;
  uint16_t tv = (uint16_t)t.temp_x100;
  out[7] = tv >> 8; out[8] = tv & 0xFF;
  out[9] = t.flags;
  out[10] = t.uptime_s >> 24; out[11] = t.uptime_s >> 16; out[12] = t.uptime_s >> 8; out[13] = t.uptime_s;
  uint16_t c = crc16(out, 14);
  out[14] = c >> 8; out[15] = c & 0xFF;
}
}  // namespace rpm
