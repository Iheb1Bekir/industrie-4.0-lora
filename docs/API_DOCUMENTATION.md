# API documentation — REST API v1

Base path `/api/v1`. JSON in, JSON out. Errors: `{"error": "human message", "code": "E_..."}` with status 400 (`E_VALIDATION`, `E_BAD_JSON`), 401 (`E_AUTH`, `E_OTP_REQUIRED`), 403 (`E_FORBIDDEN`, `E_CSRF`, `E_PASSWORD_CHANGE`), 404 (`E_NOT_FOUND`), 409 (`E_CONFLICT`, `E_STATE`), 413, 423 (`E_LOCKED`), 429 (`E_RATE`), 500, 503 (`E_DISABLED`).

**Authentication**: `POST /auth/login` sets the `rpm_session` cookie and returns `csrf_token`. Send that value in the `X-CSRF-Token` header on every POST/PUT/PATCH/DELETE. All data endpoints operate on the **current operating mode** (`simulation` or `hardware`), returned as `mode`.

Permission column: `adm` = administrator doctor; D = doctor; A = assistant; C = caregiver. Patient-bound routes additionally require the patient to be in the caller's scope (else 404).

## Authentication & account
| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/auth/login` `{username, password, otp?}` | public | sign in |
| POST | `/auth/logout` | any | revoke session |
| GET | `/auth/me` | any | user, permissions, CSRF token, mode |
| POST | `/auth/password` `{current_password, new_password}` | any | change password |
| POST | `/auth/reset/complete` `{token, new_password}` | public | use a one-time reset token |
| POST | `/auth/totp/enroll`, `/auth/totp/confirm {otp}`, `/auth/totp/disable {current_password}` | D | two-factor authentication |

## Administration
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET / POST | `/users` | adm | list / create accounts (`username, password, role, full_name, is_admin?, email?, phone?`) |
| PATCH | `/users/{id}` `{full_name?, email?, phone?, is_active?, unlock?}` | adm | update, disable, unlock |
| POST | `/users/{id}/reset-token` | adm | issue a one-time reset token |
| GET | `/staff` | D, A | minimal directory for pickers |
| GET | `/system/status` | any | mode, simulation state, model summary |
| POST | `/system/mode` `{mode}` | adm | switch `simulation` ↔ `hardware` |
| GET | `/system/health` | adm | uptime, CPU/memory, databases, model, audit chain |
| GET / PUT | `/settings/thresholds` | D,A read / adm write | default alert limits |
| GET | `/audit?action=&page=&per_page=` | adm | audit trail |

## Patients
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/patients` | D, A | scoped list with latest values, state, device, prediction, location |
| POST | `/patients` `{full_name, date_of_birth?, sex?, phone?, address?, id?}` | D | register |
| GET / PATCH | `/patients/{id}` | D,A / D | profile (audited) / update |
| PUT | `/patients/{id}/thresholds` | D | patient-specific limits |
| GET | `/patients/{id}/measurements?range=15m|1h|24h|7d|30d` or `?from=&to=` | D, A | time series (averaged in buckets above 720 points: `aggregated`, `bucket_s`) |
| GET | `/patients/{id}/predictions?range=` | D, A | prediction history with explanations |
| GET / POST | `/patients/{id}/notes` `{kind: clinical|observation, body}` | clinical: D; observation: D, A | notes |
| POST / DELETE | `/patients/{id}/staff` `{user_id}` · `/patients/{id}/staff/{user_id}` | D | care-team assignment |
| POST | `/patients/{id}/caregivers` `{user_id, consent_given_by, relationship?, can_view_vitals?, can_view_location?, notify?, expires_at?}` | D | record consent + authorize caregiver |
| DELETE | `/patients/{id}/caregivers/{link_id}` | D | revoke |
| POST | `/patients/{id}/location` `{lat, lon, accuracy_m?, consent_given_by}` | D | manual, consented location |
| DELETE | `/patients/{id}/location-consent` | D | revoke location consent |

