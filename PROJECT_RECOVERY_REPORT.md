# Project recovery report

Date of recovery: 2026-11-14. Everything below was established by inspecting the machine and the code, not assumed.

## 1. Local repository location

| Copy | Path | Git | Verdict |
|---|---|---|---|
| **Main project (used)** | `C:\Users\Admin\Downloads\remote-patient-monitoring\remote-patient-monitoring` | remote `origin = https://github.com/Iheb1Bekir/industrie-4.0-lora.git`, branch `main` @ `bbecab4`, clean working tree | Most complete and current copy. In sync with GitHub. |
| OMNeT++/FLoRa research project | WSL distro `opp_env`: `/home/opp_env/default_workspace/RPM_LoRa_Research` | own repository, **no remote**, 1 commit, 4 files with uncommitted changes (`Makefile`, `README.md`, `simulations/omnetpp.ini`, `src/doctor/DoctorApp.cc`) | Read only. Nothing was modified, rebuilt, installed or upgraded there. |
| `dashboardlora/telemed-dashboard` | `C:\Users\Admin\Downloads\dashboardlora` (+ `dashboardlora.zip`) | not a Git repository | Separate, earlier Spring Boot (Java 17, H2) dashboard attempt in French with its own prediction service. Not part of the GitHub project; **not merged** (different stack, would have replaced the working Python backend). Left untouched. |

Other Git repositories found on the machine (`E-LearningPlatform2024`, `RuView`, `WheeledRobotSimulations`, ESP-IDF…) are unrelated.
Search scope: Desktop, Documents, Downloads, AndroidStudioProjects, OneDrive, drive `D:` (depth 4), WSL distros. System folders, caches and virtual environments were excluded.

Environment: Windows 11 Home; WSL2 distros `opp_env` (OMNeT++) and `docker-desktop`; no Kali. Python 3.11.9 (system) and an existing project venv at `Downloads\remote-patient-monitoring\.venv` (Python 3.13.5, Flask 3.1, scikit-learn 1.9.1). `g++` (MSYS2) and the Arduino IDE's bundled `arduino-cli` are present. **Node.js is not installed** (this drove the choice of a build-free frontend).

## 2. GitHub connection status

* `git` 2.54 works; anonymous `git ls-remote` reaches the repository: `main` = `bbecab4` (same as local), `feature/tache3-alerte-esp32` = `b35c582` (already merged into `main` by "Merge partner ESP32 alert feature").
* **GitHub CLI (`gh`) is not installed**, so issues, pull requests and repository settings could not be read. To enable it:
  `winget install GitHub.cli`, then `gh auth login` (choose GitHub.com → HTTPS → "Login with a web browser"). Never paste a token or password into a chat.
* Nothing was pushed. All work is uncommitted in the working tree on `main` (you chose to keep the current branch).

Recovery points created before any change: Git tag `recovery/pre-platform-v2-20261114` (→ `bbecab4`), bundle `..\rpm-recovery-20261114.bundle` (all refs), copy of the existing database `..\rpm.sqlite3.backup-20261114`.

## 3. Existing project structure (before this work)

```
gateway/   Flask "pre-MVP" API: app.py, auth.py (2 bearer tokens), database.py (SQLite: patients/readings/alerts),
           telemetry.py (16-byte packet v1), bridge.py (gateway loop), radio.py (transport interfaces), alerts.py,
           prediction.py (linear-regression fallback + untested TFLite loader), maintenance.py (retention)
dashboard/ single-page doctor dashboard (token pasted into the page, polling)
wokwi/     ESP32-S3 patient-node firmware for the Wokwi simulator + serial "gateway simulator" CLI
ml/        train_model.py / evaluate_model.py (LSTM path; never run: no dataset, no TensorFlow)
tests/     107 passing tests (API, packet v1, pipeline, C++ host cross-checks)
docs/      architecture, wiring, hardware_deployment, simulation_limits, validation_plan, requirements_traceability
```

## 4. Implemented features found

