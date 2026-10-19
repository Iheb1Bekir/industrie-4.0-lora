import os, sys
import pytest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "wokwi", "gateway_simulation")))
from gateway.app import create_app
from gateway.config import Config

DOC, ADM = "doctor-test-token", "admin-test-token"
T0 = 1_700_000_000


class Clock:
    def __init__(self, t=T0): self.t = t
    def __call__(self): return self.t
    def advance(self, s): self.t += s


@pytest.fixture
def clock(): return Clock()


@pytest.fixture
def cfg(tmp_path):
    return Config(DB_PATH=str(tmp_path / "t.sqlite3"), EXPORT_DIR=str(tmp_path / "exp"), DOCTOR_TOKEN=DOC, ADMIN_TOKEN=ADM,
                  MODEL_PATH=str(tmp_path / "missing.tflite"), VITALS_MIN_INTERVAL_S=0)


@pytest.fixture
def app(cfg, clock): return create_app(cfg, clock=clock)


@pytest.fixture
def client(app): return app.test_client()


@pytest.fixture
def H(): return {"Authorization": f"Bearer {DOC}"}


@pytest.fixture
def HA(): return {"Authorization": f"Bearer {ADM}"}


def vitals(clock, **kw):
    d = {"pid": "P001", "hr": 78, "spo2": 97, "temp": 36.7, "fall": 0, "ts": int(clock())}
    d.update(kw); return d