## Devices
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/devices` | D, A | devices in scope with link statistics |
| POST | `/devices` `{serial, label?, hw_model?, radio?, patient_id?}` | D | register; response contains `provisioning.device_key_hex` **once** |
| POST | `/devices/{id}/pair` `{patient_id}` · `/disable` · `/enable` · `/replace` · `/rotate-key` | D | lifecycle |

## Alerts & notifications
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/alerts?status=open|closed|all|<status>&category=&severity=&type=&patient_id=&page=&per_page=` | D, A | list |
| GET | `/alerts/{id}` | D, A | detail with history, triggering measurement/prediction |
| POST | `/alerts/{id}/action` `{action, note?, assignee?}` | `acknowledge`, `escalate`: D, A · `assign`, `resolve`, `false_positive`: D | lifecycle |
| GET · POST | `/notifications` · `/notifications/read` | any | in-app notifications |

## Monitoring, network, intelligence
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/overview` | D, A | KPIs computed from the database, patients, open alerts |
| GET | `/network` | D, A | topology, counters, per-device statistics, events (`kind`: measured / simulated) |
| GET | `/network/research` | D, A | imported OMNeT++/FLoRa result summaries |
| GET | `/ml/model` | D | runtime status, versions, `metadata`, `metrics`, `curves` (served from the saved artifacts) |
| GET | `/ml/predictions` | D, A | recent predictions and distribution |
| POST | `/ml/deploy` `{version}` or `{rollback: true}` | adm | activate / roll back a model version |

## Simulation
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/simulation` | D, A (reduced for non-admins) | engine state |
| POST | `/simulation/start` `{scenario A–G, patient_count 1–20, speed 1–60, interval_s 5–300, relay_count 1–3, base_loss?, duplicate_rate?, delay_rate?, seed?}` | adm | reset simulation data and start |
| POST | `/simulation/pause` · `/resume` · `/stop` · `/reset` | adm | control |
| POST | `/simulation/event` `{patient_id, event}` | adm | `deterioration, spo2_decline, hr_rise, fever, fall, sensor_fault, disconnect, reconnect, packet_loss, recover, predictive_trend` |

## Reports
| Method | Path | Who |
|---|---|---|
| GET | `/reports/patient/{id}.csv|.pdf?range=` | D |
| GET | `/reports/alerts.csv?range=` · `/reports/network.csv` · `/reports/model.pdf` | D |

## Caregiver
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/caregiver/patients` | C | reduced status of consented patients |
| GET | `/caregiver/patients/{id}/history` | C | hourly averages, last 24 h |

## Real-time stream
`GET /stream` (Server-Sent Events, authenticated). Event names: `hello`, `measurement`, `prediction`, `alert`, `alert_update`, `device`, `network`, `location`, `simulation`, `system`, `notification`. Each `data:` line is `{"type", "ns", "patient_id", "data"}`. Events are filtered per user on the server.

## Hardware gateway ingestion
`POST /ingest/frame` — header `Authorization: Bearer <RPM_GATEWAY_INGEST_TOKEN>`, body `{"frame_hex": "<68 hex chars>", "rssi": -97.5, "snr": 8.2}`. Response `{"outcome": "stored|heartbeat|duplicate|replay|auth_fail|unknown_device|rejected|crc_error|malformed", "detail", "alerts"}`. Always writes to the hardware database. Returns 503 when the token is not configured.

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/ingest/frame \
  -H "Authorization: Bearer $RPM_GATEWAY_INGEST_TOKEN" -H "Content-Type: application/json" \
  -d '{"frame_hex":"<hex>","rssi":-97.5,"snr":8.2}'
```

## Legacy API (unchanged, separate process)
`python -m gateway.app` still serves the pre-MVP endpoints (`/api/vitals`, `/api/patients`, …) documented in the root README, section "Legacy pre-MVP API".
