# Requirements traceability (source: `indus_projet.pdf`, Oct 8 2026, status "Pre-MVP")

The report states that **no measurements exist**; all numbers are *targets*. Status legend:
**Impl** = implemented and executed on a computer · **Sim** = synthetic/simulated · **HW** = needs physical hardware · **Open** = not implemented.

| # | Report requirement (section) | Where | Status |
|---|---|---|---|
| R1 | ESP32 node: MAX30102 (HR/SpO2), DS18B20, MPU6050, SX1276, buzzer+LED (§3, Tab.1) | `wokwi/patient_node` | DS18B20 + MPU6050 + LED + buzzer in Wokwi circuit; **MAX30102 synthetic**; **SX1276 hardware-only** |
| R2 | 60 s cycle, 16-byte payload (§3) | `gateway/telemetry.py`, `telemetry.h` | Impl (fits exactly 16 B incl. CRC) |
| R3 | Star LoRa 868/915 MHz, SF7–SF12, 125 kHz (§3) | `gateway/radio.py` `LoRaConfig` | Config only, **HW** |
| R4 | Raspberry Pi 4 gateway script -> POST /api/vitals (§5.2) | `gateway/bridge.py` | Impl (sim transport); radio **HW** |
| R5 | Flask app serves UI + JSON API in one process (§5.1) | `gateway/app.py` | Impl |
| R6 | SQLite, 30 days, older rows exported to CSV and pruned nightly (§5.1, §5.8) | `gateway/database.py`, `maintenance.py` | Impl (nightly scheduling = cron, documented) |
| R7 | TFLite LSTM + scikit-learn LR fallback, same process (§5.1) | `gateway/prediction.py` | LR fallback Impl; **no trained LSTM exists** (loader written, untested) |
| R8 | Prediction every 5 min via worker (§5.2) | computed per request | **Deviation**: no background worker |
| R9 | Single Bearer token (doctor) + admin token for retrain only (§5.3) | `gateway/auth.py` | Impl |
| R10 | 8 endpoints in Table 2 | `gateway/app.py` | Impl; `/api/patients` added for dashboard; retrain returns 501 unless `{"action":"reload"}` |
| R11 | Request/response examples (§5.5) | tests | Impl (compatible; extra optional fields) |
| R12 | Risk rule (§5.6) | `prediction.risk_rule` | Impl, High takes precedence |
| R13 | Errors 200/201/400/401/404/429/500, body `{"error","code"}` (§5.8) | `gateway/app.py` | Impl |
| R14 | 1 write / 30 s / patient on /api/vitals (§5.8) | `gateway/app.py` | Impl, configurable |
| R15 | Rule-based alerts + local buzzer/LED (§3 L5) | `alerts.py`, firmware | Impl; thresholds are prototype defaults (report gives none for alerts) |
| R16 | Doctor dashboard: live vitals, history, alerts (§3 L4) | `dashboard/` | Impl |
| R17 | Validation targets (Tab.4) | `docs/validation_plan.md` | All **Not tested** |
| R18 | Latency targets per endpoint (Tab.2) | not benchmarked | **Not tested** |

Assumptions: ESP32-**S3** DevKitC-1 used in Wokwi (report says "ESP32 DevKit", 240 MHz; S3 is also 240 MHz). Prediction step = 5 min (3 values for horizon 15, as in the report example). `/api/vitals` uses the doctor-level token (the report defines no gateway credential). The report gives no alert thresholds -> prototype defaults, **not clinically validated**.
