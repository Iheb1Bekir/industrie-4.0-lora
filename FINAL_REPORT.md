# Final report

Date: 2026-11-15. Scope: recovery of the existing project and completion of the platform. Read with `PROJECT_RECOVERY_REPORT.md` (what existed) and `MISSING_FEATURES_AND_RISK_ANALYSIS.md` (what remains).

## 1. Repository location
`C:\Users\Admin\Downloads\remote-patient-monitoring\remote-patient-monitoring` (virtual environment one level up: `..\.venv`, Python 3.13.5).
OMNeT++ research project (read only, untouched): WSL `opp_env`, `/home/opp_env/default_workspace/RPM_LoRa_Research`.

## 2. GitHub repository and branch
`https://github.com/Iheb1Bekir/industrie-4.0-lora`, branch `main` at `bbecab4` (local = remote). **All new work is uncommitted in the working tree** (you chose to stay on `main`; nothing was committed or pushed). Recovery points: tag `recovery/pre-platform-v2-20261114`, bundle `..\rpm-recovery-20261114.bundle`, `..\rpm.sqlite3.backup-20261114`. GitHub CLI is not installed, so issues/PRs were not read.

## 3. Recovered architecture
ESP32 patient nodes → custom raw-LoRa with application-level relays (not LoRaWAN) → Raspberry Pi doctor gateway → validation, storage, alerts, prediction, dashboard. Measurement structure and relay rules taken from `RPMMeasurement.msg`, `RPMRelayApp`, `DistributedDoctorApp`; topology 20 patients / 3 relays / 1 gateway kept as the research configuration, 3 nodes + Pi 5 as the physical configuration.

## 4. Implemented features
Accounts and three role experiences; server-side RBAC and patient scoping; patient registration; device enrolment, pairing, disable, replacement, key rotation; authenticated protocol v2 with relay support; single ingestion pipeline; alert engine with lifecycle, escalation and notifications; caregiver consent, expiry, revocation; consent-bound locations and Mahdia map; real-time stream; LoRa network monitoring and digital twin; simulation engine with seven scenarios and manual events; operating-mode switch with data isolation; ML dataset, training, evaluation, local inference with explanations, deploy/rollback; AI page fed from saved artifacts; CSV/PDF reports; audit trail with integrity check; administration CLI (users, backup, retention, mode, keys); real-radio firmware, relay firmware, Pi radio driver and gateway service (hardware pending); OMNeT++ result import.

## 5. Created and modified files
**Created** — `gateway/`: `settings.py store.py protocol.py security.py services.py ingest.py alert_engine.py events.py features.py inference.py simulator.py reports.py api_v1.py server.py manage.py radio_sx127x.py hw_gateway.py` · `web/`: `index.html`, `assets/css/app.css`, `assets/js/{app,core,charts,views-staff,views-ops}.js`, `assets/vendor/leaflet/` · `ml/`: `generate_dataset.py train.py models/ew-20261114/{model.joblib,metadata.json,metrics.json,curves.json} models/active.json` · `firmware/patient_node_lora/{patient_node_lora.ino,config.h,rpm_protocol_v2.h,fall_detector.h,libraries.txt}`, `firmware/relay_node/{relay_node.ino,config.h,rpm_protocol_v2.h}` · `hardware/gateway.example.toml` · `tools/import_omnet_results.py` · `simulation/omnetpp/imported_results/circular-mixed-route-r6.json` · `scripts/setup.ps1 setup.sh` · `tests/`: `v2_harness.py test_protocol_v2.py test_v2_security.py test_v2_pipeline.py test_v2_e2e.py test_v2_ml_and_hardware.py firmware_host/protocol_v2.cpp` · documentation: `PROJECT_RECOVERY_REPORT.md MISSING_FEATURES_AND_RISK_ANALYSIS.md FINAL_REPORT.md CHANGELOG.md` and `docs/{ARCHITECTURE,DATA_DICTIONARY,PROTOCOL_SPECIFICATION,SECURITY,ML_PIPELINE,MODEL_EVALUATION,HARDWARE_SETUP,RASPBERRY_PI_SETUP,ESP32_SETUP,SIMULATION_GUIDE,API_DOCUMENTATION,TESTING,DEPLOYMENT,TROUBLESHOOTING}.md`, `docs/legacy/README_v1.md`.
**Modified** — `README.md` (rewritten; original preserved), `.env.example`, `.gitignore`, `requirements.txt`, `tests/conftest.py` (two fixtures). **Moved** — six pre-MVP documents to `docs/legacy/`.
**Not modified** — all legacy gateway modules, legacy dashboard, Wokwi firmware, legacy ML scripts, legacy tests; the WSL OMNeT++ environment.
Outside the repository: two packages added to the existing venv (`cryptography`, `waitress`); Leaflet 1.9.4 downloaded from unpkg into `web/assets/vendor/`.

