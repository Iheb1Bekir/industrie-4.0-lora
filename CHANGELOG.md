# Changelog

## [2.0.0] — 2026-11-14 (uncommitted working tree on `main`; recovery tag `recovery/pre-platform-v2-20261114`)

### Added
- **Platform server** (`python -m gateway.server`): REST API v1, Server-Sent Events, web application for three roles (doctor, medical assistant, family caregiver), administration CLI (`gateway.manage`).
- **Data model**: three SQLite databases (system / hardware / simulation) with versioned migrations: users, sessions, audit, patients, staff assignments, caregiver links, consent records, devices, pairing history, measurements, predictions, alerts + history, notes, locations, network events/counters, notifications, simulation sessions, model versions.
- **Protocol v2** (34-byte authenticated frame with the full measurement structure and relay fields), C++ header for firmware, relay step, v1 backward-compatible parsing.
- **Ingestion pipeline** shared by hardware and simulation; replay/duplicate window, plausibility and sensor-fault classification, device liveness monitor, retention.
- **Alert engine**: seven categories, lifecycle (new → acknowledged → assigned → escalated → resolved / false positive), de-duplication, automatic escalation, in-app/browser notifications, optional e-mail adapter, storm protection, patient-specific limits.
- **Machine learning**: synthetic dataset generator, shared feature engineering, training/evaluation pipeline comparing five approaches, versioned artifacts with checksums, generated `docs/MODEL_EVALUATION.md`, local inference with explanations, deploy/rollback.
- **Simulation engine**: scenarios A–G, manual events, virtual devices with real keys, raw-LoRa network model with relays; start / pause / resume / stop / reset; operating-mode switch.
- **Frontend**: overview, patients, patient profile (live charts with zoom, time ranges), alert centre, Mahdia map (Leaflet, vendored), LoRa network + digital twin, devices, AI intelligence, simulation, reports, administration, account, caregiver home; light and dark themes.
- **Reports**: patient PDF/CSV, alerts CSV, network CSV, model evaluation PDF.
- **Hardware**: real-radio patient-node firmware and relay firmware (RadioLib), SX127x register driver for the Pi, hardware gateway service with store-and-forward and recovery, `hardware/gateway.example.toml`. All **hardware pending**.
- **OMNeT++ integration**: read-only importer for `.sca` results (`tools/import_omnet_results.py`), one imported run.
- **Tests**: 126 new tests (protocol, security, pipeline, end-to-end scenarios, ML, hardware adapters) in addition to the 107 existing ones.
- **Documentation**: recovery report, risk analysis, final report, and the `docs/` set (architecture, data dictionary, protocol, security, ML, hardware, ESP32, Raspberry Pi, simulation, API, testing, deployment, troubleshooting).
- `scripts/setup.ps1`, `scripts/setup.sh`.

### Changed
- `requirements.txt`: added `cryptography`, `waitress`, explicit `werkzeug`, `joblib`.
- `.env.example`: platform variables (`RPM_*`); legacy variables kept.
- `.gitignore`: `data/*`, `ml/data/`, `.claude/`, `*.bundle`.
- Legacy documents moved to `docs/legacy/` (content unchanged).
- `tests/conftest.py`: two fixtures added for the platform tests.

### Unchanged (preserved)
- Legacy pre-MVP API and dashboard (`gateway/app.py`, `auth.py`, `database.py`, `bridge.py`, `radio.py`, `alerts.py`, `prediction.py`, `telemetry.py`, `maintenance.py`, `dashboard/`), Wokwi firmware and simulator, legacy ML scripts, and their tests.
- The OMNeT++/FLoRa project and environment in WSL (read only).

### Protocol
- New frame version 2; rationale and compatibility in `docs/PROTOCOL_SPECIFICATION.md`.

## [1.x] — before 2026-11-14
See Git history (`41c2cde` … `bbecab4`): initial import, patient-reading JSON, live simulation support, partner ESP32 alert feature.
