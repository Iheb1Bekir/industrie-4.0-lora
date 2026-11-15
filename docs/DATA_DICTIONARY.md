# Data dictionary

Schema source of truth: `gateway/store.py` (ordered migrations; applied version in table `schema_migrations`). All timestamps are **UTC epoch seconds** (REAL); the browser converts to the local time zone.

## Measurement structure (wire ↔ database ↔ API)

| Structure field (wire, camelCase) | DB column `measurements.` | Type | Meaning |
|---|---|---|---|
| `patientId` | `patient_id` | int 1..65535 | patient the device is paired with |
| `seqNo` | `seq_no` | int ≥ 1 | per-device sequence number |
| `timestamp` | `device_ts` | int | raw device clock value |
| – | `ts` | real | measurement time used everywhere: device time if synchronised and plausible, else gateway reception time |
| – | `received_at` | real | gateway reception time |
| `heartRate` | `heart_rate` | real / NULL | bpm; NULL = not available (sensor fault or implausible) |
| `spO2` | `spo2` | real / NULL | % |
| `temperature` | `temperature` | real / NULL | °C |
| `fallDetected` | `fall_detected` | 0/1 | fall flag of this frame |
| `alertLevel` | `alert_level` | 0..3 | device-side classification: 0 normal, 1 warning, 2 critical, 3 fall |
| `routingMode` | `routing_mode` | 0/1 | 0 direct, 1 relay-assisted (set by the source) |
| `sourceId` | `source_id`, `device_id` | int | originating device |
| `destinationId` | `destination_id` | int | gateway id |
| `hopCount` | `hop_count` | 0..15 | relays traversed |
| `maxHopCount` | `max_hop_count` | 1..15 | hop limit set by the source |
| `payloadType` | `payload_type` | 1..3 | MEASUREMENT / HEARTBEAT / ALERT |
| `critical` | `critical` | 0/1 | device considered the situation critical |
| (flags) | `flags` | int | raw flag byte |
| (battery) | `battery` | int / NULL | %, NULL = not supported |
| – | `rssi`, `snr` | real / NULL | reported by the receiving radio (simulated values in simulation) |
| – | `quality` | text | `ok`, `partial` (one sensor missing), `sensor_fault` (no usable vital), `implausible` (value outside hard limits, discarded) |
| – | `data_source` | text | `hardware`, `simulation`, `legacy_v1` |
| – | `sim_session_id` | int / NULL | set on every simulated record |
| – | `key_epoch` | int | device key version at reception; `(device_id, seq_no, key_epoch)` is unique |

Hard plausibility limits (outside ⇒ sensor problem, not physiology): heart rate 20–250 bpm, SpO2 50–100 %, temperature 25–45 °C.

The optional `patientState` of earlier notes is not stored: it is derived (`state` in the API) from alerts, device liveness and data age — `normal`, `warning`, `critical`, `prediction`, `offline`, `stale`, `no_data`, `no_device`.

## Clinical databases (`rpm_hw.sqlite3`, `rpm_sim.sqlite3` — identical schema)

