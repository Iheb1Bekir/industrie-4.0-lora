#pragma once

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

namespace rpm {
enum PatientProfile {
  PROFILE_NORMAL,
  PROFILE_WARNING,
  PROFILE_CRITICAL
};

struct PatientReading {
  uint16_t patient_id;
  uint32_t timestamp_ms;
  int heart_rate_bpm;
  float spo2_percent;
  float temperature_c;
  bool fall_detected;
};

struct PatientReadingSources {
  const char* heart_rate;
  const char* spo2;
  const char* temperature;
  const char* fall;
  bool temperature_valid;
};

struct SimulatedVitals {
  int heart_rate_bpm;
  float spo2_percent;
  float temperature_c;
};

inline SimulatedVitals simulatedVitals(PatientProfile profile) {
  switch (profile) {
    case PROFILE_WARNING: return {105, 94.0f, 37.5f};
    case PROFILE_CRITICAL: return {135, 88.0f, 38.9f};
    case PROFILE_NORMAL:
    default: return {78, 98.0f, 36.6f};
  }
}

inline bool patientSampleDue(uint32_t now, uint32_t lastSampleMs, bool started,
                             uint32_t intervalMs) {
  return !started || static_cast<uint32_t>(now - lastSampleMs) >= intervalMs;
}

inline bool consumeSimulatedFall(bool& pending) {
  const bool detected = pending;
  pending = false;
  return detected;
}

inline void appendJsonString(std::string& json, const char* value) {
  static const char hex[] = "0123456789ABCDEF";
  json.push_back('"');
  for (const unsigned char* c = reinterpret_cast<const unsigned char*>(value); *c; ++c) {
    switch (*c) {
      case '"': json += "\\\""; break;
      case '\\': json += "\\\\"; break;
      case '\b': json += "\\b"; break;
      case '\f': json += "\\f"; break;
      case '\n': json += "\\n"; break;
      case '\r': json += "\\r"; break;
      case '\t': json += "\\t"; break;
      default:
        if (*c < 0x20) {
          json += "\\u00";
          json.push_back(hex[*c >> 4]);
          json.push_back(hex[*c & 0x0F]);
        } else {
          json.push_back(static_cast<char>(*c));
        }
    }
  }
  json.push_back('"');
}

inline void appendJsonNumber(std::string& json, float value) {
  if (!std::isfinite(value)) value = 0.0f;
  char number[32];
  std::snprintf(number, sizeof(number), "%.2f", static_cast<double>(value));
  size_t length = std::strlen(number);
  while (length > 0 && number[length - 1] == '0') --length;
  if (length > 0 && number[length - 1] == '.') --length;
  json.append(number, length);
}

inline std::string serializePatientReading(const PatientReading& reading,
                                          const PatientReadingSources& sources) {
  std::string json = "{\"patient_id\":";
  json += std::to_string(reading.patient_id);
  json += ",\"timestamp_ms\":";
  json += std::to_string(reading.timestamp_ms);
  json += ",\"heart_rate_bpm\":";
  json += std::to_string(reading.heart_rate_bpm);
  json += ",\"heart_rate_source\":";
  appendJsonString(json, sources.heart_rate);
  json += ",\"spo2_percent\":";
  appendJsonNumber(json, reading.spo2_percent);
  json += ",\"spo2_source\":";
  appendJsonString(json, sources.spo2);
  json += ",\"temperature_c\":";
  if (sources.temperature_valid) appendJsonNumber(json, reading.temperature_c);
  else json += "null";
  json += ",\"temperature_source\":";
  appendJsonString(json, sources.temperature);
  json += ",\"fall_detected\":";
  json += reading.fall_detected ? "true" : "false";
  json += ",\"fall_status\":";
  appendJsonString(json, reading.fall_detected ? "YES" : "NO");
  json += ",\"fall_source\":";
  appendJsonString(json, sources.fall);
  json.push_back('}');
  return json;
}
}  // namespace rpm
