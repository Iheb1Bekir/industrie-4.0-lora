# Patient node (Wokwi)
Files: `diagram.json`, `patient_node.ino`, `telemetry.h`, `fall_detector.h`, `libraries.txt`. Setup, commands and scenarios: root `README.md` §7. Wiring: `docs/wiring.md`.
* Real simulated devices: DS18B20, MPU6050, LED, buzzer. **Synthetic: MAX30102.** **Serial text `LORA_TX_SIM` is not LoRa.**
* Output per transmission: `DBG {json}` (human-readable) and `LORA_TX_SIM seq=N hex=<32 hex>` (the 16-byte payload; the gateway parses only the latter).
* Fall heuristic: free-fall < 0.5 g then impact > 2.5 g within 1 s, latched 10 s (prototype). In Wokwi it is awkward to move the MPU6050 sliders that fast, so use `SET_SCENARIO FALL`.
* Hardware mode: `#define RPM_USE_SX1276` + RadioLib (untested starter code).
* `tests/firmware_host/` compiles `telemetry.h`/`fall_detector.h` with g++ and compares packets with the Python encoder.
