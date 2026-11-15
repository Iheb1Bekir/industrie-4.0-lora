"""Alert management: classification, lifecycle, de-duplication, notification, escalation.

Categories : threshold | fall | predictive | device | sensor | network | data_quality
Lifecycle  : new -> acknowledged -> assigned -> escalated -> resolved | false_positive  (see TRANSITIONS)
De-dup     : at most ONE open alert per (patient or device, type); repeats only bump trigger_count.
Thresholds are configurable engineering demonstration values (per patient overrides allowed). The engine
describes measurements; it never states a diagnosis.
"""
import json
import smtplib
import time
from email.message import EmailMessage

from .security import RateLimiter

OPEN = ("new", "acknowledged", "assigned", "escalated")
# action -> (allowed from-states, to-state, permission)
TRANSITIONS = {
    "acknowledge": (("new", "escalated"), "acknowledged", "alerts.acknowledge"),
    "assign": (OPEN, "assigned", "alerts.assign"),
    "escalate": (("new", "acknowledged", "assigned"), "escalated", "alerts.escalate"),
    "resolve": (OPEN, "resolved", "alerts.resolve"),
    "false_positive": (OPEN, "false_positive", "alerts.false_positive"),
    "note": (OPEN + ("resolved", "false_positive"), None, "alerts.acknowledge"),
}
TYPE_LABEL = {
    "HIGH_HR": "High heart rate", "LOW_HR": "Low heart rate", "LOW_SPO2": "Low SpO2", "HIGH_TEMP": "High temperature",
    "LOW_TEMP": "Low temperature", "FALL": "Fall detected", "PREDICTED_DETERIORATION": "Predictive warning",
    "DEVICE_OFFLINE": "Device offline", "SENSOR_FAULT": "Sensor malfunction", "IMPLAUSIBLE_VALUE": "Implausible value",
    "NETWORK_DEGRADED": "Network degraded", "AUTH_FAILURES": "Rejected radio frames",
}
CAREGIVER_TYPES = {"FALL", "HIGH_HR", "LOW_HR", "LOW_SPO2", "DEVICE_OFFLINE"}


def effective_thresholds(svc, patient):
    t = dict(svc.cfg.thresholds)
    t.update(svc.store.get_setting("thresholds", {}) or {})
    if patient and patient.get("thresholds"):
        try:
            t.update(json.loads(patient["thresholds"]))
        except ValueError:
            pass
    return t


def classify(m, thr):
    """Immediate (non-predictive) conditions of one measurement. Returns [(type, category, severity, message)].
    None values are 'unknown' and never produce (or clear) a physiological alert."""
    out = []
    hr, spo2, temp = m.get("heartRate"), m.get("spO2"), m.get("temperature")
    if hr is not None and hr > thr["hr_high"]:
        out.append(("HIGH_HR", "threshold", "critical" if hr > thr["hr_high"] + 20 else "high",
                    f"Heart rate {hr:.0f} bpm above the configured limit of {thr['hr_high']:g} bpm"))
    if hr is not None and hr < thr["hr_low"]:
        out.append(("LOW_HR", "threshold", "high", f"Heart rate {hr:.0f} bpm below the configured limit of {thr['hr_low']:g} bpm"))
    if spo2 is not None and spo2 < thr["spo2_low"]:
        out.append(("LOW_SPO2", "threshold", "critical" if spo2 < thr["spo2_low"] - 4 else "high",
                    f"SpO2 {spo2:.0f} % below the configured limit of {thr['spo2_low']:g} %"))
    if temp is not None and temp >= thr["temp_high"]:
        out.append(("HIGH_TEMP", "threshold", "high" if temp >= thr["temp_high"] + 1.5 else "warning",
                    f"Temperature {temp:.1f} C at or above the configured limit of {thr['temp_high']:g} C"))
    if temp is not None and temp < thr["temp_low"]:
        out.append(("LOW_TEMP", "threshold", "warning", f"Temperature {temp:.1f} C below the configured limit of {thr['temp_low']:g} C"))
    if m.get("fallDetected"):
        out.append(("FALL", "fall", "critical", "Fall detected by the patient device"))
    return out