## 6. Frontend technologies
Plain HTML/CSS/JavaScript ES modules (no framework, no build step — Node.js is not installed), custom canvas/SVG charts, Leaflet 1.9.4 with OpenStreetMap tiles, Server-Sent Events, strict Content-Security-Policy, light and dark themes, responsive layout.

## 7. Backend technologies
Python, Flask 3 (waitress in production), SQLite (WAL), scrypt (werkzeug), AES-GCM (cryptography), HMAC-SHA256, scikit-learn runtime, standard-library PDF/CSV generation.

## 8. Database structure
Three files: `rpm_system` (users, sessions, password_resets, audit_log, settings, model_versions), `rpm_hw` and `rpm_sim` with the same clinical schema (patients, staff_assignments, consent_records, caregiver_links, devices, device_assignments, measurements, predictions, alerts, alert_events, clinical_notes, locations, network_events, network_counters, notifications, sim_sessions). Versioned migrations, foreign keys, indexes. Detail: `docs/DATA_DICTIONARY.md`.

## 9. Machine-learning architecture
Target `threshold_breach_10min` (will a sustained threshold condition start within 10 minutes, from the last 15 minutes). 38 features shared by training and inference. Five approaches compared under one protocol; selection on validation PR-AUC; isotonic calibration; occlusion-based local explanations; versioned artifacts with checksum; inference in-process on the gateway; failure-safe (`model_unavailable`).

## 10. Dataset details
`synth-v2`, synthetic, seed 20261114, 600 simulated patients × 8 h, 627 099 delivered samples, content SHA-256 `f24252fd…7162d`. Split by patient 360 / 120 / 120. Prediction rows train / validation / test: 349 341 / 120 212 / 116 861; positives 5 649 / 2 133 / 1 816. Regenerable with `python ml/generate_dataset.py` (not stored in Git).

## 11. Actual model evaluation results (held-out test set, computed by `ml/train.py`, version `ew-20261114`)

| Model | Accuracy | Precision | Recall | Specificity | F1 | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|---|---|
| **Histogram gradient boosting (selected)** | 0.9813 | 0.4334 | 0.6663 | 0.9862 | 0.5252 | 0.8861 | 0.5432 |
| Random forest | 0.9804 | 0.4200 | 0.6894 | 0.9850 | 0.5220 | 0.8974 | 0.5432 |
| Logistic regression | 0.9727 | 0.3070 | 0.6035 | 0.9785 | 0.4070 | 0.8921 | 0.4128 |
| Trend rule (no learning, baseline) | 0.9647 | 0.2414 | 0.5947 | 0.9705 | 0.3435 | 0.8771 | 0.3717 |
| Isolation forest (unsupervised, baseline) | 0.9695 | 0.2770 | 0.5986 | 0.9753 | 0.3787 | 0.8583 | 0.2586 |

Selected model: confusion matrix TN 113 463 / FP 1 582 / FN 606 / TP 1 210; false-positive rate 1.38 %, false-negative rate 33.4 %; calibrated Brier 0.0095, ECE 0.0008; positive prevalence 1.55 % (accuracy is therefore not informative). Episode view: 92 of 97 threshold-crossing episodes warned in advance (94.9 %), median lead time 510 s; 282 false-alarm episodes = 7.06 per patient-day. Inference 4.8 ms on the development PC (not measured on the Pi).

Honest reading: row-level precision and recall are modest; the model is clearly better than the no-learning trend rule and usefully early at episode level, at the price of a high false-alarm rate. All of it is on synthetic data. A first run with a weaker target definition scored lower and is recorded in `docs/ML_PIPELINE.md` § 5.

## 12. Model artifact location
`ml/models/ew-20261114/model.joblib` (+ `metadata.json`, `metrics.json`, `curves.json`), active pointer `ml/models/active.json`. scikit-learn 1.9.1, Python 3.13.5.

