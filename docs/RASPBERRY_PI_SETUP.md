# Raspberry Pi 5 setup (gateway + local intelligence)

**HARDWARE PENDING**: these steps were written from the software's requirements; they have not been executed on your Pi. Commands assume Raspberry Pi OS Bookworm (64-bit), user `pi`.

## 1. System

```bash
sudo apt update && sudo apt install -y git python3-venv python3-dev sqlite3
sudo raspi-config        # Interface Options -> SPI -> enable ; reboot
sudo usermod -aG spi,gpio pi
ls /dev/spidev0.0        # must exist after reboot
```

## 2. Application

```bash
cd ~ && git clone https://github.com/Iheb1Bekir/industrie-4.0-lora.git remote-patient-monitoring
cd remote-patient-monitoring
scripts/setup.sh --pi                     # venv, dependencies, spidev/gpiozero/lgpio; trains a model only if none is present
```
The repository ships the trained model (`ml/models/`). It was produced with the scikit-learn version recorded in `ml/models/<version>/metadata.json`; install the same one on the Pi:

```bash
. .venv/bin/activate
python - <<'EOF'
import json; a=json.load(open('ml/models/active.json'))['version']
print(json.load(open(f'ml/models/{a}/metadata.json'))['dependencies'])
EOF
pip install "scikit-learn==<version printed above>"      # if pip has no wheel for it: python ml/train.py  (retrains locally)
```

## 3. Secrets and configuration

```bash
python -m gateway.manage gen-key          # prints RPM_MASTER_KEY=... and RPM_GATEWAY_INGEST_TOKEN=...
cp .env.example .env && nano .env         # paste both values; set RPM_ENV=production
chmod 600 .env
cp hardware/gateway.example.toml hardware/gateway.toml && nano hardware/gateway.toml   # set frequency_hz (required)
python -m gateway.manage create-user --role doctor --admin --username <you> --name "Dr <Name>"   # asks for the password
python -m gateway.manage set-mode hardware
```
Keep a copy of `RPM_MASTER_KEY` somewhere safe: without it the stored device keys cannot be decrypted and every node must be re-provisioned.

## 4. First start (foreground, to see the logs)

Terminal 1: `set -a; . ./.env; set +a; python -m gateway.server`
Terminal 2: `set -a; . ./.env; set +a; python -m gateway.hw_gateway --config hardware/gateway.toml`

Expected gateway log: `radio initialised`. If instead `no SX127x found on SPI (RegVersion = 0x00…)`: wiring, CS pin or power (see `TROUBLESHOOTING.md`).
Bench test without a radio: set `adapter = "stdin"` in `gateway.toml`, then paste a hex frame per line.

Open `http://127.0.0.1:8000` on the Pi (or through the reverse proxy below).

## 5. Services (systemd)

`/etc/systemd/system/rpm-platform.service`
```ini
[Unit]
Description=RPM platform (API, dashboard, inference)
After=network.target
[Service]
User=pi
WorkingDirectory=/home/pi/remote-patient-monitoring
EnvironmentFile=/home/pi/remote-patient-monitoring/.env
ExecStart=/home/pi/remote-patient-monitoring/.venv/bin/python -m gateway.server
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
```
`/etc/systemd/system/rpm-gateway.service`
```ini
[Unit]
Description=RPM hardware gateway (LoRa radio -> platform)
After=rpm-platform.service
[Service]
User=pi
SupplementaryGroups=spi gpio
WorkingDirectory=/home/pi/remote-patient-monitoring
EnvironmentFile=/home/pi/remote-patient-monitoring/.env
ExecStart=/home/pi/remote-patient-monitoring/.venv/bin/python -m gateway.hw_gateway --config hardware/gateway.toml
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now rpm-platform rpm-gateway
journalctl -u rpm-gateway -f
```
Both services restart automatically. After a platform restart the model reloads, device liveness is re-evaluated from stored timestamps, and frames received meanwhile are delivered from the gateway spool (`data/gateway_spool.sqlite3`).

## 6. HTTPS for access from other machines

The application serves HTTP on `127.0.0.1:8000`. To use the dashboard from a laptop or phone put a TLS reverse proxy in front, e.g. Caddy:

```bash
sudo apt install -y caddy
# /etc/caddy/Caddyfile
rpm.local {
    tls internal
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1          # do not buffer the Server-Sent Events stream
    }
}
sudo systemctl reload caddy
```
`tls internal` creates a local CA; install its root certificate on the client devices, or use a real certificate. Do not expose plain HTTP on the network: with `RPM_ENV=production` the session cookie is `Secure` and will not be sent over HTTP anyway.

## 7. Time

The Pi stamps every measurement. Keep its clock synchronised (`timedatectl status` → "System clock synchronized: yes"). Without internet, add a hardware RTC module or the Pi 5's RTC battery; a wrong gateway clock shifts every timestamp.

## 8. Maintenance

```bash
python -m gateway.manage backup /home/pi/backups        # consistent online copies of the three databases
python -m gateway.manage retention                      # delete clinical rows older than RPM_RETENTION_DAYS
python -m gateway.manage verify-audit
# crontab -e
15 3 * * *  cd /home/pi/remote-patient-monitoring && set -a && . ./.env && set +a && .venv/bin/python -m gateway.manage backup /home/pi/backups && .venv/bin/python -m gateway.manage retention
```
Restore: stop both services, copy the backup files over `data/rpm_system.sqlite3`, `data/rpm_hw.sqlite3`, `data/rpm_sim.sqlite3`, start the services. Updating the software: `git pull`, `pip install -r requirements.txt`, restart the services (database migrations apply automatically at start).

Model update / rollback: `ML_PIPELINE.md` § 8.

## 9. Resource monitoring

Administration → System health shows uptime, load average, process memory, disk, database sizes, live subscribers, model state, audit-chain integrity and whether the hardware gateway has delivered frames. AI intelligence shows inference latency measured on the Pi itself.
