"""Platform (v2) configuration. Everything is read from environment variables (see .env.example).

The legacy pre-MVP API keeps its own `gateway.config.Config`; this class configures the v2 platform
(`gateway.server`). No secret has a default value: secrets are either supplied through the environment
or, in development only, generated on first start and stored in DATA_DIR (which is git-ignored).
"""
import base64
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent

# Engineering demonstration thresholds (cahier des charges). NOT universally valid medical rules.
DEFAULT_THRESHOLDS = {
    "hr_high": 120.0, "hr_low": 40.0, "spo2_low": 92.0, "temp_high": 38.0, "temp_low": 35.0,
    "hr_warn": 100.0, "spo2_warn": 95.0, "temp_warn": 37.5,
}
# Hard plausibility limits: outside these a value is treated as a sensor problem, not physiology.
PLAUSIBLE = {"heartRate": (20.0, 250.0), "spO2": (50.0, 100.0), "temperature": (25.0, 45.0)}


def _env(name, default, cast=str):
    v = os.environ.get(name)
    if v in (None, ""):
        return default
    if cast is bool:
        return v.strip().lower() in ("1", "true", "yes", "on")
    return cast(v)


@dataclass
class PlatformConfig:
    ENV: str = "development"                 # development | production
    DATA_DIR: str = str(ROOT / "data")
    MODEL_DIR: str = str(ROOT / "ml" / "models")
    RESEARCH_DIR: str = str(ROOT / "simulation" / "omnetpp" / "imported_results")
    MASTER_KEY: bytes = b""                  # 32 bytes, AES-256-GCM key wrapping device keys / TOTP secrets
    GATEWAY_INGEST_TOKEN: str = ""           # bearer token of the hardware gateway service (hardware namespace only)
    GATEWAY_ID: int = 1                      # destinationId of the doctor gateway (FLoRa doctorId = 1)
    MAX_HOP_COUNT: int = 4                   # FLoRa maxHopCount = 4
    ALLOW_LEGACY_V1: bool = False            # accept unauthenticated 16-byte v1 packets from the trusted gateway
    # Sessions / authentication
    SESSION_IDLE_S: int = 1800
    SESSION_ABSOLUTE_S: int = 12 * 3600
    COOKIE_SECURE: bool = False              # forced True in production
    LOGIN_RATE_PER_MIN: int = 10             # per client IP
    LOCKOUT_AFTER: int = 5                   # failed logins before progressive delay
    LOCKOUT_BASE_S: int = 30
    LOCKOUT_MAX_S: int = 900
    PASSWORD_MIN_LEN: int = 12
    RESET_TOKEN_TTL_S: int = 900
    # Monitoring
    DEVICE_OFFLINE_AFTER_S: int = 180        # no valid frame for this long -> device offline
    STALE_AFTER_S: int = 120                 # latest measurement older than this is shown as stale
    ESCALATE_AFTER_S: int = 180              # unacknowledged critical/high alert -> escalated
    NOTIFY_MAX_PER_MIN: int = 12             # per user and channel (storm protection)
    RETENTION_DAYS: int = 30
    NETWORK_EVENT_KEEP: int = 5000
    # Prediction
    PREDICT_LOOKBACK_S: int = 900
    PREDICTIVE_ALERTS: bool = True
    # Optional notification adapters (unused unless configured AND delivery-tested by the operator)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMS_PROVIDER: str = ""                   # no provider adapter ships; see docs/SECURITY.md
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    thresholds: dict = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))

    # ---- derived paths ---------------------------------------------------
    @property
    def system_db(self): return os.path.join(self.DATA_DIR, "rpm_system.sqlite3")

    def clinical_db(self, ns):
        if ns not in ("hardware", "simulation"):
            raise ValueError(f"unknown namespace {ns!r}")
        return os.path.join(self.DATA_DIR, "rpm_hw.sqlite3" if ns == "hardware" else "rpm_sim.sqlite3")

    @property
    def production(self): return self.ENV == "production"

    @classmethod
    def from_env(cls):
        c = cls()
        for name, f in c.__dataclass_fields__.items():
            if name in ("MASTER_KEY", "thresholds"):
                continue
            cur = getattr(c, name)
            setattr(c, name, _env("RPM_" + name, cur, type(cur)))
        if c.production:
            c.COOKIE_SECURE = True
        c.MASTER_KEY = load_master_key(c)
        return c


def load_master_key(cfg) -> bytes:
    """RPM_MASTER_KEY (urlsafe base64, 32 bytes). Production: mandatory. Development: generated once into
    DATA_DIR/.master_key (git-ignored) so a fresh checkout can run the simulation without manual setup."""
    raw = os.environ.get("RPM_MASTER_KEY", "")
    if raw:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        if len(key) != 32:
            raise RuntimeError("RPM_MASTER_KEY must decode to exactly 32 bytes")
        return key
    if cfg.production:
        raise RuntimeError("RPM_MASTER_KEY must be set in production (see .env.example)")
    os.makedirs(cfg.DATA_DIR, exist_ok=True)
    path = os.path.join(cfg.DATA_DIR, ".master_key")
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return base64.urlsafe_b64decode(f.read().strip())
    key = secrets.token_bytes(32)
    with open(path, "wb") as f:
        f.write(base64.urlsafe_b64encode(key))
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover (Windows)
        pass
    return key