* 16-byte telemetry packet v1 with CRC-16, identical C++/Python encoders (cross-checked by tests).
* Flask API (`/api/vitals`, `/api/patients`, history, predict, alerts, ack, retrain), SQLite storage, 30-day retention export.
* Rule-based alerts (HR > 120, SpO2 < 92, temperature, fall, sensor error, stale data) with de-duplication.
* Wokwi firmware: DS18B20, MPU6050 fall heuristic, LED/buzzer local alert states (partner task 3), serial commands, JSON patient reading.
* OMNeT++/FLoRa research model: `DistributedRPMNetwork` (20 patients in rings of 8/8/4, 3 relays in a chain, 1 doctor), `DistributedPatientApp`, `RPMRelayApp`, `RPMRelayMac`, `DistributedDoctorApp`, `RPMLoRaNic`, `RPMGatewayNic`, `RPMMeasurement.msg`; validated runs (79/80 delivered in the circular mixed-route run).

## 5. Incomplete features found

* Prediction: only a linear-regression extrapolation; the LSTM/TFLite path had no dataset, no artifact, no evaluation.
* Real LoRa: interfaces only (`Sx1276Transport` raises without a driver); firmware prints `LORA_TX_SIM` on serial.
* MAX30102: synthetic stand-in only.
* Dashboard: one page, one role, polling, token typed into the browser.

## 6. Missing features found

Users/roles/sessions, patient registration, device identity and pairing, caregiver access and consent, audit trail, real-time push, map, network monitoring, simulation engine inside the application, reports, relay support in the packet, packet authentication / replay protection, model training and evaluation pipeline, Raspberry Pi radio driver and gateway service, hardware configuration file, deployment and security documentation.

## 7. Existing bugs / defects found

| # | Finding | Status |
|---|---|---|
| B1 | Legacy README claims "105 automated tests"; 107 actually run. | Documented. |
| B2 | Legacy `/api/vitals` trusts the patient id in the payload: anyone with the shared doctor token can write data for any patient (no device identity). | Superseded by authenticated v2 frames; legacy API left unchanged and not mounted in the new server. |
| B3 | Legacy dashboard keeps the bearer token in `sessionStorage` (readable by any script on the page). | Superseded by HttpOnly session cookies. |
| B4 | Packet v1 has no relay fields (`routingMode`, `hopCount`, `maxHopCount`, `sourceId`, `destinationId`) although the OMNeT++ model and the cahier des charges structure require them. | Protocol v2 (documented, versioned, v1 still parseable). |
| B5 | v1 sequence number is 16-bit and restarts at boot (uniqueness relied on uptime). | v2: 32-bit, persisted in NVS. |
| B6 | `opp_env` login shell prints `Multiple versions specified for project inet: [4.6.0, 4.7.0]` (both INET 4.6.0 and 4.7.0 exist in the workspace). | **Not touched** (environment must not be altered). Use `opp_env run omnetpp-6.5.0 inet-4.6.0 …` as the research README does. |
| B7 | `docs/legacy/wiring.md` states that Wokwi part/pin names were never verified in Wokwi. | Still true; unchanged. |

## 8. Hardware and software assumptions recovered

* Patient node: **ESP32-S3 DevKitC-1** (the board used in Wokwi and `build_esp32_wokwi.ps1`). The three physical boards were not connected during this work (no COM port), so their exact model is **unverified**.
* Radio: the project documents plan an **SX1276 at 868 MHz** (node pins SCK 12 / MISO 13 / MOSI 11 / NSS 10 / RST 14 / DIO0 15). No radio driver, no library and no test evidence existed. The directive also mentions SX1278: **the actual chip is unknown** → firmware and gateway refuse to build/start until the chip and frequency are set explicitly.
* Sensors: DS18B20 on GPIO4 (1-Wire), MPU6050 on I2C GPIO8/9, MAX30102 planned on the same I2C bus (0x57), LED GPIO5, buzzer GPIO6. No GPS, no battery measurement circuit.
* Gateway: legacy documents say Raspberry Pi **4** (and mention a RAK2245 concentrator); you own a Raspberry Pi **5**. On the Pi 5 `RPi.GPIO` does not work → the new service uses `spidev` + `gpiozero/lgpio`.
* Radio profile (OMNeT++ `DistributedRPM`): 868 MHz, 125 kHz, SF7, CR 4/5, 14 dBm, `maxHopCount = 4`, `samplingInterval = 30 s`, `doctorId = 1`.

