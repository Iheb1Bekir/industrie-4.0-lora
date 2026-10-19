"""SQLite persistence. All SQL is parameterized. Existing databases are never overwritten (CREATE IF NOT EXISTS)."""
import csv
import os
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients(
  pid TEXT PRIMARY KEY, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL, last_write_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS readings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pid TEXT NOT NULL REFERENCES patients(pid),
  ts INTEGER NOT NULL, hr REAL, spo2 REAL, temp REAL,
  fall INTEGER NOT NULL DEFAULT 0, flags INTEGER NOT NULL DEFAULT 0,
  synthetic INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'api',
  seq INTEGER, uptime INTEGER, received_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_readings_pid_ts ON readings(pid, ts);
CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts);
CREATE UNIQUE INDEX IF NOT EXISTS uq_readings_dup ON readings(pid, seq, uptime) WHERE seq IS NOT NULL;
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pid TEXT NOT NULL REFERENCES patients(pid),
  kind TEXT NOT NULL, severity TEXT NOT NULL, message TEXT NOT NULL,
  created_ts INTEGER NOT NULL, reading_id INTEGER, ack_ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_alerts_pid_kind ON alerts(pid, kind, ack_ts);
"""
READING_COLS = ("id", "pid", "ts", "hr", "spo2", "temp", "fall", "flags", "synthetic", "source", "seq", "uptime")


class Database:
    def __init__(self, path):
        self.path = str(path)
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout = 10000")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def init(self):
        with self.conn() as c:
            c.executescript(SCHEMA)

    # ---- patients -------------------------------------------------------
    def patient(self, pid):
        with self.conn() as c:
            r = c.execute("SELECT * FROM patients WHERE pid=?", (pid,)).fetchone()
        return dict(r) if r else None

    def list_patients(self):
        q = """SELECT p.pid, p.first_seen, p.last_seen,
               (SELECT COUNT(*) FROM readings r WHERE r.pid=p.pid) AS n_readings,
               (SELECT COUNT(*) FROM alerts a WHERE a.pid=p.pid AND a.ack_ts IS NULL) AS active_alerts
               FROM patients p ORDER BY p.pid"""
        with self.conn() as c:
            return [dict(r) for r in c.execute(q)]

    # ---- readings -------------------------------------------------------
    def is_duplicate(self, pid, seq, uptime):
        if seq is None:
            return False
        with self.conn() as c:
            return c.execute("SELECT 1 FROM readings WHERE pid=? AND seq=? AND uptime IS ?", (pid, seq, uptime)).fetchone() is not None

    def insert_reading(self, r, now):
        """Insert reading, create/update patient. Returns reading id, or None if duplicate."""
        with self.conn() as c:
            c.execute("""INSERT INTO patients(pid,first_seen,last_seen,last_write_at) VALUES(?,?,?,?)
                         ON CONFLICT(pid) DO UPDATE SET last_seen=MAX(last_seen,excluded.last_seen), last_write_at=excluded.last_write_at""",
                      (r["pid"], r["ts"], r["ts"], now))
            try:
                cur = c.execute("""INSERT INTO readings(pid,ts,hr,spo2,temp,fall,flags,synthetic,source,seq,uptime,received_at)
                                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (r["pid"], r["ts"], r.get("hr"), r.get("spo2"), r.get("temp"), int(r.get("fall", 0)),
                                 int(r.get("flags", 0)), int(bool(r.get("synthetic"))), r.get("source", "api"),
                                 r.get("seq"), r.get("uptime"), now))
            except sqlite3.IntegrityError:
                c.rollback()
                return None
            return cur.lastrowid

    def latest(self, pid):
        with self.conn() as c:
            r = c.execute("SELECT * FROM readings WHERE pid=? ORDER BY ts DESC, id DESC LIMIT 1", (pid,)).fetchone()
        return dict(r) if r else None

    def history(self, pid, since_ts):
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM readings WHERE pid=? AND ts>=? ORDER BY ts ASC, id ASC", (pid, since_ts))]

    def last_n(self, pid, n):
        with self.conn() as c:
            rows = c.execute("SELECT * FROM readings WHERE pid=? ORDER BY ts DESC, id DESC LIMIT ?", (pid, n)).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ---- alerts ---------------------------------------------------------
    def has_active_alert(self, pid, kind):
        with self.conn() as c:
            return c.execute("SELECT 1 FROM alerts WHERE pid=? AND kind=? AND ack_ts IS NULL", (pid, kind)).fetchone() is not None

    def create_alert(self, pid, kind, severity, message, ts, reading_id=None):
        """Returns new alert id, or None when an unacknowledged alert of the same kind already exists."""
        with self.conn() as c:
            if c.execute("SELECT 1 FROM alerts WHERE pid=? AND kind=? AND ack_ts IS NULL", (pid, kind)).fetchone():
                return None
            return c.execute("INSERT INTO alerts(pid,kind,severity,message,created_ts,reading_id) VALUES(?,?,?,?,?,?)",
                             (pid, kind, severity, message, ts, reading_id)).lastrowid

    def list_alerts(self, status="active", pid=None):
        q, a = "SELECT * FROM alerts WHERE 1=1", []
        if status == "active": q += " AND ack_ts IS NULL"
        elif status == "acknowledged": q += " AND ack_ts IS NOT NULL"
        if pid: q += " AND pid=?"; a.append(pid)
        with self.conn() as c:
            return [dict(r) for r in c.execute(q + " ORDER BY created_ts DESC, id DESC", a)]

    def ack_alert(self, alert_id, ts):
        """Returns (found, already_acked)."""
        with self.conn() as c:
            r = c.execute("SELECT ack_ts FROM alerts WHERE id=?", (alert_id,)).fetchone()
            if not r: return False, False
            if r["ack_ts"] is not None: return True, True
            c.execute("UPDATE alerts SET ack_ts=? WHERE id=?", (ts, alert_id))
            return True, False

    # ---- retention ------------------------------------------------------
    def export_and_prune(self, export_dir, now, days=30):
        """Export readings older than `days` to CSV, verify the file, and only then delete them.
        Returns (exported_rows, csv_path_or_None). Nothing is deleted if export or verification fails."""
        cutoff = int(now - days * 86400)
        with self.conn() as c:
            rows = c.execute("SELECT * FROM readings WHERE ts<? ORDER BY ts, id", (cutoff,)).fetchall()
        if not rows:
            return 0, None
        os.makedirs(export_dir, exist_ok=True)
        path = os.path.join(export_dir, f"readings_before_{cutoff}.csv")
        tmp = path + ".tmp"
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(rows[0].keys())
            for r in rows: w.writerow(list(r))
            f.flush(); os.fsync(f.fileno())
        with open(tmp, newline="") as f:
            n = sum(1 for _ in csv.reader(f)) - 1
        if n != len(rows):
            os.remove(tmp)
            raise IOError("CSV verification failed; nothing deleted")
        os.replace(tmp, path)
        ids = [r["id"] for r in rows]
        with self.conn() as c:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                c.execute(f"DELETE FROM readings WHERE id IN ({','.join('?' * len(chunk))})", chunk)
        return len(rows), path
