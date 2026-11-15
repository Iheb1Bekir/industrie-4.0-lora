# Deployment

## 1. Development / demonstration (Windows PC, simulation mode)

```powershell
cd C:\Users\Admin\Downloads\remote-patient-monitoring\remote-patient-monitoring
.\scripts\setup.ps1                       # first time only: venv, dependencies, model if missing, demo accounts
.\.venv\Scripts\python.exe -m gateway.server
# open http://127.0.0.1:8000  - demo credentials: data\demo_credentials.txt
```
On this PC the virtual environment already exists one level up; the equivalent command is
`..\.venv\Scripts\python.exe -m gateway.server`.

WSL / Linux:
```bash
scripts/setup.sh && . .venv/bin/activate
python -m gateway.manage seed-demo && python -m gateway.server
```

Development mode specifics: Flask's built-in threaded server, master key generated into `data/.master_key`, demo accounts allowed, cookie not marked `Secure` (plain HTTP on localhost).

## 2. Production-like (Raspberry Pi 5)

Full procedure: `RASPBERRY_PI_SETUP.md`. Summary of what changes with `RPM_ENV=production`:

| Setting | Effect |
|---|---|
| `RPM_MASTER_KEY` | mandatory; the server refuses to start without it |
| server | waitress (16 threads) instead of the Flask development server |
| cookies | `Secure` — the dashboard must be reached through HTTPS |
| headers | `Strict-Transport-Security` added |
| demo accounts | cannot be created; existing ones cannot sign in |

Checklist before real use:
- [ ] `RPM_ENV=production`, `RPM_MASTER_KEY`, `RPM_GATEWAY_INGEST_TOKEN` set in `.env` (mode 600)
- [ ] administrator created with `gateway.manage create-user`; two-factor authentication enabled for doctors
- [ ] HTTPS reverse proxy in front; nothing listening on the LAN in plain HTTP
- [ ] operating mode `hardware`; simulation only used deliberately
- [ ] system clock synchronised (NTP or RTC)
- [ ] nightly `backup` + `retention` scheduled; a restore has been rehearsed
- [ ] disk encryption on the Pi if it stores real patient data
- [ ] `pip-audit` run; OS updates applied
- [ ] hardware test procedure executed and recorded (`HARDWARE_SETUP.md` § 6)
- [ ] the limitations in `SECURITY.md` and `MODEL_EVALUATION.md` have been read by the responsible clinician

## 3. Environment variables

See `.env.example` (every variable with its default). All platform variables are prefixed `RPM_`.

## 4. Data locations

| Path | Content | In Git? |
|---|---|---|
| `data/rpm_system.sqlite3` | users, sessions, audit, settings | no |
| `data/rpm_hw.sqlite3` | real patients, devices, measurements, alerts | no |
| `data/rpm_sim.sqlite3` | simulation data | no |
| `data/.master_key` | development master key | no |
| `data/demo_credentials.txt` | development demo passwords | no |
| `data/gateway_spool.sqlite3` | undelivered radio frames | no |
| `ml/models/` | model versions + evaluation artifacts | yes |
| `ml/data/` | synthetic datasets (regenerable) | no |
| `hardware/gateway.toml` | your radio configuration | your choice (contains no secret) |

## 5. Backup, restore, disaster recovery

```bash
python -m gateway.manage backup <directory>     # online, consistent copies (SQLite backup API)
```
Back up together: the three database files, `.env` (contains the master key — store it separately and securely), `hardware/gateway.toml`. Restore = stop services, put the files back, start services.

Loss scenarios:
| Lost | Consequence | Recovery |
|---|---|---|
| SD card / disk | everything since the last backup | reinstall, restore backup + `.env` |
| `RPM_MASTER_KEY` only | device keys and TOTP secrets unreadable | set a new key, rotate every device key (re-provision nodes), users re-enrol TOTP |
| a patient node | – | retire the device, register and pair a new one; history stays with the patient |
| the Pi's radio module | frames lost while down (nodes do not buffer) | replace; the service re-initialises automatically |
| platform process crash | none (systemd restarts it); frames spooled by the gateway service | automatic |

Nodes do not buffer measurements while the gateway is unreachable (uplink-only protocol): radio outages create gaps, shown as gaps.

## 6. Updates

Application: `git pull` → `pip install -r requirements.txt` → restart services. Schema migrations are applied automatically and recorded in `schema_migrations`; take a backup first. Dependencies: check the scikit-learn version against the active model before upgrading it (`ML_PIPELINE.md` § 8) — an upgrade without retraining makes the model unloadable (the platform then runs without predictions and says so). Firmware: re-flash over USB (no over-the-air update exists).

## 7. Data subject requests (access, rectification, erasure)

* Access/export: patient PDF + CSV reports (Reports page), audited.
* Rectification: patient profile → Edit.
* Withdrawal of caregiver/location consent: patient profile → Caregivers / Location → Revoke.
* Erasure is not exposed in the UI (to prevent accidental loss). With the services stopped and a backup taken:
  `sqlite3 data/rpm_hw.sqlite3 "PRAGMA foreign_keys=ON; DELETE FROM patients WHERE id=<id>;"` removes the patient and, by cascade, measurements, predictions, alerts, notes, locations, consents and assignments; retire the device separately. Audit entries keep the numeric id only.
  Whether erasure is permitted or records must be retained is a legal question for the responsible institution, not decided by this software.

## 8. Publishing to GitHub

`.gitignore` excludes `data/`, `.env`, datasets, virtual environments and bundles. Before pushing, check `git status` shows no database, credential or key file. The work in this repository is currently uncommitted on `main`; see `FINAL_REPORT.md`.
