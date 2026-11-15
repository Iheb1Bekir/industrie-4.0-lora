# Architecture

Research prototype. Not a medical device. See `SECURITY.md` and `MODEL_EVALUATION.md` for limits.

## 1. System overview

```mermaid
flowchart LR
  subgraph Field["Patients (raw LoRa, custom application-level relay - NOT LoRaWAN)"]
    N1[ESP32 patient node 1] & N2[ESP32 patient node 2] & N3[ESP32 patient node 3]
    R[(optional relay nodes\nvalidate · dedup · hop limit · forward)]
  end
  subgraph Pi["Raspberry Pi 5 - doctor gateway & local intelligence"]
    HW[hw_gateway service\nSX127x driver · spool · recovery]
    subgraph Platform["platform process (gateway.server)"]
      ING[Ingestion pipeline\nCRC · device auth (HMAC) · replay window · plausibility]
      INF[Local inference\nfeatures → model → explanation]
      ALR[Alert engine\nlifecycle · dedup · escalation · notifications]
      SIM[Simulation engine\nvirtual devices · network model]
      API[REST API v1 + SSE stream]
      DBH[(rpm_hw.sqlite3\nREAL data)]
      DBS[(rpm_sim.sqlite3\nSYNTHETIC data)]
      DBY[(rpm_system.sqlite3\nusers · sessions · audit)]
    end
  end
  N1 & N2 -- direct --> HW
  N3 -- via relay --> R --> HW
  HW -- "POST /api/v1/ingest/frame (gateway token)" --> ING
  SIM -- "same handle_frame() call" --> ING
  ING --> INF --> ALR
  ING --> DBH & DBS
  API --> UI[Web application\ndoctor · assistant · caregiver]
  ALR --> API
```

Two processes run on the Pi: the **platform** (web/API/inference/alerts) and the **hardware gateway service** (the only code that touches SPI/GPIO). The browser never talks to hardware.

## 2. Two configurations, strictly separated

| | Physical configuration | Research / simulation configuration |
|---|---|---|
| Devices | 3 ESP32 patient nodes, Raspberry Pi 5 gateway (relays optional) | 1–20 virtual patients, 1–3 relays, 1 gateway (default research topology 20 / 3 / 1) |
| Data source | radio frames through `hw_gateway` | `gateway/simulator.py` (and, offline, OMNeT++/FLoRa results imported as read-only summaries) |
| Database | `data/rpm_hw.sqlite3` | `data/rpm_sim.sqlite3` |
| Device records | `is_virtual = 0`, ids from 101 | `is_virtual = 1`, ids from 60001 |
| Statistics label | "measured" | "simulated" |

Isolation rules enforced in code (and tested):
* the namespace is chosen by the **credential** of the data source — the gateway token always writes to *hardware*, the simulator always to *simulation* — never by a field in the payload or by the UI mode;
* a virtual device cannot exist in the hardware database and vice versa; the pipeline rejects a frame whose device type does not match the namespace;
* every simulated measurement/alert/prediction carries `sim_session_id`; simulated patients have `is_synthetic = 1`;
* stopping or resetting the simulation only ever touches the simulation database;
* the UI always shows a `SIMULATION MODE` / `HARDWARE MODE` bar; switching to hardware stops the simulation engine.

## 3. Component map