| Table | Purpose | Key columns |
|---|---|---|
| `patients` | profile | `id` (numeric LoRa id), `code` (`P001`), `full_name`, `date_of_birth`, `sex`, `phone`, `address`, `primary_doctor_id`, `status`, `thresholds` (JSON overrides), `is_synthetic`, `sim_session_id` |
| `staff_assignments` | doctor/assistant ↔ patient | `patient_id`, `user_id`, `role` |
| `consent_records` | recorded consent | `kind` (`caregiver_access`, `location_sharing`), `granted_by_name`, `recorded_by`, `granted_at`, `expires_at`, `revoked_at` |
| `caregiver_links` | caregiver ↔ patient, bound to a consent | `can_view_vitals`, `can_view_location`, `notify`, `expires_at`, `revoked_at` |
| `devices` | device identity and link state | `id` (= `sourceId`), `serial`, `key_enc` (AES-GCM wrapped), `key_version`, `status` (`provisioned`, `active`, `disabled`, `replaced`), `patient_id`, `is_virtual`, `online`, `last_seen_at`, `last_seq`, `replay_window`, link counters, `last_rssi/snr/battery/hop_count` |
| `device_assignments` | pairing history | `device_id`, `patient_id`, `assigned_at`, `unassigned_at` |
| `measurements` | see above | index `(patient_id, ts)` |
| `predictions` | one row per inference attempt | `status` (`ok`, `insufficient_data`, `model_unavailable`, `inference_error`), `score`, `probability` (calibrated estimate), `threshold`, `risk_category` (`low`, `medium`, `high`, `unknown`), `explanation` (JSON), `supporting` (JSON), `model_name`, `model_version`, `latency_ms` |
| `alerts` | alert with lifecycle | `type`, `category`, `severity`, `status`, `measurement_id`, `prediction_id`, `trigger_count`, `assigned_to`, acknowledge/escalate/resolve timestamps, `note` |
| `alert_events` | alert history | `action`, `from_status`, `to_status`, `user_id`, `note` |
| `clinical_notes` | notes | `kind` (`clinical` doctor-only, `observation`) |
| `locations` | last known positions | `lat`, `lon`, `accuracy_m`, `source` (`simulated`, `manual`, `gps`), `consent_id` |
| `network_events` | per-frame outcomes (ring, last 5000) | `kind`, `device_id`, `seq_no`, `hop_count`, `rssi`, `snr`, `latency_ms`, `detail` |
| `network_counters` | totals | `frames_received`, `valid`, `direct`, `relay_assisted`, `duplicates`, `replays`, `lost_estimate`, `crc_errors`, `malformed`, `auth_failures`, `unknown_device`, `rejected`, `out_of_order`, `offline_events` |
| `notifications` | notification history | `channel` (`in_app`, `email`), `status` (`sent`, `suppressed`, `failed`), `read_at` |
| `sim_sessions` | simulation runs | `scenario`, `config`, `started_at`, `stopped_at` |

Referential integrity: foreign keys are enforced (`PRAGMA foreign_keys=ON`); references to users live in another database file and are enforced in code.

## System database (`rpm_system.sqlite3`)

| Table | Purpose |
|---|---|
| `users` | accounts: `role` (`doctor`, `assistant`, `caregiver`), `is_admin` (doctors only), `password_hash` (scrypt), lockout counters, TOTP secret (wrapped), `is_demo`, `must_change_password` |
| `sessions` | server-side sessions (SHA-256 of the token, CSRF token, idle/absolute expiry, user-agent hash) |
| `password_resets` | one-time reset tokens (hash, expiry, used) |
| `audit_log` | append-only, hash-chained audit trail |
| `settings` | `operating_mode`, default `thresholds` |
| `model_versions` | deployment history of model versions |

## Alert types

| Type | Category | Default severity | Trigger |
|---|---|---|---|
| `HIGH_HR` / `LOW_HR` | threshold | high (critical above limit + 20) | heart rate beyond the configured limit |
| `LOW_SPO2` | threshold | high (critical below limit − 4) | SpO2 below the limit |
| `HIGH_TEMP` / `LOW_TEMP` | threshold | warning (high at limit + 1.5) | temperature beyond the limit |
| `FALL` | fall | critical | fall flag |
| `PREDICTED_DETERIORATION` | predictive | warning | model risk category high while no threshold condition is present |
| `DEVICE_OFFLINE` | device | high | no valid frame within the timeout (auto-resolved on return) |
| `SENSOR_FAULT` | sensor | warning | device fault flags |
| `IMPLAUSIBLE_VALUE` | data_quality | warning | value outside hard physical limits |
| `NETWORK_DEGRADED` | network | warning | ≥ 30 % of the last frames of a device lost |
| `AUTH_FAILURES` | network | high | ≥ 3 frames failing authentication for one device id in a minute |

Default limits (configurable globally and per patient; engineering demonstration values, not medical rules): HR > 120, HR < 40, SpO2 < 92, temperature ≥ 38.0, temperature < 35.0.

## Retention

`python -m gateway.manage retention` deletes measurements, predictions and network events older than `RPM_RETENTION_DAYS` (default 30). Alerts, notes, consent records and the audit trail are kept.
