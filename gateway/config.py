"""Configuration from environment variables (see .env.example)."""
import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    def load_dotenv():
        return False

ROOT = Path(__file__).resolve().parent.parent


def _env(name, default, cast=str):
    v = os.environ.get(name)
    return default if v in (None, "") else cast(v)


@dataclass
class Config:
    DB_PATH: str = str(ROOT / "data" / "rpm.sqlite3")
    EXPORT_DIR: str = str(ROOT / "data" / "exports")
    DOCTOR_TOKEN: str = ""
    ADMIN_TOKEN: str = ""
    VITALS_MIN_INTERVAL_S: float = 30.0   # report: 1 write / 30 s / patient
    RETENTION_DAYS: int = 30              # report: 30 days
    STALE_AFTER_S: int = 180              # prototype: 3 missed 60 s cycles
    ALLOWED_HORIZONS: tuple = (15,)       # report: 15 min
    STEP_MINUTES: int = 5                 # 15 min -> 3 values (report example)
    WINDOW: int = 30                      # report: last 30 samples
    MIN_SAMPLES: int = 10                 # assumption
    MODEL_PATH: str = str(ROOT / "ml" / "artifacts" / "lstm.tflite")
    # Prototype alert thresholds (NOT clinically validated)
    SPO2_LOW: float = 92.0
    HR_HIGH: float = 120.0
    HR_LOW: float = 40.0
    TEMP_HIGH: float = 38.0
    TEMP_LOW: float = 35.0
    # Report risk rule (section 5.6)
    RISK_HIGH_SPO2: float = 92.0
    RISK_HIGH_HR: float = 120.0
    RISK_MED_SPO2: float = 95.0
    RISK_MED_HR: float = 100.0

    @classmethod
    def from_env(cls):
        d = cls()
        for f in d.__dataclass_fields__:
            cur = getattr(d, f)
            if f == "ALLOWED_HORIZONS":
                setattr(d, f, tuple(int(x) for x in _env(f, ",".join(map(str, cur))).split(",")))
            else:
                setattr(d, f, _env(f, cur, type(cur)))
        return d
