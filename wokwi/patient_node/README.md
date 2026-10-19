# Patient node (Wokwi)
Files: `diagram.json`, `patient_node.ino`, `telemetry.h`, `fall_detector.h`, `libraries.txt`. Setup, commands and scenarios: root `README.md` §7. Wiring: `docs/wiring.md`.
* Real simulated devices: DS18B20, MPU6050, LED, buzzer. **Synthetic: MAX30102.** **Serial text `LORA_TX_SIM` is not LoRa.**
* Local alerts use Active-HIGH GPIO 5 for one LED: off when normal (<37.5°C), medium blink when borderline (37.5–38.0°C), and fast blink when critical (>38.0°C). Active-HIGH GPIO 6 buzzes only during critical alerts. Heart-rate, SpO2, fall, and sensor-fault alerts remain active; a single-color LED cannot display separate green/yellow/red colors.
* Output per transmission: `DBG {json}` (human-readable) and `LORA_TX_SIM seq=N hex=<32 hex>` (the 16-byte payload; the gateway parses only the latter).
* MPU6050 reads acceleration (±2 g) and rotation (±250°/s) every 20 ms. A fall/motion event is latched for 10 s after free-fall <0.5 g followed by impact >2.5 g within 1 s, an acceleration change >=1.5 g between samples, or rotation >=200°/s. These prototype thresholds need validation; use `SET_SCENARIO FALL` to force a simulated event.
* Hardware mode: `#define RPM_USE_SX1276` + RadioLib (untested starter code).
* `tests/firmware_host/` checks packet encoding against the Python encoder, fall detection, sketch syntax, and local alert states/outputs with g++.
