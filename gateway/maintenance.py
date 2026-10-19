"""Nightly maintenance: export readings older than RETENTION_DAYS to CSV, then delete them.
Run:  python -m gateway.maintenance      (cron example in docs/hardware_deployment.md)"""
import time
from .config import Config
from .database import Database


def run(cfg=None, now=None):
    cfg = cfg or Config.from_env()
    db = Database(cfg.DB_PATH); db.init()
    return db.export_and_prune(cfg.EXPORT_DIR, now or time.time(), cfg.RETENTION_DAYS)


if __name__ == "__main__":
    n, p = run()
    print(f"exported+pruned {n} rows" + (f" -> {p}" if p else ""))