## 9. Previous architecture recovered

```
ESP32 patient node --(raw LoRa, custom app-level relay, NOT LoRaWAN)--> [relay 1 -> relay 2 -> relay 3] --> doctor gateway (Raspberry Pi)
                                                                                                    |-> validation, storage, alerts, prediction, dashboard
```
* Measurement structure (`RPMMeasurement.msg`): `patientId, seqNo, timestamp, heartRate, spO2, temperature, fallDetected, alertLevel, routingMode, sourceId, destinationId, hopCount, maxHopCount, critical`. `alertLevel`: 0 normal, 1 warning, 2 critical, 3 fall. `routingMode`: 0 direct, 1 relay-assisted.
* Relay rules (`RPMRelayApp`): payload must be an RPM measurement; drop duplicates by `(patientId, seqNo)`; `destinationId` must be the doctor; `patientId > 0`, `seqNo > 0`; `hopCount < min(relay.maxHopCount, payload.maxHopCount)`; never send back to the previous hop; then `hopCount++` and forward to the next hop.
* Doctor rules (`DistributedDoctorApp`): duplicate suppression by `(patientId, seqNo)`, direct vs relay-assisted counters, per-patient counts, alert counters, end-to-end delay.
* Topology: patients 1–16 direct, 17–20 through relays 1, 1, 2, 3; relays forward along the ordered chain.

All of this is preserved: protocol v2 carries exactly these fields, the relay firmware and the simulator's relay model apply exactly these rules, and the gateway keeps the same counters.

## 10. Conflicts between documentation and code

| Topic | Document says | Code / reality | Resolution |
|---|---|---|---|
| Topology | Report: *star* LoRa network | OMNeT++ model: multi-hop relays | Relay architecture kept (it is the later, more complete design); direct delivery is the `routingMode = 0` case. |
| Packet | Report: 16-byte payload | OMNeT++ payload modelled as 70 B with routing fields | v2 frame is 34 bytes (all fields + authentication tag). Time on air stays far below 1 % duty cycle at a 30 s interval. |
| Sampling interval | Report 60 s | OMNeT++ 30 s, Wokwi default 5 s | Configurable; firmware default 30 s (FLoRa scenario). |
| Gateway | Raspberry Pi 4 | You have a Raspberry Pi 5 | Pi 5 supported (GPIO stack differs). |
| Prediction | "TFLite LSTM + LR fallback" | No LSTM ever existed | Replaced by a model that is actually trained, compared and measured (gradient boosting). An LSTM is not justified by the data volume/benefit; decision documented in `docs/ML_PIPELINE.md`. Legacy LR code is untouched. |
| Auth | "single doctor token + admin token" | – | Kept for the legacy API only; the platform uses accounts, roles and sessions. |
| Cahier des charges | `indus_projet.pdf` referenced by `requirements_traceability.md` | **The PDF itself was not found on disk** (only `Downloads\Deploiement_Lora_exo.pdf`, an unrelated-looking exercise sheet that was not opened) | Requirements were recovered from the traceability table, the code and the research README. |

## 11. Implementation sequence that was followed

1. Protect (tag, bundle, DB copy) → 2. data model + migrations → 3. protocol v2 + security core → 4. ingestion pipeline, alert engine, real-time bus → 5. simulation engine through the same pipeline → 6. ML dataset/training/evaluation/inference → 7. REST API v1 → 8. web application (three roles) → 9. firmware, Pi radio driver, gateway service → 10. tests → 11. documentation.

Result and status of every item: see `FINAL_REPORT.md`.
