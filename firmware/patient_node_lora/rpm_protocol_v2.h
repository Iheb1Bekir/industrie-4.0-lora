// RPM raw-LoRa protocol v2 (34-byte frame, big-endian). Reference implementation: gateway/protocol.py.
// Specification: docs/PROTOCOL_SPECIFICATION.md. Keep this file IDENTICAL in firmware/patient_node_lora and
// firmware/relay_node (tests/test_protocol_v2.py checks that, and cross-checks the bytes against Python).
// Portable C++11: no Arduino dependency, so it is compiled and tested on the host with g++.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace rpm2 {
static const uint8_t VERSION = 2;
static const size_t FRAME_LEN = 34, HDR_LEN = 24, TAG_LEN = 8;
enum PayloadType : uint8_t { PT_MEASUREMENT = 1, PT_HEARTBEAT = 2, PT_ALERT = 3 };
enum : uint8_t { F_FALL = 1, F_SYNTH = 2, F_HRSPO2_FAULT = 4, F_TEMP_FAULT = 8, F_IMU_FAULT = 16, F_CRITICAL = 32, F_TIME_SYNCED = 64 };
static const int16_t TEMP_INVALID = -32768;
static const uint8_t BATTERY_UNSUPPORTED = 255;

struct Measurement {            // field names follow the project data structure (RPMMeasurement.msg)
  uint16_t patientId, sourceId, destinationId;
  uint32_t seqNo, timestamp;
  uint8_t heartRate, spO2;      // 0 when F_HRSPO2_FAULT
  int16_t temperature_x100;     // TEMP_INVALID when F_TEMP_FAULT
  uint8_t flags;                // F_* (fallDetected = F_FALL, critical = F_CRITICAL)
  uint8_t alertLevel;           // 0 normal, 1 warning, 2 critical, 3 fall
  uint8_t routingMode;          // 0 direct, 1 relay-assisted
  uint8_t hopCount, maxHopCount;
  uint8_t payloadType;
  uint8_t battery;              // 0..100, 255 = not supported
};

// HMAC-SHA256 provider: mbedTLS on the ESP32 (see hmacSha256 in the sketch); injected so this header stays portable.
typedef void (*HmacSha256Fn)(const uint8_t* key, size_t keyLen, const uint8_t* msg, size_t msgLen, uint8_t out[32]);

inline uint16_t crc16(const uint8_t* d, size_t n) {   // CRC-16/CCITT-FALSE
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < n; i++) {
    crc ^= (uint16_t)d[i] << 8;
    for (int b = 0; b < 8; b++) crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
  }
  return crc;
}

inline void packHeader(const Measurement& m, uint8_t h[24]) {
  h[0] = VERSION; h[1] = m.payloadType;
  h[2] = m.patientId >> 8; h[3] = m.patientId & 0xFF;
  h[4] = m.sourceId >> 8; h[5] = m.sourceId & 0xFF;
  h[6] = m.destinationId >> 8; h[7] = m.destinationId & 0xFF;
  h[8] = m.seqNo >> 24; h[9] = m.seqNo >> 16; h[10] = m.seqNo >> 8; h[11] = m.seqNo;
  h[12] = m.timestamp >> 24; h[13] = m.timestamp >> 16; h[14] = m.timestamp >> 8; h[15] = m.timestamp;
  h[16] = m.heartRate; h[17] = m.spO2;
  uint16_t t = (uint16_t)m.temperature_x100; h[18] = t >> 8; h[19] = t & 0xFF;
  h[20] = m.flags & 0x7F;
  h[21] = (uint8_t)((m.alertLevel & 0x0F) | ((m.routingMode & 0x0F) << 4));
  h[22] = (uint8_t)((m.maxHopCount & 0x0F) | ((m.hopCount & 0x0F) << 4));
  h[23] = m.battery;
}

// Sensor faults are encoded as flags + sentinel values so a frame is always decodable; values are never invented.
inline void normalize(Measurement& m) {
  if ((m.flags & F_HRSPO2_FAULT) || m.heartRate < 20 || m.heartRate > 250 || m.spO2 < 50 || m.spO2 > 100) {
    m.flags |= F_HRSPO2_FAULT; m.heartRate = 0; m.spO2 = 0;
  }
  if ((m.flags & F_TEMP_FAULT) || m.temperature_x100 < 2500 || m.temperature_x100 > 4500) {
    m.flags |= F_TEMP_FAULT; m.temperature_x100 = TEMP_INVALID;
  }
}

inline void encode(const Measurement& m, const uint8_t* key, size_t keyLen, HmacSha256Fn hmac, uint8_t out[34]) {
  packHeader(m, out);
  uint8_t immutable[24], mac[32];
  memcpy(immutable, out, 24);
  immutable[22] &= 0x0F;                       // hopCount is the only relay-mutable field: excluded from the tag
  hmac(key, keyLen, immutable, 24, mac);
  memcpy(out + 24, mac, TAG_LEN);
  uint16_t c = crc16(out, 32);
  out[32] = c >> 8; out[33] = c & 0xFF;
}

// Structural + CRC validation: everything a relay can verify without holding any device key.
inline bool checkFrame(const uint8_t* f, size_t n) {
  if (n != FRAME_LEN || f[0] != VERSION) return false;
  if (crc16(f, 32) != (uint16_t)((f[32] << 8) | f[33])) return false;
  if (f[1] < PT_MEASUREMENT || f[1] > PT_ALERT || (f[20] & 0x80)) return false;
  const bool zeroId = !(f[2] | f[3]) || !(f[4] | f[5]) || !(f[6] | f[7]) || !(f[8] | f[9] | f[10] | f[11]);
  return !zeroId;
}

inline uint16_t patientIdOf(const uint8_t* f) { return (uint16_t)((f[2] << 8) | f[3]); }
inline uint16_t destinationOf(const uint8_t* f) { return (uint16_t)((f[6] << 8) | f[7]); }
inline uint32_t seqNoOf(const uint8_t* f) { return ((uint32_t)f[8] << 24) | ((uint32_t)f[9] << 16) | ((uint32_t)f[10] << 8) | f[11]; }

// Application-level relay step (in place): validate, enforce the hop limit, hopCount++, recompute CRC.
// Returns false when the frame must be dropped.
inline bool relayForward(uint8_t* f, size_t n, uint8_t relayMaxHop) {
  if (!checkFrame(f, n)) return false;
  uint8_t hop = f[22] >> 4, maxHop = f[22] & 0x0F;
  uint8_t limit = maxHop < relayMaxHop ? maxHop : relayMaxHop;
  if (hop >= limit) return false;
  f[22] = (uint8_t)(((hop + 1) << 4) | maxHop);
  uint16_t c = crc16(f, 32);
  f[32] = c >> 8; f[33] = c & 0xFF;
  return true;
}

// Duplicate detection by (patientId, seqNo): fixed-size ring, no dynamic memory.
template <size_t N>
class DedupCache {
 public:
  bool seen(uint16_t patientId, uint32_t seqNo) const {
    for (size_t i = 0; i < count_; i++) if (pid_[i] == patientId && seq_[i] == seqNo) return true;
    return false;
  }
  void add(uint16_t patientId, uint32_t seqNo) {
    pid_[next_] = patientId; seq_[next_] = seqNo;
    next_ = (next_ + 1) % N; if (count_ < N) count_++;
  }
 private:
  uint16_t pid_[N]; uint32_t seq_[N]; size_t next_ = 0, count_ = 0;
};
}  // namespace rpm2
