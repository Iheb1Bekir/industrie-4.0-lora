# Troubleshooting

## Platform

| Symptom | Cause | Fix |
|---|---|---|
| `RuntimeError: RPM_MASTER_KEY must be set in production` | production mode without a key | `python -m gateway.manage gen-key`, put the value in `.env` |
| `RPM_MASTER_KEY must decode to exactly 32 bytes` | truncated / edited key | generate a new one (then re-provision devices if keys were already stored) |
| Log: `No user account exists` | fresh install | `python -m gateway.manage create-user --role doctor --admin --username …` (development: `seed-demo`) |
| Login says "account temporarily locked" | 5+ wrong passwords | wait the indicated time, or an administrator uses **Unlock** (Administration → Users) |
| Login works on `localhost` but not through the network name | `RPM_ENV=production` sets `Secure` cookies; you are on plain HTTP | use the HTTPS reverse proxy (`RASPBERRY_PI_SETUP.md` § 6) |
| Every action returns `E_CSRF` | page kept open across a server restart / new login in another tab | reload the page |
| `E_PASSWORD_CHANGE` on every request | new or reset account | change the password (Account & security) |
| Dashboard shows "Reconnecting…" permanently behind a proxy | proxy buffers Server-Sent Events | disable buffering (`flush_interval -1` in Caddy, `proxy_buffering off` in nginx) |
| AI page: "No prediction model is deployed" | `ml/models/active.json` missing, checksum mismatch, or different feature version | `python ml/train.py`, or copy a complete version folder and activate it. Monitoring and threshold alerts keep working meanwhile |
| AI page warns the library version differs / model fails to load after an upgrade | scikit-learn differs from the training version | install the version in `metadata.json → dependencies`, or retrain |
| Predictions all "insufficient data" | fewer than 6 valid HR+SpO2 samples in the last 10 minutes (startup, sensor fault, long gaps) | wait; check the sensor |
| Simulation "Start" answers 409 | platform is in hardware mode, or a simulation is already running | switch to simulation mode / stop first |
| Map shows markers on a grey background | no internet access for OpenStreetMap tiles | expected offline; markers are still correct |
| Map shows no marker in hardware mode | no location registered with consent | patient profile → Location → Register location manually |
| `database is locked` in logs | another process holds a long write (e.g. manual `sqlite3` session) | close it; the application waits up to 15 s |
| Tests: C++ tests skipped | `g++` not on PATH | install MSYS2/MinGW or build-essential |
| Port 8000 already used | another instance | stop it or set `RPM_PORT` |

## Hardware gateway service (Pi)

| Symptom | Cause | Fix |
|---|---|---|
| `config error: [radio] frequency_hz is required` | not set on purpose in the example | set it in `hardware/gateway.toml` to your modules' frequency |
| `RPM_GATEWAY_INGEST_TOKEN is not set` | environment not loaded | `set -a; . ./.env; set +a` or use the systemd unit |
| `radio init failed: [Errno 2] No such file or directory: '/dev/spidev0.0'` | SPI disabled | `sudo raspi-config` → Interface Options → SPI; reboot |
| `PermissionError` on spidev or GPIO | user not in `spi` / `gpio` groups | `sudo usermod -aG spi,gpio <user>`; log in again |
| `no SX127x found on SPI (RegVersion = 0x00 or 0xFF)` | wiring (MISO/MOSI swapped, wrong CS), no 3.3 V, or the module is an SX126x | check `HARDWARE_SETUP.md` § 3; SX126x needs a different driver |
| Radio initialises but nothing is received | frequency / SF / BW / sync word differ from the nodes; antenna missing; module band mismatch | compare `config.h` and `gateway.toml` line by line |
| Log: `API not reachable … frame spooled` | platform stopped or wrong `[api] url` | start the platform; spooled frames are delivered automatically |
| Platform answers 503 `E_DISABLED` | token not configured on the platform side | set the same `RPM_GATEWAY_INGEST_TOKEN` for both services |
| Platform answers 401 to the gateway | tokens differ | make them identical; restart both |

## Frames arrive but are not stored (LoRa network → events)

| Event | Meaning | Fix |
|---|---|---|
| `unknown_device` | `sourceId` not registered in hardware mode | register the device; check the id typed in `PROVISION` |
| `rejected` — "not active or not paired" | device registered but not paired, disabled or retired | Devices → Pair / Enable |
| `rejected` — "routing identity mismatch" | node's patient id or gateway id differs from the pairing | re-run `PROVISION` with the values from the dashboard |
| `auth_fail` | wrong key on the node (or key rotated on the server) | Devices → New key → `PROVISION` again |
| `replay` | node restarted with an older sequence number (e.g. NVS erased) while the server remembers a higher one | Devices → New key (resets the sequence space) → `PROVISION` |
| `duplicate` | normal for event frames (sent twice) and relayed copies | none |
| `crc_error` / `malformed` | interference, or a different device type on the same channel | none if occasional; change frequency if constant |
| `lost` | sequence gap | improve link (antenna, distance, SF) |

## ESP32 node

| Symptom | Cause | Fix |
|---|---|---|
| Compile error `Set RPM_LORA_FREQUENCY_MHZ in config.h` / `Define exactly one of RPM_RADIO_…` | deliberate safety stop | edit `config.h` for your module |
| Serial: `Radio …: INIT FAILED` | wiring / wrong chip selected / module not powered | check pins and the chip marking; RadioLib error code is printed by `STATUS` |
| `ERR not provisioned` | no identity in NVS | send the `PROVISION` line from the dashboard |
| `TX … FAILED (radio err -…)` | radio fault during transmit | the firmware re-initialises on the next cycle; check supply (add a capacitor) and antenna |
| Dashboard shows "Sensor malfunction" continuously | sensor not wired but enabled in `config.h`, or MAX30102 without finger contact | fix wiring or set `RPM_USE_… 0` |
| Board resets when transmitting | supply dip | power the radio from a stable 3.3 V rail, add 100 µF |
| Wokwi build problems | see root README, section Wokwi | – |

## OMNeT++ (WSL `opp_env`)

| Symptom | Note |
|---|---|
| `Multiple versions specified for project inet: [4.6.0, 4.7.0]` when opening the shell | pre-existing; both INET versions are in the workspace. Not modified by this project. Run with explicit versions: `opp_env run omnetpp-6.5.0 inet-4.6.0 --no-deps --no-isolated -c '…'` |
| `wsl … cat` of a `.sca` file returns nothing from Git Bash | path conversion; use PowerShell, or `MSYS_NO_PATHCONV=1` |

## Getting diagnostic information

* Administration → System health (model, databases, audit chain, gateway state).
* Administration → Audit trail (who did what, denied attempts).
* LoRa network → events (reason for every rejected frame).
* `journalctl -u rpm-platform -u rpm-gateway -f` on the Pi.
