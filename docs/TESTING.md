# Testing

```powershell
# Windows (from the repository root)
.\.venv\Scripts\python.exe -m pytest -q
```
```bash
# Linux / WSL / Raspberry Pi
python -m pytest -q
```
The whole suite runs offline with temporary databases and a fake clock (no sleeping, deterministic). It takes about 8–10 minutes on the development PC. C++ cross-checks need `g++` and are skipped without it.

## Suites

| File | Scope |
|---|---|
| `tests/test_protocol_v2.py` | frame round-trip, tampering, relay step, hop limit, v1 compatibility, **C++ firmware header vs Python byte equality**, firmware config has no default frequency/radio |
| `tests/test_v2_security.py` | password hashing, lockout, rate limit, session expiry/theft, cookie flags, CSRF, reset, forced password change, TOTP, role matrix on every endpoint, IDOR, SQL injection, XSS/CSP, CSV injection, error leakage, key encryption at rest, audit chain tampering |
| `tests/test_v2_pipeline.py` | ingestion outcomes (unknown / unpaired / disabled / wrong key / wrong routing / CRC / malformed), duplicates, replay, out-of-order, loss estimate, key rotation, hop limit, missing and implausible values, clock handling, alert lifecycle, patient limits, escalation, offline detection, notification storm protection, device replacement, gateway ingestion endpoint, legacy v1, SSE filtering, reports, time filters, retention |
| `tests/test_v2_e2e.py` | acceptance scenarios 1–12 (below) + scenarios B/D/E/F, 20-patient topology, network impairments, location consent, OMNeT++ import display |
| `tests/test_v2_ml_and_hardware.py` | features (no look-ahead, missing data, artifact robustness), dataset reproducibility, label construction, saved metadata/metrics structure, inference + explanation, model unavailable, checksum refusal, deploy/rollback, **SX127x driver against a simulated chip**, gateway service forwarding / spooling / radio recovery, gateway config, OMNeT++ importer |
| `tests/test_api.py`, `test_pipeline.py`, `test_telemetry.py`, … | the 107 pre-existing tests of the legacy pre-MVP API (unchanged) |

## Acceptance scenarios (directive § 15.4) → tests

| # | Scenario | Test |
|---|---|---|
| 1 | Register a patient and associate a device | `test_01_register_patient_and_associate_device` |
| 2 | Normal measurements displayed in real time | `test_02_normal_measurements_flow_in_real_time` |
| 3 | Abnormal heart rate creates an alert | `test_03_abnormal_heart_rate_creates_alert` |
| 4 | Fall creates a high-priority alert | `test_04_fall_creates_high_priority_alert` |
| 5 | Gradual trend evaluated by the prediction module | `test_05_gradual_trend_is_predicted_before_the_threshold_alert` |
| 6 | Patient on the Mahdia map | `test_06_patients_appear_on_the_mahdia_map` |
| 7 | Doctor sees all authorized patients | `test_07_doctor_sees_all_authorized_patients` |
| 8 | Assistant restricted access | `test_08_assistant_has_restricted_access` |
| 9 | Caregiver patient-specific access | `test_09_caregiver_sees_only_the_consented_patient_in_reduced_form` |
| 10 | Disconnected simulated device detected | `test_10_disconnected_device_is_detected_by_the_backend` |
| 11 | Stop simulation / no synthetic data in the hardware stream | `test_11_stopping_simulation_and_isolation_from_hardware_data` |
| 12 | Model metrics match the saved evaluation artifacts | `test_12_dashboard_model_metrics_equal_the_saved_evaluation_artifacts` |

These exercise the backend exactly as the browser does (same HTTP API). The browser UI itself was checked manually (below); there is no automated browser test suite.

## Manual UI verification performed

On the development PC, in the in-app browser, with the server running and scenario F (5 patients, ×10): sign-in as the demo doctor; Overview (KPIs, data-flow strip, live tiles, toasts for new alerts); patient profile (live vitals, charts, limit lines, prediction badge); LoRa network (counters, topology, events, research panel); AI intelligence (metrics, confusion matrix, curves); map (OpenStreetMap tiles, status-coloured markers around Mahdia); Alerts, Devices, Reports, Administration pages load without script errors. Not manually exercised in the browser: assistant and caregiver sessions (covered by API tests), dialogs for every form, mobile layouts, light theme screenshots.

## Hardware tests

None executed (no hardware connected). Procedure: `HARDWARE_SETUP.md` § 6. Until those steps are run and recorded, every radio, sensor, firmware and Pi item is **HARDWARE PENDING**.

## Not tested / not available

* Firmware compilation with the ESP32 toolchain (RadioLib is not installed on this PC).
* Performance on the Raspberry Pi (latency numbers in the artifacts are from the development PC).
* E-mail delivery; SMS (no adapter).
* Load beyond 20 simulated devices; long-duration soak.
* Dependency vulnerability scan: `pip install pip-audit && pip-audit -r requirements.txt` (tool not installed here; run it before deployment).
* Formal penetration test.

## Useful single commands

```bash
python -m pytest tests/test_v2_e2e.py -q -k test_05          # the predictive scenario only
python -m pytest tests/test_protocol_v2.py -q                 # protocol + firmware header (fast)
python -m gateway.manage verify-audit
```
