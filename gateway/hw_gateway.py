"""Hardware gateway service (runs on the Raspberry Pi 5, separate process from the web application).

    radio (SX127x over SPI)  ->  this service  ->  POST /api/v1/ingest/frame (bearer RPM_GATEWAY_INGEST_TOKEN)

* The service only moves bytes: every validation (CRC, device registration, authentication tag, replay window,
  plausibility) is done by the platform's ingestion pipeline, the same one the simulation uses.
* Store-and-forward: frames that cannot be delivered to the API are spooled on disk and retried in order.
* Recovery: a radio fault triggers re-initialisation with exponential back-off; the service never exits on I/O errors.
* The radio adapter is selected in the hardware config file; "stdin" lets you bench-test without any radio.

Run:  python -m gateway.hw_gateway --config hardware/gateway.toml
STATUS: HARDWARE PENDING - logic unit-tested with a fake radio; not yet run against a physical SX127x.
"""
import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

from .radio_sx127x import SX127x, RadioConfig, RadioError

log = logging.getLogger("rpm.hw_gateway")


def load_config(path):
    import tomllib
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    radio = cfg.get("radio", {})
    if "frequency_hz" not in radio:
        raise SystemExit("config error: [radio] frequency_hz is required (no default: it must match your modules and local regulations)")
    return cfg


class Spool:
    """Durable FIFO of undelivered frames (SQLite file). Bounded: the oldest frames are dropped beyond max_rows."""

    def __init__(self, path, max_rows=20000):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db, self.max_rows = sqlite3.connect(path), max_rows
        self.db.execute("CREATE TABLE IF NOT EXISTS spool(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, frame_hex TEXT, rssi REAL, snr REAL)")
        self.db.commit()

    def push(self, ts, frame_hex, rssi, snr):
        self.db.execute("INSERT INTO spool(ts,frame_hex,rssi,snr) VALUES(?,?,?,?)", (ts, frame_hex, rssi, snr))
        self.db.execute("DELETE FROM spool WHERE id <= (SELECT MAX(id) FROM spool) - ?", (self.max_rows,))
        self.db.commit()

    def peek(self):
        return self.db.execute("SELECT id, ts, frame_hex, rssi, snr FROM spool ORDER BY id LIMIT 1").fetchone()

    def pop(self, row_id):
        self.db.execute("DELETE FROM spool WHERE id=?", (row_id,))
        self.db.commit()

    def __len__(self):
        return self.db.execute("SELECT COUNT(*) FROM spool").fetchone()[0]


class ApiClient:
    def __init__(self, base_url, token, timeout=5):
        self.url, self.token, self.timeout = base_url.rstrip("/") + "/api/v1/ingest/frame", token, timeout

    def post(self, frame_hex, rssi, snr):
        """Returns (delivered, outcome). delivered=False means 'retry later' (network / server problem)."""
        req = urllib.request.Request(self.url, json.dumps({"frame_hex": frame_hex, "rssi": rssi, "snr": snr}).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return True, json.loads(r.read() or b"{}").get("outcome", "?")
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 413):          # permanent: retrying the same request cannot succeed
                return True, f"http_{e.code}"
            return False, f"http_{e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return False, f"unreachable ({e})"


