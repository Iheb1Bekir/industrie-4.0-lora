# Security and privacy

This project handles health-type data. It is a **research prototype**: no legal, regulatory or clinical certification is claimed (GDPR, Tunisian law n° 2004-63 on personal data, HIPAA, medical-device regulations have **not** been assessed by qualified professionals). The controls below are implemented and tested; the "Not covered" section lists what is not.

## Implemented controls (with test evidence in `tests/test_v2_security.py`, `tests/test_v2_pipeline.py`)

| Area | Control |
|---|---|
| Passwords | scrypt with per-password salt (werkzeug); minimum 12 characters and 3 character classes; never logged, returned or stored in clear |
| Brute force | per-IP login rate limit (10/min); per-account progressive lockout after 5 failures (30 s, 60 s, … max 15 min); identical response for unknown user and wrong password, with dummy hash verification |
| Sessions | 256-bit random token, `HttpOnly` + `SameSite=Strict` cookie (`Secure` in production); only its SHA-256 is stored; 30 min idle and 12 h absolute expiry; bound to the User-Agent (mismatch revokes the session); password change revokes other sessions |
| CSRF | per-session token required in `X-CSRF-Token` on every state-changing request, in addition to SameSite |
| MFA | optional TOTP (RFC 6238) for doctor accounts; secret stored AES-GCM wrapped |
| Password reset | administrator-issued one-time token (15 min), hashed at rest; no e-mail dependency |
| Authorization | explicit permission matrix (`security.PERMISSIONS`), evaluated on the server for every request from the database record; nothing role-related sent by the browser is used |
| Patient scope / IDOR | every patient-bound route resolves the caller's visible patient set (primary doctor, staff assignment, active caregiver consent); out-of-scope ids return 404 and are audited |
| Caregivers | separate endpoints returning a reduced object; access exists only while a consent record is active (expiry and revocation are immediate); no clinical notes, predictions, thresholds, identifiers or other patients |
| Input validation | type/range validation on every field; 64 kB request limit; structured errors without stack traces |
| SQL injection | parameterized statements only |
| XSS | API returns JSON only; the UI escapes every interpolated value; strict Content-Security-Policy (`script-src 'self'`, no inline script), `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`; CSV exports neutralise spreadsheet formulas |
| CORS | none: the API is same-origin only (no `Access-Control-Allow-Origin` is ever sent) |
| Secrets | none in source code; `RPM_MASTER_KEY` and `RPM_GATEWAY_INGEST_TOKEN` come from the environment; `.env`, `data/` are git-ignored; development key is generated locally |
| Encryption at rest | device keys and TOTP secrets: AES-256-GCM under the master key, bound to the device id. The SQLite files themselves are **not** encrypted (see below) |
| Radio | per-device 256-bit key, HMAC-SHA256 tag, replay window, device must be registered + active + paired; see `PROTOCOL_SPECIFICATION.md` |
| Hardware ingestion | separate bearer token, constant-time comparison, writes only to the hardware database; disabled when the token is not configured |
| Simulation isolation | separate database file; virtual devices cannot exist in the hardware database |
| Audit | hash-chained append-only log: logins (success/failure), permission failures, patient record access and changes, device registration/changes, caregiver grants/revocations, alert actions, model deployment, exports, mode and settings changes. No passwords, tokens or measurement values. `python -m gateway.manage verify-audit` detects modification |
| Model artifact | SHA-256 of the artifact checked against its metadata before loading; only versions inside `ml/models` can be activated |
| Demo accounts | created only by `manage seed-demo`, refused when `RPM_ENV=production`; random passwords written to a git-ignored file |

## OWASP ASVS 4.0 self-assessment (level 1 scope, informal)

| Chapter | Status | Notes |
|---|---|---|
| V2 Authentication | Mostly met | no breached-password list check; MFA optional rather than enforced for administrators |
| V3 Session management | Met | |
| V4 Access control | Met | deny by default, server-side, tested per role |
| V5 Validation / encoding | Met | |
| V6 Cryptography | Met for what is used | standard primitives only (scrypt, HMAC-SHA256, AES-GCM); no custom algorithm |
| V7 Errors / logging | Met | audit chain; application logs go to stdout/journald |
| V8 Data protection | **Partly** | database files not encrypted; backups not encrypted by the tool |
| V9 Communications | **Deployment-dependent** | the application speaks HTTP; TLS must be terminated by a reverse proxy (see `DEPLOYMENT.md`) |
| V10 Malicious code / V14 Config | Partly | dependencies pinned by minimum version only; no automated dependency audit in CI |
| V13 API | Met | |

This is a developer self-assessment, not an audit.

## Not covered / known limitations (do not deploy with real patients before addressing)

1. **Transport encryption** is not provided by the application. Without an HTTPS reverse proxy, cookies and data cross the LAN in clear. Keep `RPM_HOST=127.0.0.1` unless TLS is in front.
2. **LoRa frames are authenticated but not encrypted.** Vital signs linked to a numeric id are readable by anyone in range.
3. **Databases are not encrypted at rest.** Use full-disk encryption on the Pi (LUKS) and protect backups.
4. **ESP32 key storage**: the device key sits in NVS; enable flash encryption + secure boot on production modules.
5. The **gateway ingest token** is a single shared secret between two local processes; rotate it by changing the environment variable on both.
6. **Map tiles** are requested from `tile.openstreetmap.org`: the map view reveals the viewed area (not patient data) to that provider. Host tiles locally for a closed network.
7. No automated **dependency vulnerability scanning**; run `pip-audit` manually (see `TESTING.md`). It was not run in this work because the tool is not installed.
8. **E-mail** notifications (optional) contain the alert text; do not enable them over untrusted mail relays. **SMS**: no provider adapter exists.
9. Administrators can see all patients. There is no "break-glass" workflow or four-eyes rule.
10. Rate limiting is in-memory per process (resets on restart; fine for the single-process deployment).
11. Deleting a patient is not exposed in the UI; anonymisation/erasure procedure: `DEPLOYMENT.md` § Data subject requests.

## Privacy by design choices

* Radio frames carry a numeric patient id only — never a name.
* Caregiver notifications use generic wording without measurement values.
* Real locations require a recorded consent; revoking it hides the location immediately. Simulated coordinates are labelled as fictional.
* Development and tests use synthetic data only; no real patient data is in the repository, fixtures, logs or screenshots.

## Reporting a vulnerability

Open a private security advisory on the GitHub repository (Security → Advisories) rather than a public issue.
