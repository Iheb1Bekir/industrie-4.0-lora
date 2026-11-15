"""SQLite persistence for the v2 platform.

Three physically separate database files (strong isolation, see docs/ARCHITECTURE.md):
  rpm_system.sqlite3  users, sessions, audit log, settings, model registry        (shared)
  rpm_hw.sqlite3      clinical data received from REAL hardware                   (namespace "hardware")
  rpm_sim.sqlite3     clinical data produced by the simulation engine             (namespace "simulation")

A simulated record can never be written to the hardware file: every write goes through
`Store.ns(<namespace>)` and the namespace is chosen by the *credential* of the data source, never by a
field of the payload. Schema changes are ordered, versioned migrations (table schema_migrations).
All SQL is parameterized.
"""
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

SYSTEM_MIGRATIONS = [
    (1, """
CREATE TABLE users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  full_name TEXT NOT NULL,
  email TEXT, phone TEXT,
  role TEXT NOT NULL CHECK(role IN ('doctor','assistant','caregiver')),
  is_admin INTEGER NOT NULL DEFAULT 0 CHECK(is_admin IN (0,1)),
  password_hash TEXT NOT NULL,
  is_demo INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  failed_logins INTEGER NOT NULL DEFAULT 0,
  locked_until REAL NOT NULL DEFAULT 0,
  totp_secret_enc BLOB, totp_enabled INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, last_login_at REAL,
  CHECK(is_admin = 0 OR role = 'doctor'));
CREATE TABLE sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_hash TEXT NOT NULL UNIQUE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  created_at REAL NOT NULL, last_seen_at REAL NOT NULL, expires_at REAL NOT NULL,
  ip TEXT, ua_hash TEXT, revoked INTEGER NOT NULL DEFAULT 0);
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE TABLE password_resets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE, expires_at REAL NOT NULL, used_at REAL, created_by INTEGER);
CREATE TABLE audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, user_id INTEGER, username TEXT, action TEXT NOT NULL,
  target_type TEXT, target_id TEXT, ns TEXT, ip TEXT, outcome TEXT NOT NULL DEFAULT 'ok',
  detail TEXT, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE INDEX idx_audit_ts ON audit_log(ts);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL, updated_by INTEGER);
CREATE TABLE model_versions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, version TEXT NOT NULL UNIQUE, path TEXT NOT NULL,
  dataset_version TEXT, trained_at TEXT, status TEXT NOT NULL DEFAULT 'registered'
    CHECK(status IN ('registered','active','archived')),
  deployed_at REAL, deployed_by INTEGER);
"""),
]