class GatewayService:
    def __init__(self, radio_factory, api, spool, clock=time.time, sleep=time.sleep):
        self.radio_factory, self.api, self.spool, self.clock, self.sleep = radio_factory, api, spool, clock, sleep
        self.radio = None
        self.stats = {"received": 0, "radio_crc_errors": 0, "delivered": 0, "spooled": 0, "radio_restarts": 0, "outcomes": {}}
        self._backoff = 1.0

    def ensure_radio(self):
        if self.radio is not None:
            return True
        try:
            self.radio = self.radio_factory()
            self._backoff = 1.0
            log.info("radio initialised")
            return True
        except Exception as e:  # noqa: BLE001 - RadioError, SPI errors, missing device node ...
            log.error("radio init failed: %s (retry in %.0f s)", e, self._backoff)
            self.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, 60.0)
            self.stats["radio_restarts"] += 1
            return False

    def flush_spool(self, limit=50):
        for _ in range(limit):
            row = self.spool.peek()
            if not row:
                return True
            ok, outcome = self.api.post(row[2], row[3], row[4])
            if not ok:
                return False
            self.spool.pop(row[0])
            self._count(outcome)
        return True

    def _count(self, outcome):
        self.stats["delivered"] += 1
        self.stats["outcomes"][outcome] = self.stats["outcomes"].get(outcome, 0) + 1

    def step(self, timeout=1.0):
        """One iteration: receive at most one packet and forward it. Returns the outcome string or None."""
        if not self.ensure_radio():
            return None
        try:
            pkt = self.radio.receive(timeout)
        except Exception as e:  # noqa: BLE001
            log.error("radio receive failed: %s - re-initialising", e)
            self.radio = None
            return None
        if pkt is None:
            if len(self.spool):
                self.flush_spool()
            return None
        self.stats["received"] += 1
        if not pkt.crc_ok:
            self.stats["radio_crc_errors"] += 1
            return "radio_crc_error"
        hexs = pkt.payload.hex()
        if len(self.spool) and not self.flush_spool():           # keep ordering: older frames first
            self.spool.push(self.clock(), hexs, pkt.rssi, pkt.snr); self.stats["spooled"] += 1
            return "spooled"
        ok, outcome = self.api.post(hexs, pkt.rssi, pkt.snr)
        if not ok:
            log.warning("API not reachable (%s): frame spooled (%d waiting)", outcome, len(self.spool) + 1)
            self.spool.push(self.clock(), hexs, pkt.rssi, pkt.snr); self.stats["spooled"] += 1
            return "spooled"
        self._count(outcome)
        return outcome

    def run(self):
        last_log = last_health = self.clock()
        while True:
            self.step()
            now = self.clock()
            if now - last_health > 30 and self.radio is not None and hasattr(self.radio, "healthy"):
                last_health = now
                if not self.radio.healthy():
                    log.error("radio health check failed - re-initialising")
                    self.radio = None
                    self.stats["radio_restarts"] += 1
            if now - last_log > 60:
                last_log = now
                log.info("stats %s spool=%d", json.dumps(self.stats), len(self.spool))


class StdinRadio:
    """Bench adapter: one hex frame per line on stdin (optionally 'hex rssi snr'). No radio involved."""

    def receive(self, timeout=1.0):
        from .radio_sx127x import Packet
        line = sys.stdin.readline()
        if not line:
            raise SystemExit(0)
        parts = line.split()
        if not parts:
            return None
        try:
            return Packet(bytes.fromhex(parts[0]), float(parts[1]) if len(parts) > 1 else None, float(parts[2]) if len(parts) > 2 else None, True)
        except ValueError:
            return None


def make_radio_factory(cfg):
    r = cfg["radio"]
    adapter = r.get("adapter", "sx127x")
    if adapter == "stdin":
        return StdinRadio
    if adapter != "sx127x":
        raise SystemExit(f"config error: unsupported radio adapter {adapter!r} (available: sx127x, stdin). "
                         "SX126x modules need a different driver - see docs/HARDWARE_SETUP.md")
    rc = RadioConfig(frequency_hz=int(r["frequency_hz"]), bandwidth_hz=int(r.get("bandwidth_hz", 125000)),
                     spreading_factor=int(r.get("spreading_factor", 7)), coding_rate=int(r.get("coding_rate", 5)),
                     sync_word=int(r.get("sync_word", 0x12)), preamble=int(r.get("preamble", 8)))

    def factory():
        import spidev                                  # Raspberry Pi only (pip install spidev)
        spi = spidev.SpiDev()
        spi.open(int(r.get("spi_bus", 0)), int(r.get("spi_device", 0)))
        spi.max_speed_hz, spi.mode = int(r.get("spi_speed_hz", 1_000_000)), 0
        reset = None
        if r.get("reset_gpio") is not None:
            from gpiozero import DigitalOutputDevice   # uses lgpio on the Raspberry Pi 5
            line = DigitalOutputDevice(int(r["reset_gpio"]), initial_value=True)

            def reset():
                line.off(); time.sleep(0.002); line.on(); time.sleep(0.006)
        return SX127x(spi, rc, reset).begin()
    return factory


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="hardware/gateway.toml")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = load_config(a.config)
    token = os.environ.get("RPM_GATEWAY_INGEST_TOKEN", "")
    if not token:
        raise SystemExit("RPM_GATEWAY_INGEST_TOKEN is not set (same value as on the platform server)")
    api_cfg = cfg.get("api", {})
    svc = GatewayService(make_radio_factory(cfg), ApiClient(api_cfg.get("url", "http://127.0.0.1:8000"), token),
                         Spool(cfg.get("spool", {}).get("path", "data/gateway_spool.sqlite3")))
    log.info("hardware gateway starting (adapter %s)", cfg["radio"].get("adapter", "sx127x"))
    try:
        svc.run()
    except RadioError as e:
        raise SystemExit(f"radio error: {e}")


if __name__ == "__main__":
    main()
