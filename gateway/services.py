"""Service container + domain operations shared by the HTTP API and the simulation engine
(patient registration, device enrollment/pairing, access scoping). No Flask imports here."""
import json
import re
import secrets
import time

from .alert_engine import AlertEngine
from .events import Broker
from .inference import Predictor
from .ingest import Monitor, Pipeline
from .security import Audit, Auth, wrap
from .store import Store


class DomainError(Exception):
    def __init__(self, message, code="E_VALIDATION", status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


class Services:
    def __init__(self, cfg, clock=time.time):
        self.cfg, self.clock = cfg, clock
        self.started_at = clock()
        self.store = Store(cfg)
        self.audit = Audit(self.store.system, clock)
        self.auth = Auth(self.store, cfg, self.audit, clock)
        self.broker = Broker()
        self.predictor = Predictor(cfg.MODEL_DIR)
        self.alerts = AlertEngine(self)
        self.pipeline = Pipeline(self)
        self.monitor = Monitor(self)
        self.simulator = None           # attached by gateway.simulator.attach()

    # ---- access scoping (server-side, never from request data) ----------------------------------------
    def visible_patient_ids(self, user, ns):
        """Set of patient ids this user may see in namespace `ns`."""
        db, now = self.store.ns(ns), self.clock()
        if user["role"] == "doctor":
            if user.get("is_admin"):
                return {r["id"] for r in db.q("SELECT id FROM patients")}
            return {r["id"] for r in db.q(
                """SELECT id FROM patients WHERE primary_doctor_id=?
                   UNION SELECT patient_id FROM staff_assignments WHERE user_id=?""", (user["id"], user["id"]))}
        if user["role"] == "assistant":
            return {r["patient_id"] for r in db.q("SELECT patient_id FROM staff_assignments WHERE user_id=?", (user["id"],))}
        if user["role"] == "caregiver":
            return {r["patient_id"] for r in db.q(
                """SELECT l.patient_id FROM caregiver_links l JOIN consent_records c ON c.id=l.consent_id
                   WHERE l.user_id=? AND l.revoked_at IS NULL AND (l.expires_at IS NULL OR l.expires_at>?)
                   AND c.revoked_at IS NULL AND (c.expires_at IS NULL OR c.expires_at>?)""", (user["id"], now, now))}
        return set()

    def caregiver_link(self, user, ns, patient_id):
        now = self.clock()
        return self.store.ns(ns).one(
            """SELECT l.* FROM caregiver_links l JOIN consent_records c ON c.id=l.consent_id
               WHERE l.user_id=? AND l.patient_id=? AND l.revoked_at IS NULL AND (l.expires_at IS NULL OR l.expires_at>?)
               AND c.revoked_at IS NULL AND (c.expires_at IS NULL OR c.expires_at>?)""", (user["id"], patient_id, now, now))

    # ---- patients ------------------------------------------------------------------------------------
    def register_patient(self, ns, data, user, synthetic=False, sim_session_id=None):
        db = self.store.ns(ns)
        name = str(data.get("full_name") or "").strip()
        if not 2 <= len(name) <= 120:
            raise DomainError("full_name is required (2-120 characters)")
        pid = data.get("id")
        if pid is None:
            pid = (db.scalar("SELECT COALESCE(MAX(id),0) FROM patients") or 0) + 1
        if isinstance(pid, bool) or not isinstance(pid, int) or not 1 <= pid <= 65535:
            raise DomainError("patient id must be an integer 1..65535")
        if db.one("SELECT 1 FROM patients WHERE id=?", (pid,)):
            raise DomainError(f"patient id {pid} already exists", "E_CONFLICT", 409)
        dob, sex = data.get("date_of_birth") or None, data.get("sex") or None
        if dob and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(dob)):
            raise DomainError("date_of_birth must be YYYY-MM-DD")
        if sex not in (None, "F", "M", "X"):
            raise DomainError("sex must be F, M or X")
        doctor = data.get("primary_doctor_id") or (user["id"] if user and user["role"] == "doctor" else None)
        if doctor is not None:
            u = self.auth.user(doctor)
            if not u or u["role"] != "doctor":
                raise DomainError("primary_doctor_id must reference a doctor account")
        thr = data.get("thresholds")
        db.x("""INSERT INTO patients(id,code,full_name,date_of_birth,sex,phone,address,primary_doctor_id,thresholds,is_synthetic,
                sim_session_id,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
             (pid, f"P{pid:03d}", name, dob, sex, (data.get("phone") or None), (data.get("address") or None), doctor,
              json.dumps(validate_thresholds(thr)) if thr else None, int(synthetic or ns == "simulation"), sim_session_id,
              self.clock(), user["id"] if user else None))
        return db.one("SELECT * FROM patients WHERE id=?", (pid,))

    # ---- devices: secure enrollment --------------------------------------------------------------------
    def register_device(self, ns, data, user, virtual=False):
        """Create a device identity with its own random 256-bit key. The clear key is returned ONCE
        (provisioning) and only its AES-GCM-wrapped form is stored."""
        db = self.store.ns(ns)
        if virtual != (ns == "simulation"):
            raise DomainError("virtual devices exist only in the simulation namespace")
        serial = str(data.get("serial") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9:._-]{3,40}", serial):
            raise DomainError("serial is required (3-40 characters: letters, digits, : . _ -)")
        if db.one("SELECT 1 FROM devices WHERE serial=?", (serial,)):
            raise DomainError("a device with this serial already exists", "E_CONFLICT", 409)
        did = data.get("id")
        if did is None:
            did = (db.scalar("SELECT COALESCE(MAX(id),100) FROM devices") or 100) + 1
        if isinstance(did, bool) or not isinstance(did, int) or not 1 <= did <= 65535:
            raise DomainError("device id must be an integer 1..65535")
        if db.one("SELECT 1 FROM devices WHERE id=?", (did,)):
            raise DomainError(f"device id {did} already exists", "E_CONFLICT", 409)
        key = secrets.token_bytes(32)
        db.x("""INSERT INTO devices(id,serial,label,hw_model,radio,firmware_version,key_enc,status,is_virtual,registered_at,registered_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
             (did, serial, (data.get("label") or None), (data.get("hw_model") or None), (data.get("radio") or None),
              (data.get("firmware_version") or None), wrap(self.cfg.MASTER_KEY, key, f"dev:{ns}:{did}".encode()),
              "provisioned", int(virtual), self.clock(), user["id"] if user else None))
        return db.one("SELECT * FROM devices WHERE id=?", (did,)), key

    def rotate_device_key(self, ns, device_id):
        db = self.store.ns(ns)
        if not db.one("SELECT 1 FROM devices WHERE id=?", (device_id,)):
            raise DomainError("unknown device", "E_NOT_FOUND", 404)
        key = secrets.token_bytes(32)
        db.x("""UPDATE devices SET key_enc=?, key_version=key_version+1, last_seq=0, replay_window=0 WHERE id=?""",
             (wrap(self.cfg.MASTER_KEY, key, f"dev:{ns}:{device_id}".encode()), device_id))
        return key

    def pair_device(self, ns, device_id, patient_id, user):
        """Associate a device with a patient (one active device per patient; closes previous assignment)."""
        db, now = self.store.ns(ns), self.clock()
        dev = db.one("SELECT * FROM devices WHERE id=?", (device_id,))
        if not dev:
            raise DomainError("unknown device", "E_NOT_FOUND", 404)
        if dev["status"] in ("disabled", "replaced"):
            raise DomainError(f"device is {dev['status']}", "E_STATE", 409)
        if not db.one("SELECT 1 FROM patients WHERE id=?", (patient_id,)):
            raise DomainError("unknown patient", "E_NOT_FOUND", 404)
        other = db.one("SELECT id FROM devices WHERE patient_id=? AND status='active' AND id<>?", (patient_id, device_id))
        if other:
            raise DomainError(f"patient already has active device {other['id']}; disable or replace it first", "E_CONFLICT", 409)
        with db.tx() as c:
            c.execute("UPDATE device_assignments SET unassigned_at=? WHERE device_id=? AND unassigned_at IS NULL", (now, device_id))
            c.execute("UPDATE devices SET patient_id=?, status='active', online=0 WHERE id=?", (patient_id, device_id))
            c.execute("INSERT INTO device_assignments(device_id,patient_id,assigned_at,assigned_by) VALUES(?,?,?,?)",
                      (device_id, patient_id, now, user["id"] if user else None))
        return db.one("SELECT * FROM devices WHERE id=?", (device_id,))

    def set_device_status(self, ns, device_id, status):
        db, now = self.store.ns(ns), self.clock()
        if status not in ("active", "disabled", "replaced"):
            raise DomainError("invalid status")
        dev = db.one("SELECT * FROM devices WHERE id=?", (device_id,))
        if not dev:
            raise DomainError("unknown device", "E_NOT_FOUND", 404)
        if status == "active" and dev["patient_id"] is None:
            raise DomainError("pair the device with a patient first", "E_STATE", 409)
        with db.tx() as c:
            if status == "replaced":
                c.execute("UPDATE device_assignments SET unassigned_at=? WHERE device_id=? AND unassigned_at IS NULL", (now, device_id))
                c.execute("UPDATE devices SET status='replaced', patient_id=NULL, online=0 WHERE id=?", (device_id,))
            else:
                c.execute("UPDATE devices SET status=?, online=CASE WHEN ?='disabled' THEN 0 ELSE online END WHERE id=?",
                          (status, status, device_id))
        return db.one("SELECT * FROM devices WHERE id=?", (device_id,))


THRESHOLD_BOUNDS = {"hr_high": (60, 220), "hr_low": (25, 80), "spo2_low": (70, 99), "temp_high": (36.5, 42), "temp_low": (30, 36.5),
                    "hr_warn": (60, 220), "spo2_warn": (70, 100), "temp_warn": (36, 42)}


def validate_thresholds(t):
    if not isinstance(t, dict):
        raise DomainError("thresholds must be an object")
    out = {}
    for k, v in t.items():
        if k not in THRESHOLD_BOUNDS:
            raise DomainError(f"unknown threshold {k!r}")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not THRESHOLD_BOUNDS[k][0] <= v <= THRESHOLD_BOUNDS[k][1]:
            raise DomainError(f"{k} must be a number in {THRESHOLD_BOUNDS[k][0]}..{THRESHOLD_BOUNDS[k][1]}")
        out[k] = float(v)
    return out
