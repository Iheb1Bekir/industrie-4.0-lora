# What is simulated, implemented, hardware-dependent, or incomplete

| Component | Category | Notes |
|---|---|---|
| DS18B20 reading | Simulated in Wokwi (genuine driver code path) | Value comes from Wokwi's slider (default 24 °C), not a body |
| MPU6050 acceleration | Simulated in Wokwi | Fall heuristic runs on simulated acceleration; `SET_SCENARIO FALL` injects a fall instead (reliable demo) |
| MAX30102 HR/SpO2 | **Synthetic data** | No MAX30102 in Wokwi; class `SyntheticHrSpo2` mimics the interface. Every packet carries the SYNTHETIC flag |
| LED + buzzer | Simulated in Wokwi | |
| SX1276 LoRa link | **Hardware-dependent / not simulated** | Wokwi serial text `LORA_TX_SIM` is a stand-in, **not LoRa**. `Sx1276Transport` (firmware, under `RPM_USE_SX1276`) and `gateway/radio.py::Sx1276Transport` are interfaces; no register-level Pi driver ships; never run over the air |
| Raspberry Pi | **Not simulated** | Python code runs on any computer; not run on a Pi here |
| Wokwi -> Python bridge | **Manual** | Copy lines from the Wokwi serial monitor into `--stdin`/`--file` (browser Wokwi has no link to local Python) |
| Gateway, Flask API, SQLite, alerts, retention, LR fallback, dashboard | **Implemented, executed on a computer** | 105 automated tests + live HTTP run |
| TFLite LSTM | **Incomplete** | No dataset, no trained artifact. Loader/training scripts written, untested |
| Prediction worker every 5 min | Not implemented | Computed on request |
| Nightly pruning schedule | Implemented as CLI; scheduling is a cron/Task Scheduler entry you add | |
| Firmware | Partially verified | Packet encoder + fall logic compiled and cross-checked against Python with g++; `patient_node.ino` passed a syntax/type check against hand-written Arduino stubs. **Not compiled with the real ESP32 core, not run in Wokwi** |
| All accuracy / latency / PDR / battery targets | **Not tested** | See `validation_plan.md` |