## 13. Raspberry Pi deployment procedure
`docs/RASPBERRY_PI_SETUP.md`: enable SPI → clone → `scripts/setup.sh --pi` → match scikit-learn version (or retrain) → `gen-key`, `.env`, `hardware/gateway.toml` → `create-user` → `set-mode hardware` → systemd units `rpm-platform` and `rpm-gateway` → HTTPS reverse proxy → backup cron. Not executed on a Pi.

## 14. ESP32 firmware status
Wokwi simulation firmware: unchanged, working as before. Real-radio firmware `firmware/patient_node_lora` and `firmware/relay_node`: written; the protocol header is compiled and byte-verified on the host; **the sketches have not been compiled with the ESP32 toolchain (RadioLib not installed) and never ran on a board**.

## 15. LoRa communication status
Protocol v2 implemented and tested in Python and C++ (host). SX127x Pi driver tested against a simulated chip. **No frame has been transmitted or received over the air.** Radio chip and frequency are unknown and must be set by you; SX126x is not supported on the Pi side.

## 16. Simulation status
Working: scenarios A–G, manual events, 1–20 patients, 1–3 relays, pause/resume/stop/reset, isolation from hardware data — all covered by automated tests and observed live in the browser.

## 17. Security implementation
See `docs/SECURITY.md`: hashed passwords, lockout and rate limit, HttpOnly/SameSite sessions with expiry, CSRF tokens, optional TOTP, server-side RBAC and patient scoping, consent-bound caregiver access, parameterized SQL, CSP and output escaping, encrypted device keys, authenticated radio frames with replay protection, hash-chained audit. Not provided: TLS (reverse proxy required), radio payload encryption, database encryption, dependency scanning, any certification.

## 18. Test results
`python -m pytest -q`:
* 107 pre-existing tests: pass (unchanged).
* 126 new tests: protocol 15, security 51, pipeline 22, end-to-end 20, ML + hardware adapters 18.
* Final run on 2026-11-15: **233 passed in 357.68 s, 0 failed, 0 skipped** (Windows 11, Python 3.13.5, g++ available). The one-line caregiver UI text added after this run is not covered by a test.
* Manual browser check: doctor workspace pages and caregiver home (also at phone width). Assistant workspace was not opened in a browser (API-tested).
* Not run: firmware compilation, anything on hardware, performance on the Pi, e-mail delivery, dependency audit, browser automation.

## 19. Features not yet physically validated
Everything involving the ESP32 boards, LoRa modules, sensors (MAX30102, DS18B20, MPU6050), battery reading, relay node, Raspberry Pi SPI/GPIO, radio range and delivery ratio, end-to-end latency, inference latency on the Pi, systemd services, HTTPS proxy.

## 20. Remaining hardware requirements
Four LoRa modules of the same band with antennas (three nodes + Pi; SX127x family on the Pi), confirmation of the ESP32 board model and of each sensor, optional fourth ESP32 + module for a relay, optional battery divider, optional RTC battery for the Pi 5. Decisions needed from you: radio chip, operating frequency and transmit power legal at your location.

## 21. Exact commands to launch the complete application (this PC)

```powershell
cd C:\Users\Admin\Downloads\remote-patient-monitoring\remote-patient-monitoring
..\.venv\Scripts\python.exe -m gateway.server
```
Open http://127.0.0.1:8000. Demo accounts (development only) are in `data\demo_credentials.txt`; they already exist on this PC. On a fresh checkout run `.\scripts\setup.ps1` first. Tests: `..\.venv\Scripts\python.exe -m pytest -q`.

## 22. Switching from simulation mode to hardware mode
1. Sign in as an administrator doctor.
2. **Simulation** page → Operating mode → **Real hardware** (or `python -m gateway.manage set-mode hardware`). The bar at the top turns to "HARDWARE MODE"; a running simulation is stopped; pages now show only the hardware database (empty until you register patients).
3. On the Pi, the platform must have `RPM_GATEWAY_INGEST_TOKEN` set and the `hw_gateway` service running (Administration → System health → "Hardware gateway: Enabled").
4. Switch back the same way; simulation data and hardware data never mix.