CLINICAL_MIGRATIONS = [
    (1, """
CREATE TABLE patients(
  id INTEGER PRIMARY KEY CHECK(id BETWEEN 1 AND 65535),      -- numeric patientId carried in LoRa frames
  code TEXT NOT NULL UNIQUE,                                 -- display id, e.g. P001
  full_name TEXT NOT NULL,
  date_of_birth TEXT, sex TEXT CHECK(sex IN ('F','M','X') OR sex IS NULL),
  phone TEXT, address TEXT,
  primary_doctor_id INTEGER,                                 -- users.id (system DB, enforced in code)
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','discharged')),
  thresholds TEXT,                                           -- JSON patient-specific overrides
  is_synthetic INTEGER NOT NULL DEFAULT 0,
  sim_session_id INTEGER,
  created_at REAL NOT NULL, created_by INTEGER);
CREATE TABLE staff_assignments(
  patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL, role TEXT NOT NULL, assigned_at REAL NOT NULL, assigned_by INTEGER,
  PRIMARY KEY(patient_id, user_id));
CREATE TABLE consent_records(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('caregiver_access','location_sharing')),
  granted_by_name TEXT NOT NULL, recorded_by INTEGER, scope TEXT,
  granted_at REAL NOT NULL, expires_at REAL, revoked_at REAL, revoked_by INTEGER, note TEXT);
CREATE TABLE caregiver_links(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL, relationship TEXT,
  consent_id INTEGER NOT NULL REFERENCES consent_records(id),
  can_view_vitals INTEGER NOT NULL DEFAULT 1, can_view_location INTEGER NOT NULL DEFAULT 0,
  notify INTEGER NOT NULL DEFAULT 1,
  granted_at REAL NOT NULL, expires_at REAL, revoked_at REAL, revoked_by INTEGER,
  UNIQUE(patient_id, user_id, consent_id));
CREATE INDEX idx_cg_user ON caregiver_links(user_id);
CREATE TABLE devices(
  id INTEGER PRIMARY KEY CHECK(id BETWEEN 1 AND 65535),      -- sourceId carried in LoRa frames
  serial TEXT NOT NULL UNIQUE, label TEXT,
  hw_model TEXT, radio TEXT, firmware_version TEXT,
  key_enc BLOB NOT NULL, key_version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'provisioned' CHECK(status IN ('provisioned','active','disabled','replaced')),
  patient_id INTEGER REFERENCES patients(id) ON DELETE SET NULL,
  is_virtual INTEGER NOT NULL DEFAULT 0,                     -- 1 = simulated device (simulation namespace only)
  last_seen_at REAL, online INTEGER NOT NULL DEFAULT 0,
  last_seq INTEGER NOT NULL DEFAULT 0, replay_window INTEGER NOT NULL DEFAULT 0,
  last_rssi REAL, last_snr REAL, last_battery INTEGER, last_hop_count INTEGER, last_routing_mode INTEGER,
  rx_count INTEGER NOT NULL DEFAULT 0, dup_count INTEGER NOT NULL DEFAULT 0, lost_estimate INTEGER NOT NULL DEFAULT 0,
  auth_fail_count INTEGER NOT NULL DEFAULT 0, replay_count INTEGER NOT NULL DEFAULT 0,
  out_of_order_count INTEGER NOT NULL DEFAULT 0, latency_ms_sum REAL NOT NULL DEFAULT 0, latency_n INTEGER NOT NULL DEFAULT 0,
  registered_at REAL NOT NULL, registered_by INTEGER);
CREATE TABLE device_assignments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  assigned_at REAL NOT NULL, unassigned_at REAL, assigned_by INTEGER);
CREATE TABLE measurements(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  device_id INTEGER NOT NULL REFERENCES devices(id),
  seq_no INTEGER NOT NULL,
  ts REAL NOT NULL,                       -- UTC epoch seconds of the measurement (see docs/DATA_DICTIONARY.md)
  device_ts INTEGER, received_at REAL NOT NULL,
  heart_rate REAL, spo2 REAL, temperature REAL,
  fall_detected INTEGER NOT NULL DEFAULT 0,
  alert_level INTEGER NOT NULL DEFAULT 0, routing_mode INTEGER NOT NULL DEFAULT 0,
  source_id INTEGER NOT NULL, destination_id INTEGER NOT NULL,
  hop_count INTEGER NOT NULL DEFAULT 0, max_hop_count INTEGER NOT NULL DEFAULT 0,
  payload_type INTEGER NOT NULL DEFAULT 1, critical INTEGER NOT NULL DEFAULT 0,
  flags INTEGER NOT NULL DEFAULT 0, battery INTEGER,
  rssi REAL, snr REAL,
  quality TEXT NOT NULL DEFAULT 'ok',     -- ok | partial | sensor_fault | implausible
  data_source TEXT NOT NULL CHECK(data_source IN ('hardware','simulation','legacy_v1')),
  sim_session_id INTEGER,
  key_epoch INTEGER NOT NULL DEFAULT 1,   -- devices.key_version at reception (seqNo restarts after re-provisioning)
  UNIQUE(device_id, seq_no, key_epoch));
CREATE INDEX idx_meas_patient_ts ON measurements(patient_id, ts);
CREATE INDEX idx_meas_ts ON measurements(ts);
CREATE TABLE predictions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  measurement_id INTEGER REFERENCES measurements(id) ON DELETE SET NULL,
  ts REAL NOT NULL, model_name TEXT, model_version TEXT,
  prediction_type TEXT NOT NULL, status TEXT NOT NULL,
  score REAL, probability REAL, threshold REAL, risk_category TEXT NOT NULL,
  explanation TEXT, supporting TEXT, latency_ms REAL, sim_session_id INTEGER);
CREATE INDEX idx_pred_patient_ts ON predictions(patient_id, ts);
CREATE TABLE alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER REFERENCES patients(id) ON DELETE CASCADE,
  device_id INTEGER,
  type TEXT NOT NULL,
  category TEXT NOT NULL CHECK(category IN ('threshold','fall','predictive','device','sensor','network','data_quality')),
  severity TEXT NOT NULL CHECK(severity IN ('info','warning','high','critical')),
  message TEXT NOT NULL,
  measurement_id INTEGER, prediction_id INTEGER,
  status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','acknowledged','assigned','escalated','resolved','false_positive')),
  created_at REAL NOT NULL, last_trigger_at REAL NOT NULL, trigger_count INTEGER NOT NULL DEFAULT 1,
  assigned_to INTEGER, acknowledged_at REAL, acknowledged_by INTEGER,
  escalated_at REAL, escalation_level INTEGER NOT NULL DEFAULT 0,
  resolved_at REAL, resolved_by INTEGER, note TEXT, sim_session_id INTEGER);
CREATE INDEX idx_alerts_open ON alerts(patient_id, type, status);
CREATE INDEX idx_alerts_created ON alerts(created_at);
CREATE TABLE alert_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alert_id INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
  ts REAL NOT NULL, user_id INTEGER, action TEXT NOT NULL, from_status TEXT, to_status TEXT, note TEXT);
CREATE TABLE clinical_notes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  author_id INTEGER NOT NULL, author_name TEXT NOT NULL, author_role TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('clinical','observation')),
  ts REAL NOT NULL, body TEXT NOT NULL);
CREATE TABLE locations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  ts REAL NOT NULL, lat REAL NOT NULL CHECK(lat BETWEEN -90 AND 90), lon REAL NOT NULL CHECK(lon BETWEEN -180 AND 180),
  accuracy_m REAL, source TEXT NOT NULL CHECK(source IN ('simulated','manual','gps')),
  consent_id INTEGER, recorded_by INTEGER);
CREATE INDEX idx_loc_patient_ts ON locations(patient_id, ts);
CREATE TABLE network_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, kind TEXT NOT NULL, device_id INTEGER, patient_id INTEGER, seq_no INTEGER,
  hop_count INTEGER, rssi REAL, snr REAL, latency_ms REAL, detail TEXT, sim_session_id INTEGER);
CREATE INDEX idx_net_ts ON network_events(ts);
CREATE TABLE network_counters(name TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0);
CREATE TABLE notifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL, alert_id INTEGER REFERENCES alerts(id) ON DELETE CASCADE,
  channel TEXT NOT NULL, ts REAL NOT NULL, status TEXT NOT NULL, title TEXT, body TEXT, read_at REAL);
CREATE INDEX idx_notif_user ON notifications(user_id, ts);
CREATE TABLE sim_sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at REAL NOT NULL, stopped_at REAL, scenario TEXT, config TEXT, started_by INTEGER, status TEXT NOT NULL);
"""),
]


