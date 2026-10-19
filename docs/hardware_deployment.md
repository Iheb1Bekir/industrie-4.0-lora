# Raspberry Pi deployment

```bash
sudo apt update && sudo apt install -y python3-venv git
cd ~ && unzip remote-patient-monitoring.zip && cd remote-patient-monitoring
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env && nano .env        # set DOCTOR_TOKEN / ADMIN_TOKEN (python -c "import secrets;print(secrets.token_urlsafe(32))")
chmod 600 .env
python -m gateway.app                     # binds 127.0.0.1:5000
```
Serve to the LAN with `HOST=0.0.0.0` **only behind HTTPS** (report architecture shows HTTPS; Flask's dev server has no TLS - put nginx/caddy with a certificate in front, or use a VPN). Tokens travel in headers: never expose plain HTTP beyond a trusted network. For production use a WSGI server (`pip install gunicorn; gunicorn -w 1 'gateway.app:create_app()'`; keep one worker so the in-process model is single).

## systemd (API)
`/etc/systemd/system/rpm-api.service`:
```
[Unit]
Description=RPM API
After=network.target
[Service]
User=pi
WorkingDirectory=/home/pi/remote-patient-monitoring
EnvironmentFile=/home/pi/remote-patient-monitoring/.env
ExecStart=/home/pi/remote-patient-monitoring/.venv/bin/python -m gateway.app
Restart=on-failure
[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now rpm-api`.

## Nightly retention (report: 30 days, export CSV then prune)
`crontab -e`: `15 3 * * * cd /home/pi/remote-patient-monitoring && . .venv/bin/activate && set -a && . ./.env && set +a && python -m gateway.maintenance`
Windows: Task Scheduler running `python -m gateway.maintenance` with the same environment variables. CSVs land in `EXPORT_DIR`; rows are deleted only after the CSV is written and row-count verified.

## Backup / recovery
Backup (safe while running): `sqlite3 data/rpm.sqlite3 ".backup 'backup-$(date +%F).sqlite3'"`. Recovery: stop the service, copy the backup over `DB_PATH`, start. Keep exported CSVs - they are the only copy of pruned data.

## Real radio (hardware mode) - what remains to be done
1. Node: add RadioLib to `libraries.txt`, build with `-DRPM_USE_SX1276`, switch `transport` to `Sx1276Transport` (code is a starting point, untested).
2. Gateway: write a driver object with `configure(LoRaConfig)` and `receive(timeout)->bytes|None` for your radio (e.g. wrapping a SX127x library or the HAT vendor stack), then run `Gateway(Sx1276Transport(driver), HttpForwarder(...))`. Set identical frequency/BW/SF/CR/sync word on both ends. RAK2245 needs a packet-forwarder based transport instead.
3. Measure PDR (500 packets at 0.5/1.2/2.5 km) and fill `validation_plan.md`.
Replace synthetic MAX30102: implement a driver returning HR/SpO2 and a validity flag in place of `SyntheticHrSpo2::read`, and stop setting `F_SYNTH` for those fields.
Troubleshooting: `401` wrong token; `429` sending faster than 30 s (set `VITALS_MIN_INTERVAL_S=0` only for demos); `no SX1276 driver supplied` = hardware transport not configured; SPI permission errors -> add user to `spi`/`gpio` groups.
