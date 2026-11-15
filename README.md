# Remote Patient Monitoring — ESP32 · raw LoRa · Raspberry Pi 5 · local early-warning model

Distributed patient monitoring: ESP32 patient nodes send vital signs over a **custom raw-LoRa protocol with application-level relays** (not LoRaWAN) to a Raspberry Pi 5 gateway that validates, stores, predicts, alerts and serves a role-based web application.

> **Research prototype. Not a medical device.** No clinical validation, no regulatory assessment. Alert limits are configurable engineering values. The prediction model is trained on **synthetic** data. Nothing has been validated on physical hardware yet — see the status table.

## Status at a glance

| Area | Status |
|---|---|
| Backend, database, authentication, three roles, alerts, reports | implemented and tested |
| Simulation mode (scenarios A–G through the real pipeline) | implemented and tested |
| ML dataset → training → evaluation → local inference → dashboard | implemented and tested (synthetic data) |
| Web application | implemented; checked manually in a browser (doctor role), API-tested for all roles |
| ESP32 real-radio firmware, relay firmware | written, **not compiled, hardware pending** |
| Raspberry Pi radio driver + gateway service | unit-tested against a simulated chip, **hardware pending** |
| OMNeT++ / FLoRa research model | untouched; results imported read-only |

Full checklist: [`FINAL_REPORT.md`](FINAL_REPORT.md). What was found and recovered: [`PROJECT_RECOVERY_REPORT.md`](PROJECT_RECOVERY_REPORT.md). Risks and gaps: [`MISSING_FEATURES_AND_RISK_ANALYSIS.md`](MISSING_FEATURES_AND_RISK_ANALYSIS.md).

## Quick start (simulation, Windows)

```powershell
.\scripts\setup.ps1                                  # venv, dependencies, model (if missing), demo accounts
.\.venv\Scripts\python.exe -m gateway.server         # http://127.0.0.1:8000
```
Sign in with a demo account from `data\demo_credentials.txt` (development only) → **Simulation** → choose a scenario → **Start simulation** → watch Overview, Alerts, Map, LoRa network, AI intelligence.

Linux / WSL: `scripts/setup.sh && . .venv/bin/activate && python -m gateway.manage seed-demo && python -m gateway.server`

Requirements: Python 3.11+ and a modern browser. No Node.js, no build step, no cloud service. `g++` is optional (firmware cross-check tests).

## Architecture in one picture

```
ESP32 patient node ──raw LoRa──▶ [relay]* ──▶ SX127x ─ hw_gateway (Pi) ─▶ ingestion pipeline ─▶ SQLite (hardware)
   sensors · protocol v2 · HMAC                        store-and-forward     CRC · device auth · replay window
                                                                             plausibility · alerts · inference
virtual devices (simulation engine) ─────────────── same pipeline ─────────▶ SQLite (simulation, separate file)
                                                                             │
                                             REST API v1 + SSE ─▶ web app (doctor · assistant · caregiver)
```
Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Documentation

| Topic | File |
|---|---|
| Architecture, isolation of simulation and hardware | `docs/ARCHITECTURE.md` |
| Measurement structure, tables, alert types | `docs/DATA_DICTIONARY.md` |
| LoRa frame v2, relay rules, security properties | `docs/PROTOCOL_SPECIFICATION.md` |
| Security controls, limits, privacy | `docs/SECURITY.md` |
| Dataset, features, training, deployment of the model | `docs/ML_PIPELINE.md` |
| Measured model results (generated) | `docs/MODEL_EVALUATION.md` |
| Wiring, radio parameters, 3-patient physical test plan | `docs/HARDWARE_SETUP.md` |
| ESP32 firmware build, provisioning | `docs/ESP32_SETUP.md` |
| Raspberry Pi installation, services, HTTPS, backup | `docs/RASPBERRY_PI_SETUP.md` |
| Simulation mode, OMNeT++ import, Wokwi | `docs/SIMULATION_GUIDE.md` |
| REST API | `docs/API_DOCUMENTATION.md` |
| Tests and what is not tested | `docs/TESTING.md` |
| Deployment, environment, recovery | `docs/DEPLOYMENT.md` |
| Common errors | `docs/TROUBLESHOOTING.md` |
| Pre-MVP documents (unchanged) | `docs/legacy/` |

## Repository layout

```
gateway/     platform (server, api_v1, ingest, alert_engine, inference, simulator, security, store, …)
             + legacy pre-MVP API (app.py, auth.py, database.py, bridge.py, radio.py, telemetry.py, …)
web/         browser application (ES modules, CSS, vendored Leaflet)
ml/          generate_dataset.py, train.py, models/<version>/ (artifact + metadata + metrics + curves)
firmware/    patient_node_lora/ and relay_node/ (real radios, protocol v2)   — hardware pending
wokwi/       Wokwi simulation firmware + serial gateway simulator (protocol v1) — unchanged
hardware/    gateway.example.toml (Pi radio configuration)
simulation/  omnetpp/imported_results/ (read-only summaries of OMNeT++/FLoRa runs)
tools/       import_omnet_results.py
tests/       233 automated tests
docs/        documentation
```

## Everyday commands

```bash
python -m gateway.server                       # platform
python -m gateway.manage create-user --role doctor --admin --username <name>    # real account (password prompted)
python -m gateway.manage seed-demo             # development demo accounts
python -m gateway.manage set-mode hardware     # or: simulation (also switchable in the UI)
python -m gateway.manage backup <dir> | retention | verify-audit | gen-key
python -m gateway.hw_gateway --config hardware/gateway.toml    # on the Pi: radio -> platform
python ml/generate_dataset.py && python ml/train.py            # rebuild dataset and model
python -m pytest -q                            # all tests
```

## From simulation to your hardware (short version)

1. Identify your LoRa modules; set chip + frequency in `firmware/patient_node_lora/config.h` and `hardware/gateway.toml`.
2. Pi: `docs/RASPBERRY_PI_SETUP.md` (secrets, services, hardware mode).
3. Dashboard (hardware mode): register patient → register device → pair; paste the shown `PROVISION …` line into the node's serial monitor.
4. Follow the test procedure in `docs/HARDWARE_SETUP.md` § 6.

## Legacy pre-MVP API and Wokwi firmware

The original Flask API with bearer tokens (`python -m gateway.app`, port 5000), its dashboard, the Wokwi firmware, the serial gateway simulator and their 107 tests are **unchanged**. Their original README is preserved as [`docs/legacy/README_v1.md`](docs/legacy/README_v1.md) (run instructions, Wokwi build, serial commands, API examples).

## License / data

No licence file exists in the repository yet (all rights reserved by default) — add one before publishing more widely. Leaflet 1.9.4 (BSD-2-Clause) is vendored in `web/assets/vendor/leaflet/`. The repository contains synthetic data only.