| Module | Responsibility |
|---|---|
| `gateway/settings.py` | configuration from environment, master key handling |
| `gateway/store.py` | three SQLite databases, versioned migrations |
| `gateway/protocol.py` | protocol v2 frame (encode / decode / relay step), v1 compatibility |
| `gateway/security.py` | scrypt passwords, sessions, CSRF, RBAC matrix, TOTP, AES-GCM wrapping, hash-chained audit |
| `gateway/services.py` | service container, patient/device registration and pairing, access scoping |
| `gateway/ingest.py` | the single ingestion pipeline, device liveness monitor, retention |
| `gateway/alert_engine.py` | alert classification, lifecycle, de-duplication, escalation, notification adapters |
| `gateway/features.py` | feature engineering shared by training and inference |
| `gateway/inference.py` | model registry on disk, integrity check, local inference, explanation, latency |
| `gateway/simulator.py` | scenarios A–G, physiology model, raw-LoRa network model with relays |
| `gateway/events.py` | in-process pub/sub feeding Server-Sent Events |
| `gateway/api_v1.py` | REST API v1, per-role views, SSE stream, hardware ingestion endpoint |
| `gateway/reports.py` | CSV and PDF generation |
| `gateway/server.py` | Flask application factory, security headers, background monitor |
| `gateway/manage.py` | administration CLI (users, mode, backup, retention, audit verification) |
| `gateway/radio_sx127x.py` | SX127x register driver (Pi) |
| `gateway/hw_gateway.py` | hardware gateway service: receive → forward, store-and-forward, recovery |
| `ml/` | dataset generator, training/evaluation pipeline, versioned models |
| `web/` | browser application (ES modules, no build step, Leaflet vendored) |
| `firmware/` | ESP32 patient node and relay node for real radios (RadioLib) |
| `wokwi/` | unchanged Wokwi simulation firmware (protocol v1 over serial) |
| `simulation/omnetpp/imported_results/` | read-only summaries of OMNeT++/FLoRa runs (`tools/import_omnet_results.py`) |

## 4. Measurement path (identical for real and simulated frames)

1. structure + CRC-16 → `malformed` / `crc_error`
2. `sourceId` must be a registered device of the right kind → `unknown_device`
3. device must be `active` and paired → `rejected`
4. HMAC tag verified with that device's key → `auth_fail` (3 in a minute raise a network alert)
5. `destinationId` = this gateway, `patientId` = the paired patient, `hopCount ≤ min(maxHopCount, gateway limit)` → `rejected`
6. replay / duplicate window per device (62 sequence numbers) → `duplicate` / `replay`; loss estimated from gaps; late frames accepted once
7. timestamp: device clock only if it claims synchronisation **and** is within ±300 s of the gateway, otherwise gateway time (UTC)
8. plausibility: values outside hard physical limits are stored as *missing* with quality `implausible`; sensor-fault flags give quality `partial` / `sensor_fault`
9. store, update device liveness and link statistics, publish live event
10. immediate alerts (threshold, fall, sensor, data quality) with patient-specific limits
11. local inference on the last 15 minutes → prediction stored (also when *not* computable) → predictive alert if high risk and no threshold condition is present

Missing or invalid values are never turned into normal readings; "no data" and "device offline" are states of their own everywhere (API, UI, reports).

## 5. Real-time

Server-Sent Events (`GET /api/v1/stream`): one long-lived HTTP response per browser. Every event passes through a per-user filter built from the server-side role and patient scope; caregivers receive reduced copies. No page polling for live data; the client reconnects automatically.

## 6. Technology choices and why

* **Flask + SQLite kept** (existing, working, right-sized for one gateway and tens of patients; WAL mode; no server to administer on the Pi).
* **No frontend build chain**: Node.js is not installed on the development PC and a build step would be one more thing to maintain on the Pi. The UI is plain ES modules with a small in-house chart component; Leaflet 1.9.4 is vendored so the application works without a CDN (map *tiles* still need internet).
* **scikit-learn model** instead of the planned LSTM: measurable, explainable, 5 ms inference, no TensorFlow on the Pi.
* **Separate hardware service**: radio faults or SPI permissions can never take the web application down, and vice versa (frames are spooled).

## 7. Legacy compatibility

`gateway/app.py`, `auth.py`, `database.py`, `bridge.py`, `radio.py`, `alerts.py`, `prediction.py`, `telemetry.py`, the old dashboard and their 107 tests are unchanged and still pass. They are **not mounted** in the new server (their shared-token trust model is weaker). The 16-byte v1 packet can still enter the platform through the gateway endpoint when `RPM_ALLOW_LEGACY_V1=1` (stored as `data_source = legacy_v1`, unauthenticated, migration aid only).

## 8. Scalability notes

Measured on the development PC: ~100 ms per ingested frame including inference and all bookkeeping, i.e. far above the offered load of 20 nodes × 1 frame / 30 s. The limiting factors beyond a few hundred nodes would be the single LoRa channel (collisions, duty cycle) long before the software; scaling up means more gateways/channels and moving the clinical databases to a server DBMS — the store layer is the only module that would change.
