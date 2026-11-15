"""Test harness around the v2 server: fake clock, the three roles, helper clients, frame builder."""
import os

PW = "Str0ng-Passw0rd-x"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class Clock:
    def __init__(self, t): self.t = t
    def __call__(self): return self.t
    def advance(self, s): self.t += s


class V2:
    def __init__(self, tmp_path, model_dir=None):
        from gateway.server import create_server
        from gateway.settings import PlatformConfig
        self.clock = Clock(1_800_000_000.0)
        self.cfg = PlatformConfig(DATA_DIR=str(tmp_path / "data"), MASTER_KEY=os.urandom(32),
                                  MODEL_DIR=model_dir or os.path.join(ROOT, "ml", "models"), GATEWAY_INGEST_TOKEN="gw-test-token",
                                  RESEARCH_DIR=str(tmp_path / "research"))
        self.app = create_server(self.cfg, clock=self.clock)
        self.svc = self.app.config["SERVICES"]
        a = self.svc.auth
        self.ids = {"doc": a.create_user("doc", PW, "doctor", "Doc One", is_admin=True),
                    "doc2": a.create_user("doc2", PW, "doctor", "Doc Two"),
                    "asst": a.create_user("asst", PW, "assistant", "Assistant"),
                    "fam": a.create_user("fam", PW, "caregiver", "Family", is_demo=True),
                    "fam2": a.create_user("fam2", PW, "caregiver", "Other Family")}

    def login(self, username, password=PW):
        c = self.app.test_client()
        r = c.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.json
        c.csrf = {"X-CSRF-Token": r.json["csrf_token"]}
        return c

    def start_sim(self, **cfg):
        """Start the engine WITHOUT its thread; tests drive it deterministically with run_sim()."""
        body = {"scenario": "A", "patient_count": 3, "speed": 10, "interval_s": 30, "base_loss": 0.0, "duplicate_rate": 0.0, "delay_rate": 0.0}
        body.update(cfg)
        return self.svc.simulator.start(body, self.svc.auth.user(self.ids["doc"]), threaded=False)

    def run_sim(self, seconds, dt=0.5):
        for i in range(int(seconds / dt)):
            self.clock.advance(dt)
            self.svc.simulator.step(self.clock())
            if i % 10 == 0:
                self.svc.monitor.tick(self.clock())

    def hw_patient(self, client, name="Real Patient", pid=None):
        """Register a patient + physical device (hardware mode). Returns (patient_id, device_id, key)."""
        body = {"full_name": name}
        if pid:
            body["id"] = pid
        r = client.post("/api/v1/patients", json=body, headers=client.csrf)
        assert r.status_code == 201, r.json
        p = r.json["patient"]
        r = client.post("/api/v1/devices", json={"serial": f"ESP32-{p['id']:04d}", "patient_id": p["id"]}, headers=client.csrf)
        assert r.status_code == 201, r.json
        return p["id"], r.json["device"]["id"], bytes.fromhex(r.json["provisioning"]["device_key_hex"])

    def frame(self, pid, did, key, seq, **kw):
        from gateway import protocol as P
        m = {"patientId": pid, "sourceId": did, "destinationId": 1, "seqNo": seq, "timestamp": int(self.clock()), "heartRate": 75,
             "spO2": 97, "temperature": 36.8, "fallDetected": False, "alertLevel": 0, "routingMode": 0, "hopCount": 0, "maxHopCount": 4,
             "payloadType": 1, "flags": P.F_TIME_SYNCED, "critical": False}
        m.update(kw)
        return P.encode(m, key)

    def ingest(self, raw, **kw):
        return self.svc.pipeline.handle_frame("hardware", raw, **kw)

    def open_alerts(self, ns, pid=None):
        q, a = "SELECT type FROM alerts WHERE status IN ('new','acknowledged','assigned','escalated')", ()
        if pid is not None:
            q, a = q + " AND patient_id=?", (pid,)
        return sorted(r["type"] for r in self.svc.store.ns(ns).q(q, a))
