# Missing features and risk analysis

Engineering gap analysis performed against the repository, the recovered measurement structure, the LoRa/relay architecture, the OMNeT++ model, and general requirements of real-time, embedded, ML and health-data systems. Each item: why it matters → decision → status. Status vocabulary: **Done** (implemented + automated test), **Done (untested on hardware)**, **Documented** (procedure/limit written, no code needed or possible now), **Open**.

## Critical

| # | Gap | Why it matters | Depends on | Decision / status |
|---|---|---|---|---|
| C1 | Anyone could inject data for any patient (legacy packet had no device identity or authentication) | false vitals or suppressed alarms | per-device keys | **Done** — protocol v2 HMAC tag, registered + active + paired device required, tests for wrong key / tampering |
| C2 | Replayed radio captures | old "normal" frames could mask deterioration | persisted sequence number | **Done** — 32-bit seqNo persisted in NVS, 62-frame window on the gateway |
| C3 | Missing data shown as normal | silent failure of monitoring | – | **Done** — NULL values, `quality`, `stale`, `offline`, `no_data` states; gaps drawn as gaps; tests |
| C4 | Device presented as connected because a record exists | false confidence | liveness timeout | **Done** — online only by valid frames within the timeout; monitor task; offline alert |
| C5 | Simulated data mixing with real patient data | wrong clinical picture | separate stores | **Done** — separate database files, credential-bound namespaces, virtual-device guard, tests |
| C6 | No access control (one shared token) | exposure of health data | accounts | **Done** — three roles, patient scoping, consent-bound caregiver access, audit |
| C7 | Radio frames are readable in clear | confidentiality of vitals (numeric id only) | AEAD in firmware, new frame version | **Open** — authenticated but not encrypted; documented in `PROTOCOL_SPECIFICATION.md` and `SECURITY.md`. Next step: AES-CCM payload with the existing key |
| C8 | No TLS in the application | credentials and data in clear on a LAN | reverse proxy | **Documented** — bind to localhost, Caddy/nginx recipe; `Secure` cookies in production |
| C9 | Nothing validated on real hardware | every radio/sensor claim | the hardware | **Open** — firmware, driver and Pi procedure are HARDWARE PENDING; test plan written |
| C10 | Model trained on synthetic data only | predictions may be wrong on real patients; false reassurance or alarm fatigue | real, consented data | **Documented** — labelled everywhere as decision support, never suppresses threshold alerts, false-alarm rate published |

## High

| # | Gap | Why it matters | Decision / status |
|---|---|---|---|
| H1 | Duplicate alerts / notification storms | alarm fatigue, missed real alerts | **Done** — one open alert per (patient, type), trigger counter, per-user rate limit with recorded suppression |
| H2 | Unacknowledged critical alerts | nobody reacts | **Done** — automatic escalation after `RPM_ESCALATE_AFTER_S`, notification to staff |
| H3 | Gateway/API restart loses frames | data gaps | **Done** — durable spool in the gateway service, ordered replay; test |
| H4 | Radio module hang | silent loss of all patients | **Done (untested on hardware)** — health probe every 30 s, re-initialisation with back-off; device-offline alerts as second line |
| H5 | Clock synchronisation | wrong timestamps, wrong trends | **Done / Documented** — gateway time is authoritative unless the device claims sync and is within ±300 s; Pi NTP/RTC procedure. Nodes have no RTC (limitation) |
| H6 | Out-of-order and delayed frames | corrupted history, false loss counts | **Done** — accepted once inside the window, loss estimate corrected; test |
| H7 | Sensor disconnection vs abnormal physiology | false clinical alarms | **Done** — fault flags, plausibility limits, separate `sensor` / `data_quality` alert categories |
| H8 | Device replacement / patient reassignment | history attached to the wrong person | **Done** — one active device per patient, retire/replace flow, pairing history; test |
| H9 | Consent expiry and revocation | unlawful access | **Done** — expiry and revocation checked on every request and event; tests |
| H10 | Audit integrity | undetectable tampering | **Done** — hash chain + `verify-audit`; test. Not write-once storage (an administrator with file access can rewrite the whole chain) |
| H11 | Model artifact integrity / wrong model loaded | silent wrong predictions | **Done** — SHA-256 + feature-definition check, failed activation keeps the previous model, rollback |
| H12 | Model failure blocks monitoring | loss of alerts | **Done** — `model_unavailable` path, threshold alerts independent; test |
| H13 | Key loss on the server | all devices unusable | **Documented** — master-key backup procedure, re-provisioning path |
| H14 | ESP32 key extraction from flash | device impersonation | **Open** — enable flash encryption + secure boot (documented, not configured) |
| H15 | No downlink acknowledgement | node cannot know a frame was lost; no buffering during outages | **Open** — uplink-only like the OMNeT++ model; event frames are repeated. ACK + node-side buffer would need a receive window in the firmware and a transmit path in the Pi driver |
| H16 | Backup / restore | data loss | **Done** — `manage backup` (online, consistent), restore procedure; not automated by default (cron example) |