## 23. Connecting the three patient ESP32 devices
1. Identify the LoRa chip; in `firmware/patient_node_lora/config.h` uncomment the matching `RPM_RADIO_…`, set `RPM_LORA_FREQUENCY_MHZ`, check pins and enabled sensors. Set the same frequency in `hardware/gateway.toml`.
2. Wire each node and the Pi radio (`docs/HARDWARE_SETUP.md` §§ 2–3). Antennas on before powering.
3. Install the toolchain and libraries, compile and flash each board (`docs/ESP32_SETUP.md` §§ 1–3). First compilation may need small fixes.
4. Dashboard in hardware mode: **Patients → Register patient** (three times); **Devices → Register device** for each board and pair it — copy the `PROVISION <deviceId> <patientId> <gatewayId> <key>` line shown once.
5. Serial monitor of each board (115200): paste its `PROVISION` line → `OK provisioned`; `STATUS` to check.
6. Within one sampling interval each device turns **online** and measurements appear. Then run the test procedure in `docs/HARDWARE_SETUP.md` § 6 and record the results.

## Implementation checklist

| Feature | Status |
|---|---|
| Repository discovery, protection, recovery report | IMPLEMENTED AND TESTED |
| GitHub issues / PR inspection | BLOCKED (GitHub CLI not installed; needs your sign-in) |
| Database schema, migrations | IMPLEMENTED AND TESTED |
| Authentication (hashing, lockout, sessions, CSRF, reset, TOTP) | IMPLEMENTED AND TESTED |
| Three roles, server-side permissions, patient scoping | IMPLEMENTED AND TESTED |
| Patient registration, device enrolment/pairing/replacement | IMPLEMENTED AND TESTED |
| Protocol v2 (Python + C++ header) | IMPLEMENTED AND TESTED |
| Ingestion pipeline and validation | IMPLEMENTED AND TESTED |
| Alert engine, lifecycle, escalation, in-app notifications | IMPLEMENTED AND TESTED |
| Browser notifications | IMPLEMENTED BUT NOT FULLY TESTED (permission flow not exercised) |
| E-mail notifications | IMPLEMENTED BUT NOT FULLY TESTED (no delivery test) |
| SMS notifications | NOT IMPLEMENTED |
| Caregiver consent, expiry, revocation, reduced view | IMPLEMENTED AND TESTED |
| Real-time updates (SSE) | IMPLEMENTED AND TESTED |
| Doctor dashboard, patient profile, charts, alerts, devices, reports, admin pages | IMPLEMENTED BUT NOT FULLY TESTED (API tested; UI checked manually, not every dialog) |
| Assistant dashboard | IMPLEMENTED BUT NOT FULLY TESTED (API tested; not opened in a browser) |
| Caregiver dashboard | IMPLEMENTED BUT NOT FULLY TESTED (API tested; one manual view) |
| Mahdia map (simulated locations) | IMPLEMENTED AND TESTED (data) / manually viewed |
| Real patient locations (manual, consented) | IMPLEMENTED AND TESTED; GPS adapter NOT IMPLEMENTED |
| LoRa network page, digital twin | IMPLEMENTED AND TESTED (data) / manually viewed |
| OMNeT++ result import | IMPLEMENTED AND TESTED (one run imported) |
| Simulation engine, scenarios A–G, controls, isolation | IMPLEMENTED AND TESTED |
| Synthetic dataset generator | IMPLEMENTED AND TESTED |
| Training + evaluation pipeline, saved metrics | IMPLEMENTED AND TESTED |
| Local inference, explanations, deploy/rollback | IMPLEMENTED AND TESTED |
| AI intelligence page | IMPLEMENTED AND TESTED (data equals artifacts) / manually viewed |
| Model on the Raspberry Pi | HARDWARE PENDING |
| Reports CSV/PDF | IMPLEMENTED AND TESTED |
| Audit trail with integrity verification | IMPLEMENTED AND TESTED |
| Backup, retention CLI | IMPLEMENTED BUT NOT FULLY TESTED (retention tested; backup run manually not automated) |
| HTTPS/TLS | NOT IMPLEMENTED in the application (documented reverse proxy) |
| Radio payload encryption | NOT IMPLEMENTED |
| ESP32 real-radio firmware | HARDWARE PENDING (not compiled) |
| Relay firmware | HARDWARE PENDING (not compiled; no relay hardware) |
| Pi SX127x driver | HARDWARE PENDING (tested against a simulated chip) |
| Pi gateway service (spool, recovery) | HARDWARE PENDING (logic tested with a fake radio) |
| MAX30102 / DS18B20 / MPU6050 on real boards | HARDWARE PENDING |
| Three-patient physical test | HARDWARE PENDING (procedure written) |
| Clinical validation, regulatory compliance | NOT IMPLEMENTED (out of scope; not claimed) |