class DB:
    """Thin wrapper: one short-lived connection per unit of work, WAL, foreign keys on."""

    def __init__(self, path, migrations):
        self.path = str(path)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._lock = threading.RLock()        # serialize writers inside this process
        self._migrate(migrations)

    def _connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=15000")
        return c

    def _migrate(self, migrations):
        c = self._connect()
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)")
            done = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
            for version, sql in migrations:
                if version in done:
                    continue
                c.executescript("BEGIN;" + sql + "COMMIT;")
                c.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(?,?)", (version, time.time()))
                c.commit()
        finally:
            c.close()

    def schema_version(self):
        return self.scalar("SELECT MAX(version) FROM schema_migrations")

    @contextmanager
    def tx(self):
        """Transaction: commits on success, rolls back on any exception."""
        with self._lock:
            c = self._connect()
            try:
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise
            finally:
                c.close()

    def q(self, sql, args=()):
        c = self._connect()
        try:
            return [dict(r) for r in c.execute(sql, args)]
        finally:
            c.close()

    def one(self, sql, args=()):
        r = self.q(sql, args)
        return r[0] if r else None

    def scalar(self, sql, args=()):
        c = self._connect()
        try:
            r = c.execute(sql, args).fetchone()
            return r[0] if r else None
        finally:
            c.close()

    def x(self, sql, args=()):
        with self.tx() as c:
            cur = c.execute(sql, args)
            return cur.lastrowid if cur.lastrowid else cur.rowcount

    def size_bytes(self):
        return os.path.getsize(self.path) if os.path.exists(self.path) else 0


NAMESPACES = ("hardware", "simulation")


class Store:
    def __init__(self, cfg):
        self.cfg = cfg
        self.system = DB(cfg.system_db, SYSTEM_MIGRATIONS)
        self._ns = {n: DB(cfg.clinical_db(n), CLINICAL_MIGRATIONS) for n in NAMESPACES}

    def ns(self, name) -> DB:
        return self._ns[name]

    # ---- settings (system DB) -------------------------------------------
    def get_setting(self, key, default=None):
        import json
        r = self.system.one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(r["value"]) if r else default

    def set_setting(self, key, value, user_id=None):
        import json
        self.system.x("""INSERT INTO settings(key,value,updated_at,updated_by) VALUES(?,?,?,?)
                         ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at,
                         updated_by=excluded.updated_by""", (key, json.dumps(value), time.time(), user_id))

    def mode(self):
        """Operating mode shown in the UI: 'simulation' (default on a fresh install) or 'hardware'."""
        return self.get_setting("operating_mode", "simulation")