## Medium

| # | Gap | Decision / status |
|---|---|---|
| M1 | Packet collisions / congestion with many nodes on one channel | **Documented** — listen-before-talk + random back-off in firmware (untested); OMNeT++ model is the tool to size this; single channel is the scaling limit |
| M2 | Duty-cycle / regulatory compliance | **Documented** — ≈ 0.27 % at 30 s; frequency and power must be set explicitly by the operator; no enforcement counter in firmware (**Open**) |
| M3 | Battery monitoring | **Done (untested)** — optional ADC divider, otherwise reported as "not supported"; no low-battery alert yet (**Open**, trivial once hardware exists) |
| M4 | Sensor calibration | **Open** — no calibration offsets; accuracy targets remain unmeasured (`docs/legacy/validation_plan.md`) |
| M5 | Fall-detection quality | **Open** — prototype thresholds; doctors can mark false positives, which is the data needed to tune it |
| M6 | Prediction calibration and confidence | **Done** — isotonic calibration, ECE/Brier reported; UI shows category + raw score, calibrated value labelled an estimate |
| M7 | False-positive management for predictions | **Done** — `false_positive` alert state (doctor), counted in history; no automatic feedback into training (**Open**, deliberate) |
| M8 | Model drift / retraining | **Documented** — manual, versioned retraining; no drift statistic on live data yet (**Open**) |
| M9 | Data retention | **Done** — configurable retention command; alerts/audit kept |
| M10 | Timezone consistency | **Done** — UTC stored, browser-local display with the zone shown |
| M11 | Notification delivery failures | **Done** for in-app (status recorded); e-mail adapter records `failed` but was never delivery-tested; SMS adapter does not exist (**Open**) |
| M12 | Offline operation | **Done** — no cloud dependency; only map tiles need internet (markers still shown) |
| M13 | Software / dependency updates | **Documented** — update procedure, scikit-learn pinning rule; no automated vulnerability scan (**Open**) |
| M14 | System monitoring | **Done** — System health page; no external watchdog/alerting on the Pi itself (**Open**) |
| M15 | Location privacy | **Done** — consent-bound, age and accuracy shown, no fabricated tracking; tile requests reveal the viewed area to the tile provider (documented) |
| M16 | Session theft | **Done** — HttpOnly/SameSite cookies, UA binding, idle/absolute expiry |
| M17 | Erasure / anonymisation | **Documented** — manual SQL procedure; no UI |

## Low

| # | Gap | Decision / status |
|---|---|---|
| L1 | Over-the-air firmware update | **Open** — USB only |
| L2 | Multiple gateways / roaming | **Open** — `destinationId` exists in the frame; one gateway supported |
| L3 | Dynamic relay routing | **Open** — static next-hop as in the OMNeT++ model |
| L4 | Automated browser tests | **Open** — API-level end-to-end tests + manual UI check |
| L5 | Internationalisation (French/Arabic UI) | **Open** — UI in English |
| L6 | PDF charts in reports | **Open** — reports are textual |
| L7 | GPS adapter | **Open** — store supports `source = gps`; no hardware |
| L8 | Break-glass access / four-eyes rule for administrators | **Open** |
| L9 | CI pipeline on GitHub | **Open** — tests run locally (`gh` not installed, nothing pushed) |

## Things deliberately not added

* A neural network for prediction (no evidence of benefit on this data; heavier runtime).
* LoRaWAN (the architecture is a custom relay protocol by design).
* A message broker / microservices (one gateway, tens of devices).
* A JavaScript framework and build chain (no Node.js on the development PC; nothing to gain at this size).
* Automatic clinical actions from predictions (human in the loop).

## Top residual risks to state in any demonstration

1. No physical validation yet: radio range, sensor accuracy, fall detection, Pi performance are unknown.
2. The prediction model is a synthetic-data prototype with roughly seven false-alarm episodes per simulated patient-day at 95 % episode recall.
3. Radio payloads are not encrypted and HTTPS depends on the deployment.
4. Not a medical device; thresholds are engineering values; no regulatory assessment.
