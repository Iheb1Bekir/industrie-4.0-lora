#include <cstdio>
#include <cstdlib>
#include "patient_reading.h"

static void printReading(const rpm::PatientReading& reading,
                         const rpm::PatientReadingSources& sources) {
  const std::string json = rpm::serializePatientReading(reading, sources);
  std::puts(json.c_str());
}

int main() {
  printReading({1, 5000, 78, 98.0f, 36.7f, false},
               {"SIMULATED\nPROFILE", "SIMULATED_PROFILE", "DS18B20_SENSOR",
                "MPU6050_SENSOR_NO_FALL", true});
  printReading({2, 10000, 105, 94.0f, 37.5f, true},
               {"SIMULATED_PROFILE", "SIMULATED_PROFILE", "SIMULATED_PROFILE",
                "SERIAL_COMMAND_SIMULATED", true});
  printReading({3, 15000, 135, 88.0f, 38.9f, false},
               {"SIMULATED_PROFILE", "SIMULATED_PROFILE", "SIMULATED_PROFILE",
                "MPU6050_SENSOR_NO_FALL", true});
  printReading({4, 20000, 78, 98.0f, 0.0f, false},
               {"SIMULATED_PROFILE", "SIMULATED_PROFILE", "UNAVAILABLE_SENSOR",
                "UNAVAILABLE_ACCELEROMETER", false});

  const rpm::PatientProfile profiles[] = {
      rpm::PROFILE_NORMAL, rpm::PROFILE_WARNING, rpm::PROFILE_CRITICAL};
  for (rpm::PatientProfile profile : profiles) {
    const rpm::SimulatedVitals vitals = rpm::simulatedVitals(profile);
    if (vitals.heart_rate_bpm <= 0 || vitals.spo2_percent < 0 ||
        vitals.spo2_percent > 100 || vitals.temperature_c < 20 ||
        vitals.temperature_c > 45) return EXIT_FAILURE;
    std::printf("PROFILE %d %d %.1f %.1f\n", static_cast<int>(profile),
                vitals.heart_rate_bpm, vitals.spo2_percent, vitals.temperature_c);
  }

  bool fallPending = true;
  if (!rpm::consumeSimulatedFall(fallPending) || fallPending ||
      rpm::consumeSimulatedFall(fallPending)) return EXIT_FAILURE;

  if (!rpm::patientSampleDue(100, 0, false, 5000) ||
      rpm::patientSampleDue(5099, 100, true, 5000) ||
      !rpm::patientSampleDue(5100, 100, true, 5000) ||
      !rpm::patientSampleDue(50, 0xFFFFFF00u, true, 100)) return EXIT_FAILURE;
}