def device_alert_level(m, thr):
    """Same 0..3 scale as the FLoRa model and the firmware: 0 normal, 1 warning, 2 critical, 3 fall."""
    if m.get("fallDetected"):
        return 3
    hr, spo2, temp = m.get("heartRate"), m.get("spO2"), m.get("temperature")
    if (hr is not None and (hr > thr["hr_high"] or hr < thr["hr_low"])) or (spo2 is not None and spo2 < thr["spo2_low"]) \
            or (temp is not None and temp >= thr["temp_high"]):
        return 2
    if (hr is not None and hr > thr["hr_warn"]) or (spo2 is not None and spo2 < thr["spo2_warn"]) \
            or (temp is not None and temp >= thr["temp_warn"]):
        return 1
    return 0


class AlertEngine:
    def __init__(self, svc):
        self.svc = svc
        self.limiter = RateLimiter()

    # ---- creation ------------------------------------------------------------------------------------
    def raise_alert(self, ns, atype, category, severity, message, patient_id=None, device_id=None,
                    measurement_id=None, prediction_id=None, sim_session_id=None, now=None):
        """Create an alert unless an open one of the same type exists for the same patient/device.
        Returns the new alert row (dict) or None when de-duplicated."""
        db, now = self.svc.store.ns(ns), self.svc.clock() if now is None else now
        with db.tx() as c:
            if patient_id is not None:
                row = c.execute(f"SELECT id FROM alerts WHERE patient_id=? AND type=? AND status IN ({','.join('?' * len(OPEN))})",
                                (patient_id, atype, *OPEN)).fetchone()
            else:
                row = c.execute(f"SELECT id FROM alerts WHERE patient_id IS NULL AND device_id IS ? AND type=? AND status IN ({','.join('?' * len(OPEN))})",
                                (device_id, atype, *OPEN)).fetchone()
            if row:
                c.execute("UPDATE alerts SET last_trigger_at=?, trigger_count=trigger_count+1 WHERE id=?", (now, row[0]))
                return None
            aid = c.execute("""INSERT INTO alerts(patient_id,device_id,type,category,severity,message,measurement_id,
                               prediction_id,created_at,last_trigger_at,sim_session_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (patient_id, device_id, atype, category, severity, message, measurement_id, prediction_id,
                             now, now, sim_session_id)).lastrowid
            c.execute("INSERT INTO alert_events(alert_id,ts,action,to_status) VALUES(?,?,?,?)", (aid, now, "created", "new"))
        alert = db.one("SELECT * FROM alerts WHERE id=?", (aid,))
        self.svc.broker.publish({"type": "alert", "ns": ns, "patient_id": patient_id, "data": self.public(alert)})
        self._notify(ns, alert, "New alert")
        return alert

    @staticmethod
    def public(a):
        d = dict(a)
        d["label"] = TYPE_LABEL.get(a["type"], a["type"])
        return d

    # ---- lifecycle -----------------------------------------------------------------------------------
    def act(self, ns, alert_id, action, user, perms, note=None, assignee=None):
        """Apply a lifecycle action. Returns (alert, None) or (None, (message, code, http_status))."""
        if action not in TRANSITIONS:
            return None, ("unknown action", "E_VALIDATION", 400)
        allowed_from, to, perm = TRANSITIONS[action]
        if perm not in perms:
            return None, ("you do not have permission for this alert action", "E_FORBIDDEN", 403)
        db, now = self.svc.store.ns(ns), self.svc.clock()
        with db.tx() as c:
            a = c.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
            if not a:
                return None, ("unknown alert", "E_NOT_FOUND", 404)
            if a["status"] not in allowed_from:
                return None, (f"action '{action}' is not allowed from status '{a['status']}'", "E_STATE", 409)
            sets, args = [], []
            if action == "acknowledge":
                sets += ["acknowledged_at=?", "acknowledged_by=?"]; args += [now, user["id"]]
            elif action == "assign":
                if not isinstance(assignee, int):
                    return None, ("assignee (user id) is required", "E_VALIDATION", 400)
                sets += ["assigned_to=?"]; args += [assignee]
            elif action == "escalate":
                sets += ["escalated_at=?", "escalation_level=escalation_level+1"]; args += [now]
            elif action in ("resolve", "false_positive"):
                sets += ["resolved_at=?", "resolved_by=?"]; args += [now, user["id"]]
            if note:
                sets += ["note=?"]; args += [str(note)[:1000]]
            if to:
                sets += ["status=?"]; args += [to]
            if sets:
                c.execute(f"UPDATE alerts SET {', '.join(sets)} WHERE id=?", (*args, alert_id))
            c.execute("INSERT INTO alert_events(alert_id,ts,user_id,action,from_status,to_status,note) VALUES(?,?,?,?,?,?,?)",
                      (alert_id, now, user["id"], action, a["status"], to or a["status"], (note or None) and str(note)[:1000]))
        alert = db.one("SELECT * FROM alerts WHERE id=?", (alert_id,))
        self.svc.broker.publish({"type": "alert_update", "ns": ns, "patient_id": alert["patient_id"], "data": self.public(alert)})
        if action == "escalate":
            self._notify(ns, alert, "Alert escalated", staff_only=True)
        return alert, None

    def system_resolve(self, ns, patient_id, device_id, atype, note):
        """Automatic resolution by the platform (e.g. device came back online)."""
        db, now = self.svc.store.ns(ns), self.svc.clock()
        col, val = ("device_id", device_id) if device_id is not None else ("patient_id", patient_id)
        rows = db.q(f"SELECT id, status FROM alerts WHERE type=? AND {col}=? AND status IN ({','.join('?' * len(OPEN))})",
                    (atype, val, *OPEN))
        for r in rows:
            with db.tx() as c:
                c.execute("UPDATE alerts SET status='resolved', resolved_at=?, note=? WHERE id=?", (now, note, r["id"]))
                c.execute("INSERT INTO alert_events(alert_id,ts,action,from_status,to_status,note) VALUES(?,?,?,?,?,?)",
                          (r["id"], now, "auto_resolve", r["status"], "resolved", note))
            a = db.one("SELECT * FROM alerts WHERE id=?", (r["id"],))
            self.svc.broker.publish({"type": "alert_update", "ns": ns, "patient_id": a["patient_id"], "data": self.public(a)})
        return len(rows)

    def escalate_overdue(self, ns, now=None):
        """Escalate critical/high alerts that nobody acknowledged within ESCALATE_AFTER_S."""
        db, now = self.svc.store.ns(ns), self.svc.clock() if now is None else now
        rows = db.q("SELECT * FROM alerts WHERE status='new' AND severity IN ('critical','high') AND created_at<=?",
                    (now - self.svc.cfg.ESCALATE_AFTER_S,))
        for a in rows:
            with db.tx() as c:
                c.execute("UPDATE alerts SET status='escalated', escalated_at=?, escalation_level=escalation_level+1 WHERE id=?",
                          (now, a["id"]))
                c.execute("INSERT INTO alert_events(alert_id,ts,action,from_status,to_status,note) VALUES(?,?,?,?,?,?)",
                          (a["id"], now, "auto_escalate", "new", "escalated",
                           f"not acknowledged within {self.svc.cfg.ESCALATE_AFTER_S} s"))
            a = db.one("SELECT * FROM alerts WHERE id=?", (a["id"],))
            self.svc.broker.publish({"type": "alert_update", "ns": ns, "patient_id": a["patient_id"], "data": self.public(a)})
            self._notify(ns, a, "Unacknowledged alert escalated", staff_only=True)
        return len(rows)

    # ---- notifications -------------------------------------------------------------------------------
    def recipients(self, ns, alert, staff_only=False):
        """[(user_row, is_caregiver)] authorized to be notified about this alert."""
        db, sysdb, now = self.svc.store.ns(ns), self.svc.store.system, self.svc.clock()
        ids, caregivers = set(), set()
        if alert["patient_id"] is not None:
            p = db.one("SELECT primary_doctor_id FROM patients WHERE id=?", (alert["patient_id"],))
            if p and p["primary_doctor_id"]:
                ids.add(p["primary_doctor_id"])
            ids |= {r["user_id"] for r in db.q("SELECT user_id FROM staff_assignments WHERE patient_id=?", (alert["patient_id"],))}
            if not staff_only and alert["type"] in CAREGIVER_TYPES and alert["severity"] in ("critical", "high"):
                caregivers = {r["user_id"] for r in db.q(
                    """SELECT user_id FROM caregiver_links WHERE patient_id=? AND notify=1 AND revoked_at IS NULL
                       AND (expires_at IS NULL OR expires_at>?)""", (alert["patient_id"], now))}
        else:  # device/network alerts without a patient go to administrators
            ids |= {r["id"] for r in sysdb.q("SELECT id FROM users WHERE is_admin=1 AND is_active=1")}
        out = []
        for uid in ids | caregivers:
            u = sysdb.one("SELECT * FROM users WHERE id=? AND is_active=1", (uid,))
            if u:
                out.append((u, uid in caregivers and uid not in ids))
        return out

    def _notify(self, ns, alert, title, staff_only=False):
        db, now = self.svc.store.ns(ns), self.svc.clock()
        label = TYPE_LABEL.get(alert["type"], alert["type"])
        pname = None
        if alert["patient_id"] is not None:
            p = db.one("SELECT full_name, code FROM patients WHERE id=?", (alert["patient_id"],))
            pname = f"{p['full_name']} ({p['code']})" if p else None
        for u, is_caregiver in self.recipients(ns, alert, staff_only):
            # caregivers get a deliberately generic text: no measurement values, no clinical wording
            body = (f"{label} for {pname}. The care team has been notified." if is_caregiver
                    else f"{label}{' - ' + pname if pname else ''}: {alert['message']}")
            ok = self.limiter.allow((u["id"], "in_app"), self.svc.cfg.NOTIFY_MAX_PER_MIN, 60, now)
            nid = db.x("INSERT INTO notifications(user_id,alert_id,channel,ts,status,title,body) VALUES(?,?,?,?,?,?,?)",
                       (u["id"], alert["id"], "in_app", now, "sent" if ok else "suppressed", title, body))
            if ok:
                self.svc.broker.publish({"type": "notification", "ns": ns, "user_id": u["id"], "patient_id": alert["patient_id"],
                                         "data": {"id": nid, "title": title, "body": body, "severity": alert["severity"],
                                                  "alert_id": alert["id"], "ts": now}})
            if self.svc.cfg.SMTP_HOST and u.get("email") and alert["severity"] in ("critical", "high") and ns == "hardware":
                status, detail = self._email(u["email"], title, body) if self.limiter.allow(
                    (u["id"], "email"), self.svc.cfg.NOTIFY_MAX_PER_MIN, 60, now) else ("suppressed", "rate limit")
                db.x("INSERT INTO notifications(user_id,alert_id,channel,ts,status,title,body) VALUES(?,?,?,?,?,?,?)",
                     (u["id"], alert["id"], "email", now, status, title, detail))

    def _email(self, to, title, body):
        """SMTP adapter (STARTTLS). Only used when RPM_SMTP_HOST is configured. Returns (status, detail)."""
        cfg = self.svc.cfg
        try:
            msg = EmailMessage()
            msg["Subject"], msg["From"], msg["To"] = f"[RPM] {title}", cfg.SMTP_FROM or cfg.SMTP_USER, to
            msg.set_content(body + "\n\nOpen the monitoring dashboard for details. Do not reply to this message.")
            with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=10) as s:
                s.starttls()
                if cfg.SMTP_USER:
                    s.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
                s.send_message(msg)
            return "sent", ""
        except Exception as e:  # noqa: BLE001 - delivery failure is recorded, never raised
            return "failed", str(e)[:200]
