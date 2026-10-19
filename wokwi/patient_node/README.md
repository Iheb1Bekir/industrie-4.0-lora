# Patient node (Wokwi)
Files: `diagram.json`, `patient_node.ino`, `telemetry.h`, `fall_detector.h`, `patient_reading.h`, `libraries.txt`. Setup, commands and scenarios: root `README.md` §7. Wiring: `docs/wiring.md`.
* Real simulated devices: DS18B20, MPU6050, LED, buzzer. **Synthetic: MAX30102.** **Serial text `LORA_TX_SIM` is not LoRa.**
* Output per transmission: one compact six-field JSON object per line, `DBG {json}` (human-readable), and `LORA_TX_SIM seq=N hex=<32 hex>` (the 16-byte payload; the gateway parses only the latter).
* Fall heuristic: free-fall < 0.5 g then impact > 2.5 g within 1 s, latched 10 s (prototype). In Wokwi it is awkward to move the MPU6050 sliders that fast, so use `SET_SCENARIO FALL`.
* Hardware mode: `#define RPM_USE_SX1276` + RadioLib (untested starter code).
* `tests/firmware_host/` compiles `telemetry.h`/`fall_detector.h` with g++ and compares packets with the Python encoder.

## Patient-reading JSON

The independent `rpm::PatientReading` structure and `rpm::serializePatientReading()` function are in `patient_reading.h`. The sketch fills this structure from its existing simulated/sensor values and prints one compact JSON object per line to the Serial Monitor. This JSON is an application-level representation only; the separate 16-byte telemetry packet and simulated transport are unchanged.

| Field | JSON type | Unit / meaning |
|---|---|---|
| `patient_id` | string | Configured node ID, currently `P001` (`P%03u`, adjustable with `SET_PATIENT`) |
| `timestamp` | string | `UPTIME+<seconds>s (NOT UTC)`; this node has no real-time clock or UTC source |
| `heart_rate` | number (integer) | Beats per minute (BPM) |
| `spo2` | number | Oxygen saturation percentage (0–100) |
| `temperature` | number | Degrees Celsius |
| `fall_detected` | boolean | `true` when the fall scenario/heuristic is active |

Example output (illustrative values):

```json
{"patient_id":"P001","timestamp":"UPTIME+3s (NOT UTC)","heart_rate":78,"spo2":98,"temperature":36.7,"fall_detected":false}
```

To build, run `.\scripts\build_esp32_wokwi.ps1` from the repository root with Arduino CLI and the ESP32 core installed. In Wokwi, start the ESP32-S3 simulation and inspect the Serial Monitor at 115200 baud. `SET_SCENARIO FALL` produces a reading with `"fall_detected":true`. Sensor-fault values that the existing packet normalization marks invalid are represented as numeric zero in this six-field JSON contract; this object does not include separate quality flags. Timestamps are uptime markers, not ISO 8601 wall-clock times.
