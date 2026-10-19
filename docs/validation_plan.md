# Validation plan (targets from the report, Table 4 + Table 1/2)

**No target has been measured. The report is Pre-MVP; simulations cannot prove sensor accuracy, fall detection, radio reliability, battery life, or prediction quality.**

| Metric | Target | Procedure | Needs | Result | Status | Evidence |
|---|---|---|---|---|---|---|
| HR accuracy | ±5 % or ±5 bpm | MAX30102 vs reference, 200 samples | Physical sensor + reference oximeter | – | **Not tested** | – |
| SpO2 accuracy | ±2 % | same, 200 samples | same | – | **Not tested** | – |
| Temperature accuracy | ±0.5 °C | DS18B20 vs clinical thermometer, 100 samples | Physical sensor | – | **Not tested** | – |
| Fall detection | ≥ 95 % | 50 falls + 100 non-falls | Worn MPU6050, volunteers/protocol | – | **Not tested** | Heuristic is prototype only |
| LoRa PDR | ≥ 90 % | 500 packets at 0.5/1.2/2.5 km | Two SX1276 radios | – | **Not tested** | Gateway computes loss from seq gaps (unit-tested logic only) |
| End-to-end latency | ≤ 3 s | ESP32 -> dashboard timestamp | Full hardware chain | – | **Not tested** | – |
| HR prediction MAPE | ≤ 8 % | 80/20 split, 1000 samples | Real patient dataset | – | **Not tested** | `ml/evaluate_model.py` ready; only code-path run on synthetic sine data |
| SpO2 prediction MAPE | ≤ 5 % | same | same | – | **Not tested** | same |
| Risk classification | ≥ 90 % | 3-class confusion matrix | Labeled data | – | **Not tested** | Rule logic unit-tested for correctness, not accuracy |
| Prediction API inference | ≤ 300 ms | time `/predict` on Pi 4 | Raspberry Pi 4 | – | **Not tested** | Not benchmarked here |
| Other endpoint latency (50/100/200 ms) | per Table 2 | benchmark on Pi 4 | Raspberry Pi 4 | – | **Not tested** | – |
| Battery life | ≥ 24 h, 2000 mAh, 60 s uplink | discharge test | Hardware + power meter | – | **Not tested** | – |
| Uplink range | 2–5 km | field test | Hardware | – | **Not tested** | – |

## Software checks that WERE executed (correctness, not performance)
`python -m pytest` -> 105 passed: packet encode/decode, CRC, gateway duplicate/loss logic, API validation/auth/rate limit/alerts/ack/admin, database + retention, alert rules, risk rule precedence, fallback behaviour, end-to-end synthetic pipeline, C++/Python packet equivalence. Live run: Flask server + `gateway_simulator.py` over HTTP + curl.
