#include <cstdio>
#include "patient_reading.h"

int main() {
  const rpm::PatientReading readings[] = {
      {"PATIENT_01", "2026-10-19T19:58:00Z", 78, 98.0f, 36.7f, false},
      {"PATIENT_02", "UPTIME+8s (NOT UTC)", 88, 89.0f, 38.9f, true},
      {"PATIENT_\"\\\n\x01", "UPTIME+\t3s", 72, 97.5f, 36.6f, false},
      {"PATIENT_01", "UPTIME+12s (NOT UTC)", 80, 99.0f, 36.8f, false},
  };
  for (const rpm::PatientReading& reading : readings) {
    const std::string json = rpm::serializePatientReading(reading);
    std::puts(json.c_str());
  }
}
