# gateway package
`app.py` Flask API+UI · `config.py` env config · `database.py` SQLite · `telemetry.py` 16-byte codec · `alerts.py` rules · `prediction.py` LR fallback + TFLite loader · `auth.py` tokens · `radio.py` transports (`SimulationTransport`, `Sx1276Transport` interface, `LoRaConfig`) · `bridge.py` Gateway + `HttpForwarder` · `maintenance.py` retention.
Hardware mode = construct `Gateway(Sx1276Transport(your_driver), HttpForwarder(url, token))`; the driver must provide `configure(LoRaConfig)` and `receive(timeout)->bytes|None`. None is bundled.
