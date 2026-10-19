#pragma once

#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>

namespace rpm {
struct PatientReading {
  std::string patient_id;
  std::string timestamp;
  int heart_rate;
  float spo2;
  float temperature;
  bool fall_detected;
};

inline void appendJsonString(std::string& json, const std::string& value) {
  static const char hex[] = "0123456789ABCDEF";
  json.push_back('"');
  for (unsigned char c : value) {
    switch (c) {
      case '"': json += "\\\""; break;
      case '\\': json += "\\\\"; break;
      case '\b': json += "\\b"; break;
      case '\f': json += "\\f"; break;
      case '\n': json += "\\n"; break;
      case '\r': json += "\\r"; break;
      case '\t': json += "\\t"; break;
      default:
        if (c < 0x20) {
          json += "\\u00";
          json.push_back(hex[c >> 4]);
          json.push_back(hex[c & 0x0F]);
        } else {
          json.push_back(static_cast<char>(c));
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

inline std::string serializePatientReading(const PatientReading& reading) {
  std::string json = "{\"patient_id\":";
  appendJsonString(json, reading.patient_id);
  json += ",\"timestamp\":";
  appendJsonString(json, reading.timestamp);
  json += ",\"heart_rate\":";
  json += std::to_string(reading.heart_rate);
  json += ",\"spo2\":";
  appendJsonNumber(json, reading.spo2);
  json += ",\"temperature\":";
  appendJsonNumber(json, reading.temperature);
  json += ",\"fall_detected\":";
  json += reading.fall_detected ? "true" : "false";
  json.push_back('}');
  return json;
}
}  // namespace rpm
