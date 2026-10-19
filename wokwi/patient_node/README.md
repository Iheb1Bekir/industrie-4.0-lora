# Patient node (Wokwi)

Files: `diagram.json`, `patient_node.ino`, `telemetry.h`, `fall_detector.h`, `patient_reading.h`, `libraries.txt`. Setup and wiring: root `README.md` §7 and `docs/wiring.md`.

The circuit uses an ESP32-S3 DevKitC-1 with a Wokwi-simulated DS18B20, MPU6050, LED, and buzzer. There is no MAX30102 in the circuit: heart rate and SpO2 use deterministic software test profiles. The serial `LORA_TX_SIM` output is a binary telemetry test path, not an over-the-air LoRa transmission.

## Patient readings

Each sampling cycle prints one compact JSON record. `timestamp_ms` is elapsed milliseconds since boot (`millis()`), not calendar time or UTC. Measurement sources are included in the record so missing sensors are not silently replaced by generated values.

| Field | Type | Unit / meaning |
|---|---|---|
| `patient_id` | integer | Patient number, defaults to `1`; configure with `SET_PATIENT 1..999` |
| `timestamp_ms` | integer | Milliseconds elapsed since startup |
| `heart_rate_bpm` | integer | Beats per minute; simulated |
| `heart_rate_source` | string | `SIMULATED_PROFILE` |
| `spo2_percent` | number | Saturation percent, 0–100; simulated |
| `spo2_source` | string | `SIMULATED_PROFILE` |
| `temperature_c` | number or `null` | Temperature in Celsius; `null` when no valid sensor reading is available |
| `temperature_source` | string | `DS18B20_SENSOR`, `SIMULATED_PROFILE`, or an `UNAVAILABLE_...` reason |
| `fall_detected` | boolean | Whether a fall event was detected |
| `fall_status` | string | `YES` or `NO` |
| `fall_source` | string | MPU6050 heuristic, simulated command/scenario, or unavailable reason |

Example (illustrative):

```json
{"patient_id":1,"timestamp_ms":5000,"heart_rate_bpm":78,"heart_rate_source":"SIMULATED_PROFILE","spo2_percent":98,"spo2_source":"SIMULATED_PROFILE","temperature_c":36.7,"temperature_source":"DS18B20_SENSOR","fall_detected":false,"fall_status":"NO","fall_source":"MPU6050_SENSOR_NO_FALL"}
```

The development sampling interval defaults to 5 seconds. Change it at runtime with `SET_SAMPLE_INTERVAL <1..3600>`; the deployment specification's 60-second sampling interval can be selected with `SET_SAMPLE_INTERVAL 60`. This reading interval is separate from the existing telemetry transmit interval (`SET_INTERVAL`, default 60 seconds). Both use non-blocking `millis()` scheduling.

## Test commands

Commands are case-insensitive. A newly selected profile is used by the next reading:

* `NORMAL`: 78 BPM, 98% SpO2.
* `WARNING`: 105 BPM, 94% SpO2.
* `CRITICAL`: 135 BPM, 88% SpO2.
* `FALL`: queue one clearly labeled simulated fall for the next patient reading; it clears after that record.
* `TEMP_SOURCE SENSOR|SYNTH`: use the DS18B20 or the selected profile's simulated temperature (36.6, 37.5, or 38.9 °C for normal, warning, or critical).
* `HELP`, `STATUS`, and `SET_PATIENT <1..999>` are also available.

HR/SpO2 are always software-generated; selecting profiles does not claim they came from physical sensors. Temperature defaults to the DS18B20. If it is absent or outside the accepted 20–45 °C range, `temperature_c` is `null` with an `UNAVAILABLE_...` source; no synthetic fallback is applied unless `TEMP_SOURCE SYNTH` is selected. The existing LED/buzzer alert manager evaluates the sampled patient reading. MPU6050 acceleration uses the existing prototype fall heuristic, not clinically validated fall detection. The `FALL` command is only a one-reading test event, not a physical-fall measurement.

## Build and run

With Arduino CLI, the ESP32 core, OneWire, and DallasTemperature installed, build from the repository root:

```powershell
.\scripts\build_esp32_wokwi.ps1
```

The target is `esp32:esp32:esp32s3` (ESP32-S3 DevKitC-1). In Wokwi, load the files under `wokwi/patient_node/`, including `patient_reading.h`, start the simulation, and open the Serial Monitor at 115200 baud. Use the commands above and verify one JSON object per patient sample. The 16-byte telemetry packet is still transmitted only through the pre-existing serial simulation path; this task adds no LoRa behavior.
