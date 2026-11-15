"""REST API v1 (/api/v1). Every protected route re-derives the user's role and patient scope on the server.
Errors: {"error": "...", "code": "E_..."}. See docs/API_DOCUMENTATION.md."""
import hmac
import json
import math
import os
import platform
import queue
import shutil
import sys
import time

from flask import Blueprint, Response, current_app, g, jsonify, request, stream_with_context

from . import reports
from .alert_engine import CAREGIVER_TYPES, OPEN, TYPE_LABEL, AlertEngine, classify, effective_thresholds
from .events import sse_format
from .security import (COOKIE, AuthFailure, err, load_session, password_problem, permissions_of, public_user, require,
                       totp_uri, totp_verify, unwrap, wrap)
from .services import DomainError, validate_thresholds

bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")
RANGES = {"15m": 900, "1h": 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}
SEV_ORDER = {"critical": 4, "high": 3, "warning": 2, "info": 1}


def S():
    return current_app.config["SERVICES"]


def NS():
    return S().store.mode()


def body():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise DomainError("JSON object expected", "E_BAD_JSON", 400)
    return d


def paging():
    try:
        page = max(1, int(request.args.get("page", 1)))
        per = min(200, max(1, int(request.args.get("per_page", 50))))
    except ValueError:
        raise DomainError("page and per_page must be integers")
    return page, per, (page - 1) * per


@bp.errorhandler(DomainError)
def _domain(e):
    return err(e.message, e.code, e.status)


@bp.errorhandler(AuthFailure)
def _authfail(e):
    return err(e.message, e.code, e.status)


def patient_or_404(pid, audit_view=False):
    svc, ns = S(), NS()
    if pid not in svc.visible_patient_ids(g.user, ns):
        svc.audit.log("patient.access_denied", g.user, "patient", pid, ns, outcome="denied")
        raise DomainError("unknown patient", "E_NOT_FOUND", 404)
    p = svc.store.ns(ns).one("SELECT * FROM patients WHERE id=?", (pid,))
    if audit_view:
        svc.audit.log("patient.view", g.user, "patient", pid, ns)
    return p


# ======================================================================== authentication
def _set_cookie(resp, token):
    cfg = S().cfg
    resp.set_cookie(COOKIE, token, max_age=cfg.SESSION_ABSOLUTE_S, httponly=True, secure=cfg.COOKIE_SECURE,
                    samesite="Strict", path="/")
    return resp


def _me(user, session):
    return {"user": public_user(user), "permissions": sorted(permissions_of(user)), "csrf_token": session["csrf_token"],
            "mode": NS(), "session_expires_at": session["expires_at"], "idle_timeout_s": S().cfg.SESSION_IDLE_S}


@bp.post("/auth/login")
def login():
    d = body()
    svc = S()
    token, csrf, user = svc.auth.login(d.get("username"), d.get("password"), d.get("otp"), request.remote_addr,
                                       request.headers.get("User-Agent", ""))
    session = svc.auth.session(token, request.headers.get("User-Agent", ""))[0]
    return _set_cookie(jsonify(_me(user, session)), token)


@bp.post("/auth/logout")
@require()
def logout():
    svc = S()
    svc.auth.logout(request.cookies.get(COOKIE))
    svc.audit.log("auth.logout", g.user)
    resp = jsonify({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@bp.get("/auth/me")
@require()
def me():
    return jsonify(_me(g.user, g.session))


@bp.post("/auth/password")
@require()
def change_password():
    d, svc = body(), S()
    from .security import verify_password
    if not verify_password(g.user["password_hash"], d.get("current_password") or ""):
        svc.audit.log("auth.password_change", g.user, outcome="denied")
        return err("current password is incorrect", "E_AUTH", 403)
    problem = password_problem(d.get("new_password"), svc.cfg, g.user["username"])
    if problem:
        return err(problem, "E_VALIDATION", 400)
    svc.auth.set_password(g.user["id"], d["new_password"], keep_session_token=request.cookies.get(COOKIE))
    svc.audit.log("auth.password_change", g.user)
    return jsonify({"ok": True})


@bp.post("/auth/reset/complete")
def reset_complete():
    d, svc = body(), S()
    if not svc.auth.limiter.allow(("reset", request.remote_addr), 5, 60, svc.clock()):
        return err("too many attempts", "E_RATE", 429)
    svc.auth.complete_reset(d.get("token"), d.get("new_password"))
    return jsonify({"ok": True})


@bp.post("/auth/totp/enroll")
@require()
def totp_enroll():
    svc = S()
    if g.user["role"] != "doctor":
        return err("two-factor authentication is offered to doctor accounts", "E_FORBIDDEN", 403)
    secret = os.urandom(20)
    svc.store.system.x("UPDATE users SET totp_secret_enc=?, totp_enabled=0 WHERE id=?",
                       (wrap(svc.cfg.MASTER_KEY, secret, b"totp"), g.user["id"]))
    b32, uri = totp_uri(secret, g.user["username"])
    return jsonify({"secret_base32": b32, "otpauth_uri": uri})


@bp.post("/auth/totp/confirm")
@require()
def totp_confirm():
    svc, d = S(), body()
    if not g.user["totp_secret_enc"]:
        return err("start enrollment first", "E_STATE", 409)
    if not totp_verify(unwrap(svc.cfg.MASTER_KEY, g.user["totp_secret_enc"], b"totp"), d.get("otp"), svc.clock()):
        return err("code is not valid", "E_AUTH", 400)
    svc.store.system.x("UPDATE users SET totp_enabled=1 WHERE id=?", (g.user["id"],))
    svc.audit.log("auth.totp_enabled", g.user)
    return jsonify({"ok": True})


@bp.post("/auth/totp/disable")
@require()
def totp_disable():
    svc, d = S(), body()
    from .security import verify_password
    if not verify_password(g.user["password_hash"], d.get("current_password") or ""):
        return err("current password is incorrect", "E_AUTH", 403)
    svc.store.system.x("UPDATE users SET totp_enabled=0, totp_secret_enc=NULL WHERE id=?", (g.user["id"],))
    svc.audit.log("auth.totp_disabled", g.user)
    return jsonify({"ok": True})


# ======================================================================== users (administration)
@bp.get("/users")
@require("users.manage")
def users_list():
    return jsonify({"users": [public_user(u) for u in S().store.system.q("SELECT * FROM users ORDER BY role, username")]})


@bp.get("/staff")
@require("patients.read")
def staff_directory():
    """Minimal directory (id, name, role) for assignment pickers. No contact details."""
    rows = S().store.system.q("SELECT id, username, full_name, role FROM users WHERE is_active=1 AND role IN ('doctor','assistant','caregiver') ORDER BY full_name")
    if "caregivers.manage" not in g.perms:
        rows = [r for r in rows if r["role"] != "caregiver"]
    return jsonify({"staff": rows})


@bp.post("/users")
@require("users.manage")
def users_create():
    d, svc = body(), S()
    try:
        uid = svc.auth.create_user(d.get("username"), d.get("password"), d.get("role"), d.get("full_name"),
                                   is_admin=bool(d.get("is_admin")), email=d.get("email") or None, phone=d.get("phone") or None,
                                   must_change=True)
    except ValueError as e:
        return err(str(e), "E_VALIDATION", 400)
    svc.audit.log("user.create", g.user, "user", uid, detail={"role": d.get("role"), "is_admin": bool(d.get("is_admin"))})
    return jsonify({"user": public_user(svc.auth.user(uid))}), 201


@bp.patch("/users/<int:uid>")
@require("users.manage")
def users_update(uid):
    d, svc = body(), S()
    u = svc.auth.user(uid)
    if not u:
        return err("unknown user", "E_NOT_FOUND", 404)
    sets, args = [], []
    for k in ("full_name", "email", "phone"):
        if k in d:
            sets.append(f"{k}=?"); args.append((str(d[k])[:120] if d[k] else None))
    if "is_active" in d:
        if uid == g.user["id"] and not d["is_active"]:
            return err("you cannot deactivate your own account", "E_STATE", 409)
        sets.append("is_active=?"); args.append(int(bool(d["is_active"])))
    if d.get("unlock"):
        sets += ["failed_logins=0", "locked_until=0"]
    if sets:
        svc.store.system.x(f"UPDATE users SET {', '.join(sets)} WHERE id=?", (*args, uid))
        if "is_active" in d and not d["is_active"]:
            svc.store.system.x("UPDATE sessions SET revoked=1 WHERE user_id=?", (uid,))
    svc.audit.log("user.update", g.user, "user", uid, detail=sorted(k for k in d if k in ("full_name", "email", "phone", "is_active", "unlock")))
    return jsonify({"user": public_user(svc.auth.user(uid))})


@bp.post("/users/<int:uid>/reset-token")
@require("users.manage")
def users_reset_token(uid):
    svc = S()
    if not svc.auth.user(uid):
        return err("unknown user", "E_NOT_FOUND", 404)
    token = svc.auth.issue_reset(uid, g.user["id"])
    svc.audit.log("user.reset_token_issued", g.user, "user", uid)
    return jsonify({"reset_token": token, "expires_in_s": svc.cfg.RESET_TOKEN_TTL_S,
                    "note": "Hand this one-time token to the user through a trusted channel. It is shown only once."})


# ======================================================================== system / mode
def _counters(db):
    return {r["name"]: r["value"] for r in db.q("SELECT name, value FROM network_counters")}


def _pdr(c):
    valid, lost = c.get("valid", 0), c.get("lost_estimate", 0)
    return None if valid + lost == 0 else round(valid / (valid + lost), 4)


@bp.get("/system/status")
@require()
def system_status():
    svc, ns = S(), NS()
    sim = svc.simulator.status() if svc.simulator else {"state": "unavailable"}
    return jsonify({"mode": ns, "server_time": svc.clock(), "simulation": {"state": sim["state"], "session_id": sim.get("session_id"),
                                                                           "scenario": (sim.get("config") or {}).get("scenario")},
                    "model": {k: svc.predictor.status()[k] for k in ("loaded", "model_name", "model_version", "health")},
                    "environment": svc.cfg.ENV, "stale_after_s": svc.cfg.STALE_AFTER_S})


@bp.post("/system/mode")
@require("mode.switch")
def system_mode():
    svc, d = S(), body()
    mode = d.get("mode")
    if mode not in ("simulation", "hardware"):
        return err("mode must be 'simulation' or 'hardware'", "E_VALIDATION", 400)
    prev = svc.store.mode()
    if mode == "hardware" and svc.simulator and svc.simulator.state != "stopped":
        svc.simulator.stop(g.user)       # no synthetic frame may be produced while in hardware mode
    svc.store.set_setting("operating_mode", mode, g.user["id"])
    svc.audit.log("system.mode_switch", g.user, detail={"from": prev, "to": mode})
    svc.broker.publish({"type": "system", "ns": None, "patient_id": None, "data": {"mode": mode}})
    return jsonify({"mode": mode})


@bp.get("/system/health")
@require("system.read")
def system_health():
    svc = S()
    rss = None
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) * 1024
    except OSError:
        pass
    du = shutil.disk_usage(svc.cfg.DATA_DIR)
    ok, n, bad = svc.audit.verify()
    hw = svc.store.ns("hardware")
    return jsonify({
        "uptime_s": round(svc.clock() - svc.started_at), "python": sys.version.split()[0], "platform": platform.platform(),
        "machine": platform.machine(), "cpu_count": os.cpu_count(),
        "load_avg": list(os.getloadavg()) if hasattr(os, "getloadavg") else None, "process_rss_bytes": rss,
        "disk_free_bytes": du.free, "disk_total_bytes": du.total,
        "databases": {"system": {"bytes": svc.store.system.size_bytes(), "schema": svc.store.system.schema_version()},
                      "hardware": {"bytes": hw.size_bytes(), "schema": hw.schema_version(),
                                   "measurements": hw.scalar("SELECT COUNT(*) FROM measurements")},
                      "simulation": {"bytes": svc.store.ns("simulation").size_bytes(),
                                     "measurements": svc.store.ns("simulation").scalar("SELECT COUNT(*) FROM measurements")}},
        "realtime": {"subscribers": svc.broker.subscriber_count(), "published": svc.broker.published, "dropped": svc.broker.dropped},
        "model": svc.predictor.status(), "audit_chain": {"ok": ok, "entries": n, "first_bad_id": bad},
        "hardware_gateway": {"ingest_token_configured": bool(svc.cfg.GATEWAY_INGEST_TOKEN),
                             "last_frame_at": hw.scalar("SELECT MAX(ts) FROM network_events"),
                             "online_devices": hw.scalar("SELECT COUNT(*) FROM devices WHERE online=1")},
        "notifications": {"email": "configured (delivery must be verified by the operator)" if svc.cfg.SMTP_HOST else "not configured",
                          "sms": "no provider adapter installed", "in_app": "active", "browser": "active (per-browser permission)"},
    })


@bp.get("/settings/thresholds")
@require("patients.read")
def thresholds_get():
    return jsonify({"thresholds": effective_thresholds(S(), None),
                    "note": "Engineering demonstration thresholds - configurable, not universal medical rules."})


@bp.put("/settings/thresholds")
@require("settings.write")
def thresholds_put():
    svc = S()
    t = validate_thresholds(body())
    cur = svc.store.get_setting("thresholds", {}) or {}
    cur.update(t)
    svc.store.set_setting("thresholds", cur, g.user["id"])
    svc.audit.log("settings.thresholds", g.user, detail=sorted(t))
    return jsonify({"thresholds": effective_thresholds(svc, None)})


# ======================================================================== patients
def _summary(db, p, now, svc, with_location):
    dev = db.one("SELECT id, serial, label, online, last_seen_at, last_battery, last_rssi, last_snr, last_hop_count, status FROM devices WHERE patient_id=? AND status IN ('active','disabled') ORDER BY status LIMIT 1", (p["id"],))
    m = db.one("""SELECT id, ts, heart_rate, spo2, temperature, fall_detected, alert_level, quality, hop_count, routing_mode, battery
                  FROM measurements WHERE patient_id=? ORDER BY ts DESC, id DESC LIMIT 1""", (p["id"],))
    alerts = db.q(f"SELECT severity, category, type FROM alerts WHERE patient_id=? AND status IN ({','.join('?' * len(OPEN))})", (p["id"], *OPEN))
    pred = db.one("SELECT ts, status, risk_category, score, probability, model_version FROM predictions WHERE patient_id=? ORDER BY id DESC LIMIT 1", (p["id"],))
    thr = effective_thresholds(svc, p)
    if m:
        m["age_s"] = round(now - m["ts"], 1)
        m["stale"] = m["age_s"] > svc.cfg.STALE_AFTER_S
        m["abnormal"] = bool(classify({"heartRate": m["heart_rate"], "spO2": m["spo2"], "temperature": m["temperature"],
                                       "fallDetected": m["fall_detected"]}, thr)) and not m["stale"]
    non_pred = [a for a in alerts if a["category"] != "predictive"]
    top = max((SEV_ORDER[a["severity"]] for a in non_pred), default=0)
    if not dev:
        state = "no_device"
    elif not m:
        state = "no_data"
    elif top >= 3:
        state = "critical"
    elif not dev["online"]:
        state = "offline"
    elif top == 2:
        state = "warning"
    elif any(a["category"] == "predictive" for a in alerts):
        state = "prediction"
    elif m["stale"]:
        state = "stale"
    else:
        state = "normal"
    out = {"id": p["id"], "code": p["code"], "full_name": p["full_name"], "status": p["status"], "is_synthetic": p["is_synthetic"],
           "primary_doctor_id": p["primary_doctor_id"], "device": dev, "latest": m, "state": state,
           "open_alerts": len(alerts), "open_alert_types": sorted({a["type"] for a in alerts}), "prediction": pred, "location": None}
    if with_location:
        out["location"] = _location(db, p["id"], now, svc)
    return out


def _location(db, pid, now, svc):
    """Last known AUTHORIZED location. Real (hardware) locations need an unrevoked location consent."""
    loc = db.one("SELECT ts, lat, lon, accuracy_m, source, consent_id FROM locations WHERE patient_id=? ORDER BY ts DESC, id DESC LIMIT 1", (pid,))
    if not loc:
        return None
    if loc["source"] != "simulated":
        c = db.one("SELECT 1 FROM consent_records WHERE id=? AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?)",
                   (loc["consent_id"], now))
        if not c:
            return None
    loc.pop("consent_id")
    loc["age_s"] = round(now - loc["ts"])
    loc["is_current"] = loc["age_s"] <= 300
    return loc


@bp.get("/patients")
@require("patients.read")
def patients_list():
    svc, ns = S(), NS()
    db, now = svc.store.ns(ns), svc.clock()
    ids = svc.visible_patient_ids(g.user, ns)
    rows = [p for p in db.q("SELECT * FROM patients ORDER BY id") if p["id"] in ids]
    return jsonify({"mode": ns, "patients": [_summary(db, p, now, svc, "location.read" in g.perms) for p in rows]})


@bp.post("/patients")
@require("patients.register")
def patients_create():
    svc, ns = S(), NS()
    p = svc.register_patient(ns, body(), g.user)
    svc.audit.log("patient.create", g.user, "patient", p["id"], ns)
    return jsonify({"patient": p}), 201


def _patient_detail(svc, ns, p):
    db, now = svc.store.ns(ns), svc.clock()
    out = _summary(db, p, now, svc, "location.read" in g.perms)
    doctor = svc.auth.user(p["primary_doctor_id"]) if p["primary_doctor_id"] else None
    out.update(date_of_birth=p["date_of_birth"], sex=p["sex"], phone=p["phone"], address=p["address"], created_at=p["created_at"],
               thresholds=effective_thresholds(svc, p), threshold_overrides=json.loads(p["thresholds"]) if p["thresholds"] else {},
               primary_doctor=None if not doctor else {"id": doctor["id"], "full_name": doctor["full_name"]},
               staff=[], caregivers=[], devices=[])
    names = {u["id"]: u for u in svc.store.system.q("SELECT id, full_name, role, username FROM users")}
    for r in db.q("SELECT user_id, role, assigned_at FROM staff_assignments WHERE patient_id=?", (p["id"],)):
        u = names.get(r["user_id"])
        if u:
            out["staff"].append({"user_id": u["id"], "full_name": u["full_name"], "role": u["role"], "assigned_at": r["assigned_at"]})
    if "caregivers.manage" in g.perms:
        for r in db.q("""SELECT l.*, c.granted_by_name, c.note FROM caregiver_links l JOIN consent_records c ON c.id=l.consent_id
                         WHERE l.patient_id=? ORDER BY l.granted_at DESC""", (p["id"],)):
            u = names.get(r["user_id"])
            out["caregivers"].append({"link_id": r["id"], "user_id": r["user_id"], "full_name": u["full_name"] if u else "?",
                                      "relationship": r["relationship"], "can_view_vitals": r["can_view_vitals"],
                                      "can_view_location": r["can_view_location"], "notify": r["notify"], "granted_at": r["granted_at"],
                                      "expires_at": r["expires_at"], "revoked_at": r["revoked_at"], "consent_given_by": r["granted_by_name"],
                                      "active": r["revoked_at"] is None and (r["expires_at"] is None or r["expires_at"] > now)})
    out["devices"] = db.q("""SELECT d.id, d.serial, d.label, d.status, d.online, d.last_seen_at, d.last_battery, a.assigned_at, a.unassigned_at
                             FROM device_assignments a JOIN devices d ON d.id=a.device_id WHERE a.patient_id=? ORDER BY a.assigned_at DESC""", (p["id"],))
    return out


@bp.get("/patients/<int:pid>")
@require("patients.read")
def patient_get(pid):
    svc, ns = S(), NS()
    return jsonify({"mode": ns, "patient": _patient_detail(svc, ns, patient_or_404(pid, audit_view=True))})


@bp.patch("/patients/<int:pid>")
@require("patients.write")
def patient_update(pid):
    svc, ns, d = S(), NS(), body()
    patient_or_404(pid)
    sets, args = [], []
    for k in ("full_name", "date_of_birth", "sex", "phone", "address", "status"):
        if k in d:
            v = d[k] or None
            if k == "full_name" and (not v or not 2 <= len(str(v)) <= 120):
                return err("full_name must have 2-120 characters", "E_VALIDATION", 400)
            if k == "sex" and v not in (None, "F", "M", "X"):
                return err("sex must be F, M or X", "E_VALIDATION", 400)
            if k == "status" and v not in ("active", "discharged"):
                return err("status must be active or discharged", "E_VALIDATION", 400)
            sets.append(f"{k}=?"); args.append(None if v is None else str(v)[:200])
    if "primary_doctor_id" in d:
        if "patients.assign" not in g.perms:
            return err("not allowed to reassign", "E_FORBIDDEN", 403)
        u = svc.auth.user(d["primary_doctor_id"]) if isinstance(d["primary_doctor_id"], int) else None
        if not u or u["role"] != "doctor":
            return err("primary_doctor_id must reference a doctor", "E_VALIDATION", 400)
        sets.append("primary_doctor_id=?"); args.append(u["id"])
    if sets:
        svc.store.ns(ns).x(f"UPDATE patients SET {', '.join(sets)} WHERE id=?", (*args, pid))
        svc.audit.log("patient.update", g.user, "patient", pid, ns, detail=sorted(k for k in d))
    return jsonify({"patient": _patient_detail(svc, ns, svc.store.ns(ns).one("SELECT * FROM patients WHERE id=?", (pid,)))})


@bp.put("/patients/<int:pid>/thresholds")
@require("thresholds.write")
def patient_thresholds(pid):
    svc, ns = S(), NS()
    patient_or_404(pid)
    t = validate_thresholds(body())
    svc.store.ns(ns).x("UPDATE patients SET thresholds=? WHERE id=?", (json.dumps(t) if t else None, pid))
    svc.audit.log("patient.thresholds", g.user, "patient", pid, ns, detail=sorted(t))
    return jsonify({"thresholds": effective_thresholds(svc, svc.store.ns(ns).one("SELECT * FROM patients WHERE id=?", (pid,)))})


def _time_window(svc):
    now = svc.clock()
    rng = request.args.get("range")
    try:
        if rng:
            if rng not in RANGES:
                raise DomainError(f"range must be one of {', '.join(RANGES)}")
            return now - RANGES[rng], now
        t_to = float(request.args.get("to", now))
        t_from = float(request.args.get("from", t_to - 3600))
    except ValueError:
        raise DomainError("from/to must be epoch seconds")
    if not math.isfinite(t_from) or not math.isfinite(t_to) or t_from >= t_to or t_to - t_from > 366 * 86400:
        raise DomainError("invalid time window")
    return t_from, t_to


@bp.get("/patients/<int:pid>/measurements")
@require("patients.read")
def patient_measurements(pid):
    svc, ns = S(), NS()
    patient_or_404(pid)
    db = svc.store.ns(ns)
    t_from, t_to = _time_window(svc)
    n = db.scalar("SELECT COUNT(*) FROM measurements WHERE patient_id=? AND ts BETWEEN ? AND ?", (pid, t_from, t_to))
    max_points = 720
    if n <= max_points:
        rows = db.q("""SELECT id, ts, heart_rate, spo2, temperature, fall_detected, alert_level, quality, hop_count, routing_mode,
                       rssi, snr, seq_no, battery FROM measurements WHERE patient_id=? AND ts BETWEEN ? AND ? ORDER BY ts""",
                    (pid, t_from, t_to))
        return jsonify({"patient_id": pid, "from": t_from, "to": t_to, "aggregated": False, "count": n, "points": rows})
    bucket = math.ceil((t_to - t_from) / max_points)
    rows = db.q("""SELECT CAST(ts/? AS INTEGER)*? AS ts, AVG(heart_rate) AS heart_rate, MIN(heart_rate) AS hr_min, MAX(heart_rate) AS hr_max,
                   AVG(spo2) AS spo2, MIN(spo2) AS spo2_min, AVG(temperature) AS temperature, MAX(temperature) AS temp_max,
                   MAX(fall_detected) AS fall_detected, COUNT(*) AS n FROM measurements
                   WHERE patient_id=? AND ts BETWEEN ? AND ? GROUP BY 1 ORDER BY 1""", (bucket, bucket, pid, t_from, t_to))
    return jsonify({"patient_id": pid, "from": t_from, "to": t_to, "aggregated": True, "bucket_s": bucket, "count": n, "points": rows})


@bp.get("/patients/<int:pid>/predictions")
@require("predictions.read")
def patient_predictions(pid):
    svc, ns = S(), NS()
    patient_or_404(pid)
    t_from, t_to = _time_window(svc)
    rows = svc.store.ns(ns).q("""SELECT id, ts, model_name, model_version, prediction_type, status, score, probability, threshold,
                                 risk_category, explanation, supporting, latency_ms FROM predictions
                                 WHERE patient_id=? AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 500""", (pid, t_from, t_to))
    for r in rows:
        r["explanation"], r["supporting"] = json.loads(r["explanation"] or "[]"), json.loads(r["supporting"] or "{}")
    return jsonify({"patient_id": pid, "predictions": rows})


@bp.get("/patients/<int:pid>/notes")
@require("patients.read")
def notes_list(pid):
    svc, ns = S(), NS()
    patient_or_404(pid)
    kinds = [k for k, perm in (("clinical", "notes.clinical.read"), ("observation", "notes.observation.read")) if perm in g.perms]
    if not kinds:
        return jsonify({"notes": []})
    rows = svc.store.ns(ns).q(f"SELECT * FROM clinical_notes WHERE patient_id=? AND kind IN ({','.join('?' * len(kinds))}) ORDER BY ts DESC LIMIT 200",
                              (pid, *kinds))
    return jsonify({"notes": rows})


@bp.post("/patients/<int:pid>/notes")
@require("patients.read")
def notes_add(pid):
    svc, ns, d = S(), NS(), body()
    patient_or_404(pid)
    kind, text = d.get("kind"), str(d.get("body") or "").strip()
    if kind not in ("clinical", "observation"):
        return err("kind must be 'clinical' or 'observation'", "E_VALIDATION", 400)
    if f"notes.{kind}.write" not in g.perms:
        svc.audit.log("auth.forbidden", g.user, outcome="denied", detail=f"notes.{kind}.write")
        return err("you may not write this kind of note", "E_FORBIDDEN", 403)
    if not 1 <= len(text) <= 4000:
        return err("body must have 1-4000 characters", "E_VALIDATION", 400)
    nid = svc.store.ns(ns).x("INSERT INTO clinical_notes(patient_id,author_id,author_name,author_role,kind,ts,body) VALUES(?,?,?,?,?,?,?)",
                             (pid, g.user["id"], g.user["full_name"], g.user["role"], kind, svc.clock(), text))
    svc.audit.log("note.create", g.user, "patient", pid, ns, detail=kind)
    return jsonify({"id": nid}), 201


@bp.post("/patients/<int:pid>/staff")
@require("patients.assign")
def staff_assign(pid):
    svc, ns, d = S(), NS(), body()
    patient_or_404(pid)
    u = svc.auth.user(d.get("user_id")) if isinstance(d.get("user_id"), int) else None
    if not u or u["role"] not in ("doctor", "assistant") or not u["is_active"]:
        return err("user_id must reference an active doctor or assistant", "E_VALIDATION", 400)
    svc.store.ns(ns).x("INSERT OR IGNORE INTO staff_assignments(patient_id,user_id,role,assigned_at,assigned_by) VALUES(?,?,?,?,?)",
                       (pid, u["id"], u["role"], svc.clock(), g.user["id"]))
    svc.audit.log("patient.staff_assign", g.user, "patient", pid, ns, detail={"user_id": u["id"]})
    return jsonify({"ok": True}), 201


@bp.delete("/patients/<int:pid>/staff/<int:uid>")
@require("patients.assign")
def staff_unassign(pid, uid):
    svc, ns = S(), NS()
    patient_or_404(pid)
    svc.store.ns(ns).x("DELETE FROM staff_assignments WHERE patient_id=? AND user_id=?", (pid, uid))
    svc.audit.log("patient.staff_unassign", g.user, "patient", pid, ns, detail={"user_id": uid})
    return jsonify({"ok": True})


# ---- caregivers + consent
@bp.post("/patients/<int:pid>/caregivers")
@require("caregivers.manage")
def caregiver_grant(pid):
    svc, ns, d = S(), NS(), body()
    patient_or_404(pid)
    u = svc.auth.user(d.get("user_id")) if isinstance(d.get("user_id"), int) else None
    if not u or u["role"] != "caregiver" or not u["is_active"]:
        return err("user_id must reference an active caregiver account", "E_VALIDATION", 400)
    who = str(d.get("consent_given_by") or "").strip()
    if len(who) < 2:
        return err("consent_given_by is required: name of the patient or legal representative who authorized this access", "E_VALIDATION", 400)
    now = svc.clock()
    exp = d.get("expires_at")
    if exp is not None and (isinstance(exp, bool) or not isinstance(exp, (int, float)) or exp <= now):
        return err("expires_at must be a future epoch timestamp", "E_VALIDATION", 400)
    db = svc.store.ns(ns)
    with db.tx() as c:
        cid = c.execute("""INSERT INTO consent_records(patient_id,kind,granted_by_name,recorded_by,scope,granted_at,expires_at,note)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (pid, "caregiver_access", who[:120], g.user["id"],
                         json.dumps({"vitals": bool(d.get("can_view_vitals", True)), "location": bool(d.get("can_view_location", False))}),
                         now, exp, (str(d.get("note"))[:500] if d.get("note") else None))).lastrowid
        lid = c.execute("""INSERT INTO caregiver_links(patient_id,user_id,relationship,consent_id,can_view_vitals,can_view_location,notify,granted_at,expires_at)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (pid, u["id"], (str(d.get("relationship"))[:60] if d.get("relationship") else None), cid,
                         int(bool(d.get("can_view_vitals", True))), int(bool(d.get("can_view_location", False))),
                         int(bool(d.get("notify", True))), now, exp)).lastrowid
    svc.audit.log("caregiver.grant", g.user, "patient", pid, ns, detail={"caregiver_user_id": u["id"], "link_id": lid})
    return jsonify({"link_id": lid, "consent_id": cid}), 201


@bp.delete("/patients/<int:pid>/caregivers/<int:lid>")
@require("caregivers.manage")
def caregiver_revoke(pid, lid):
    svc, ns = S(), NS()
    patient_or_404(pid)
    db, now = svc.store.ns(ns), svc.clock()
    link = db.one("SELECT * FROM caregiver_links WHERE id=? AND patient_id=?", (lid, pid))
    if not link:
        return err("unknown caregiver link", "E_NOT_FOUND", 404)
    with db.tx() as c:
        c.execute("UPDATE caregiver_links SET revoked_at=?, revoked_by=? WHERE id=? AND revoked_at IS NULL", (now, g.user["id"], lid))
        c.execute("UPDATE consent_records SET revoked_at=?, revoked_by=? WHERE id=? AND revoked_at IS NULL", (now, g.user["id"], link["consent_id"]))
    svc.audit.log("caregiver.revoke", g.user, "patient", pid, ns, detail={"link_id": lid})
    return jsonify({"ok": True})


# ---- location
@bp.post("/patients/<int:pid>/location")
@require("location.write")
def location_set(pid):
    """Manual, consented registration of a last known location (no GPS hardware is assumed)."""
    svc, ns, d = S(), NS(), body()
    patient_or_404(pid)
    lat, lon, acc = d.get("lat"), d.get("lon"), d.get("accuracy_m")
    for v, lo, hi, name in ((lat, -90, 90, "lat"), (lon, -180, 180, "lon")):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            return err(f"{name} out of range", "E_VALIDATION", 400)
    if acc is not None and (isinstance(acc, bool) or not isinstance(acc, (int, float)) or not 0 <= acc <= 100000):
        return err("accuracy_m must be 0..100000", "E_VALIDATION", 400)
    who = str(d.get("consent_given_by") or "").strip()
    if len(who) < 2:
        return err("consent_given_by is required: the patient (or legal representative) must agree to location sharing", "E_VALIDATION", 400)
    db, now = svc.store.ns(ns), svc.clock()
    with db.tx() as c:
        row = c.execute("""SELECT id FROM consent_records WHERE patient_id=? AND kind='location_sharing' AND revoked_at IS NULL
                           AND (expires_at IS NULL OR expires_at>?) ORDER BY id DESC LIMIT 1""", (pid, now)).fetchone()
        cid = row[0] if row else c.execute(
            "INSERT INTO consent_records(patient_id,kind,granted_by_name,recorded_by,granted_at) VALUES(?,?,?,?,?)",
            (pid, "location_sharing", who[:120], g.user["id"], now)).lastrowid
        c.execute("INSERT INTO locations(patient_id,ts,lat,lon,accuracy_m,source,consent_id,recorded_by) VALUES(?,?,?,?,?,?,?,?)",
                  (pid, now, float(lat), float(lon), acc, "manual", cid, g.user["id"]))
    svc.audit.log("location.set", g.user, "patient", pid, ns)
    svc.broker.publish({"type": "location", "ns": ns, "patient_id": pid,
                        "data": {"patient_id": pid, "lat": lat, "lon": lon, "ts": now, "source": "manual", "accuracy_m": acc}})
    return jsonify({"ok": True}), 201


@bp.delete("/patients/<int:pid>/location-consent")
@require("location.write")
def location_revoke(pid):
    svc, ns = S(), NS()
    patient_or_404(pid)
    n = svc.store.ns(ns).x("UPDATE consent_records SET revoked_at=?, revoked_by=? WHERE patient_id=? AND kind='location_sharing' AND revoked_at IS NULL",
                           (svc.clock(), g.user["id"], pid))
    svc.audit.log("location.consent_revoked", g.user, "patient", pid, ns)
    return jsonify({"revoked": n})


# ======================================================================== devices
DEV_COLS = """id, serial, label, hw_model, radio, firmware_version, status, patient_id, is_virtual, last_seen_at, online, last_seq,
              last_rssi, last_snr, last_battery, last_hop_count, last_routing_mode, rx_count, dup_count, lost_estimate,
              auth_fail_count, replay_count, out_of_order_count, latency_ms_sum, latency_n, registered_at, key_version"""


def _device_public(d):
    d = dict(d)
    tot = d["rx_count"] + d["lost_estimate"]
    d["pdr"] = None if tot == 0 else round(d["rx_count"] / tot, 4)
    d["avg_latency_ms"] = None if not d["latency_n"] else round(d.pop("latency_ms_sum") / d["latency_n"], 1)
    d.pop("latency_ms_sum", None)
    return d


def _visible_devices(svc, ns):
    ids = svc.visible_patient_ids(g.user, ns)
    rows = svc.store.ns(ns).q(f"SELECT {DEV_COLS} FROM devices ORDER BY id")
    manage = "devices.manage" in g.perms
    return [_device_public(d) for d in rows if d["patient_id"] in ids or (manage and d["patient_id"] is None)]


@bp.get("/devices")
@require("devices.read")
def devices_list():
    svc, ns = S(), NS()
    return jsonify({"mode": ns, "offline_after_s": svc.monitor.offline_after(ns), "devices": _visible_devices(svc, ns)})


def _provisioning(svc, dev, key):
    return {"device_id": dev["id"], "device_key_hex": key.hex(), "key_version": dev["key_version"], "gateway_id": svc.cfg.GATEWAY_ID,
            "max_hop_count": svc.cfg.MAX_HOP_COUNT,
            "serial_command": f"PROVISION {dev['id']} {dev['patient_id'] or 0} {svc.cfg.GATEWAY_ID} {key.hex()}",
            "warning": "This key is shown ONCE. Enter it on the device over USB serial (docs/ESP32_SETUP.md). Never send it by e-mail or chat."}


@bp.post("/devices")
@require("devices.manage")
def devices_create():
    svc, ns, d = S(), NS(), body()
    if d.get("patient_id") is not None:        # check pairing preconditions BEFORE creating the identity (atomic outcome)
        if not isinstance(d["patient_id"], int):
            return err("patient_id must be an integer", "E_VALIDATION", 400)
        patient_or_404(d["patient_id"])
        other = svc.store.ns(ns).one("SELECT id FROM devices WHERE patient_id=? AND status='active'", (d["patient_id"],))
        if other:
            return err(f"patient already has active device {other['id']}; disable or retire it first", "E_CONFLICT", 409)
    dev, key = svc.register_device(ns, d, g.user, virtual=(ns == "simulation"))
    if d.get("patient_id") is not None:
        dev = svc.pair_device(ns, dev["id"], d["patient_id"], g.user)
    svc.audit.log("device.register", g.user, "device", dev["id"], ns, detail={"serial": dev["serial"], "patient_id": dev["patient_id"]})
    return jsonify({"device": _device_public(svc.store.ns(ns).one(f"SELECT {DEV_COLS} FROM devices WHERE id=?", (dev["id"],))),
                    "provisioning": _provisioning(svc, dev, key)}), 201


@bp.post("/devices/<int:did>/<action>")
@require("devices.manage")
def devices_action(did, action):
    svc, ns = S(), NS()
    db = svc.store.ns(ns)
    dev = db.one("SELECT * FROM devices WHERE id=?", (did,))
    if not dev or (dev["patient_id"] is not None and dev["patient_id"] not in svc.visible_patient_ids(g.user, ns)):
        return err("unknown device", "E_NOT_FOUND", 404)
    extra = {}
    if action == "pair":
        pid = body().get("patient_id")
        if not isinstance(pid, int):
            return err("patient_id is required", "E_VALIDATION", 400)
        patient_or_404(pid)
        svc.pair_device(ns, did, pid, g.user)
    elif action in ("disable", "enable", "replace"):
        svc.set_device_status(ns, did, {"disable": "disabled", "enable": "active", "replace": "replaced"}[action])
    elif action == "rotate-key":
        key = svc.rotate_device_key(ns, did)
        extra["provisioning"] = _provisioning(svc, db.one("SELECT * FROM devices WHERE id=?", (did,)), key)
    else:
        return err("unknown device action", "E_NOT_FOUND", 404)
    svc.audit.log(f"device.{action}", g.user, "device", did, ns)
    svc.broker.publish({"type": "device", "ns": ns, "patient_id": dev["patient_id"], "data": {"device_id": did, "changed": action}})
    return jsonify({"device": _device_public(db.one(f"SELECT {DEV_COLS} FROM devices WHERE id=?", (did,))), **extra})


# ======================================================================== alerts + notifications
def _alert_rows(svc, ns, where="", args=(), limit=200, offset=0):
    db = svc.store.ns(ns)
    ids = svc.visible_patient_ids(g.user, ns)
    rows = db.q(f"SELECT * FROM alerts WHERE 1=1 {where} ORDER BY created_at DESC, id DESC", args)
    admin = "system.read" in g.perms
    rows = [a for a in rows if a["patient_id"] in ids or (a["patient_id"] is None and admin)]
    total = len(rows)
    rows = rows[offset:offset + limit]
    names = {p["id"]: p for p in db.q("SELECT id, code, full_name FROM patients")}
    for a in rows:
        p = names.get(a["patient_id"])
        a.update(label=TYPE_LABEL.get(a["type"], a["type"]), patient_code=p["code"] if p else None, patient_name=p["full_name"] if p else None)
    return rows, total


@bp.get("/alerts")
@require("alerts.read")
def alerts_list():
    svc, ns = S(), NS()
    page, per, off = paging()
    where, args = "", []
    status = request.args.get("status", "open")
    if status == "open":
        where += f" AND status IN ({','.join('?' * len(OPEN))})"; args += list(OPEN)
    elif status == "closed":
        where += " AND status IN ('resolved','false_positive')"
    elif status != "all":
        where += " AND status=?"; args.append(status)
    for col in ("category", "severity", "type"):
        if request.args.get(col):
            where += f" AND {col}=?"; args.append(request.args[col])
    if request.args.get("patient_id"):
        try:
            where += " AND patient_id=?"; args.append(int(request.args["patient_id"]))
        except ValueError:
            return err("patient_id must be an integer", "E_VALIDATION", 400)
    rows, total = _alert_rows(svc, ns, where, args, per, off)
    return jsonify({"mode": ns, "alerts": rows, "total": total, "page": page, "per_page": per})


@bp.get("/alerts/<int:aid>")
@require("alerts.read")
def alert_get(aid):
    svc, ns = S(), NS()
    rows, _ = _alert_rows(svc, ns, " AND id=?", (aid,))
    if not rows:
        return err("unknown alert", "E_NOT_FOUND", 404)
    db = svc.store.ns(ns)
    a = rows[0]
    a["events"] = db.q("SELECT * FROM alert_events WHERE alert_id=? ORDER BY id", (aid,))
    users = {u["id"]: u["full_name"] for u in svc.store.system.q("SELECT id, full_name FROM users")}
    for e in a["events"]:
        e["user_name"] = users.get(e["user_id"], "system" if e["user_id"] is None else "?")
    a["measurement"] = db.one("SELECT ts, heart_rate, spo2, temperature, fall_detected, quality FROM measurements WHERE id=?", (a["measurement_id"],)) if a["measurement_id"] else None
    pr = db.one("SELECT ts, score, probability, risk_category, model_version, explanation FROM predictions WHERE id=?", (a["prediction_id"],)) if a["prediction_id"] else None
    if pr:
        pr["explanation"] = json.loads(pr["explanation"] or "[]")
    a["prediction"] = pr if "predictions.read" in g.perms else None
    return jsonify({"alert": a})


@bp.post("/alerts/<int:aid>/action")
@require("alerts.read")
def alert_action(aid):
    svc, ns, d = S(), NS(), body()
    rows, _ = _alert_rows(svc, ns, " AND id=?", (aid,))
    if not rows:
        return err("unknown alert", "E_NOT_FOUND", 404)
    assignee = d.get("assignee")
    if d.get("action") == "assign":
        u = svc.auth.user(assignee) if isinstance(assignee, int) else None
        if not u or u["role"] not in ("doctor", "assistant"):
            return err("assignee must be a doctor or assistant", "E_VALIDATION", 400)
    alert, problem = svc.alerts.act(ns, aid, d.get("action"), g.user, g.perms, d.get("note"), assignee)
    if problem:
        if problem[2] == 403:
            svc.audit.log("alert." + str(d.get("action")), g.user, "alert", aid, ns, outcome="denied")
        return err(*problem)
    svc.audit.log("alert." + d["action"], g.user, "alert", aid, ns)
    return jsonify({"alert": AlertEngine.public(alert)})


@bp.get("/notifications")
@require()
def notifications_list():
    svc, ns = S(), NS()
    rows = svc.store.ns(ns).q("SELECT id, alert_id, channel, ts, status, title, body, read_at FROM notifications WHERE user_id=? AND channel='in_app' ORDER BY id DESC LIMIT 50",
                              (g.user["id"],))
    return jsonify({"notifications": rows, "unread": sum(1 for r in rows if r["read_at"] is None and r["status"] == "sent")})


@bp.post("/notifications/read")
@require()
def notifications_read():
    svc, ns = S(), NS()
    svc.store.ns(ns).x("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL", (svc.clock(), g.user["id"]))
    return jsonify({"ok": True})


# ======================================================================== overview
@bp.get("/overview")
@require("patients.read")
def overview():
    svc, ns = S(), NS()
    db, now = svc.store.ns(ns), svc.clock()
    ids = svc.visible_patient_ids(g.user, ns)
    pats = [_summary(db, p, now, svc, False) for p in db.q("SELECT * FROM patients ORDER BY id") if p["id"] in ids]
    alerts, _ = _alert_rows(svc, ns, f" AND status IN ({','.join('?' * len(OPEN))})", OPEN, 1000)
    c = _counters(db)
    recent_pred = [r for r in db.q("SELECT patient_id, risk_category, status FROM predictions WHERE ts>=?", (now - 300,)) if r["patient_id"] in ids]
    last = max((p["latest"]["ts"] for p in pats if p["latest"]), default=None)
    ps = svc.predictor.status()
    return jsonify({
        "mode": ns, "data_source": "SIMULATION (synthetic)" if ns == "simulation" else "hardware", "generated_at": now,
        "kpi": {
            "patients_total": len(pats),
            "patients_connected": sum(1 for p in pats if p["device"] and p["device"]["online"]),
            "patients_abnormal": sum(1 for p in pats if p["latest"] and p["latest"]["abnormal"]),
            "alerts_critical": sum(1 for a in alerts if a["severity"] == "critical"),
            "alerts_open": len(alerts),
            "patients_attention": sum(1 for p in pats if p["open_alerts"] > 0),
            "devices_offline": sum(1 for p in pats if p["device"] and not p["device"]["online"]),
            "last_measurement_ts": last,
            "predictions_5min": sum(1 for r in recent_pred if r["status"] == "ok"),
            "predictions_high_5min": sum(1 for r in recent_pred if r["risk_category"] == "high"),
        },
        "network": {"valid": c.get("valid", 0), "lost_estimate": c.get("lost_estimate", 0), "duplicates": c.get("duplicates", 0),
                    "pdr": _pdr(c), "kind": "simulated" if ns == "simulation" else "measured"},
        "model": {"name": ps["model_name"], "version": ps["model_version"], "health": ps["health"], "loaded": ps["loaded"]},
        "patients": pats, "alerts": alerts[:20],
    })


# ======================================================================== network / digital twin
@bp.get("/network")
@require("network.read")
def network():
    svc, ns = S(), NS()
    db, now = svc.store.ns(ns), svc.clock()
    devices = _visible_devices(svc, ns)
    c = _counters(db)
    names = {p["id"]: p["code"] for p in db.q("SELECT id, code FROM patients")}
    sim = svc.simulator.status() if (ns == "simulation" and svc.simulator) else None
    relays = []
    if sim:
        relays = [{"id": f"R{r['index'] + 1}", "kind": "simulated", **r} for r in sim["relays"]]
        routes = {p["device_id"]: p for p in sim["patients"]}
    else:
        routes = {}
    nodes = [{"id": "GW", "type": "gateway", "label": "Doctor gateway (Raspberry Pi 5)", "gateway_id": svc.cfg.GATEWAY_ID}]
    nodes += [{"id": r["id"], "type": "relay", "label": f"Relay {r['id'][1:]}", **{k: r[k] for k in ("received", "forwarded", "dropped", "duplicates")}} for r in relays]
    links = []
    for i, r in enumerate(relays):
        links.append({"from": r["id"], "to": relays[i + 1]["id"] if i + 1 < len(relays) else "GW", "kind": "relay"})
    ids = svc.visible_patient_ids(g.user, ns)
    for d in devices:
        if d["patient_id"] is None:
            continue
        route = routes.get(d["id"])
        hops = d["last_hop_count"] or 0
        entry = f"R{len(relays) - route['hops'] + 1}" if route and route["hops"] else None
        nodes.append({"id": f"D{d['id']}", "type": "patient", "label": names.get(d["patient_id"], "?"), "patient_id": d["patient_id"],
                      "device_id": d["id"], "online": d["online"], "rssi": d["last_rssi"], "snr": d["last_snr"], "hop_count": hops,
                      "pdr": d["pdr"], "last_seen_at": d["last_seen_at"]})
        links.append({"from": f"D{d['id']}", "to": entry or "GW", "kind": "relay" if entry or hops else "direct",
                      "inferred": bool(hops and not entry)})
    events = [e for e in db.q("SELECT * FROM network_events ORDER BY id DESC LIMIT 150") if e["patient_id"] is None or e["patient_id"] in ids][:80]
    lat = db.one("SELECT AVG(latency_ms) AS avg, MAX(latency_ms) AS max, COUNT(latency_ms) AS n FROM network_events WHERE kind='rx' AND latency_ms IS NOT NULL AND ts>=?", (now - 900,))
    rate = db.scalar("SELECT COUNT(*) FROM network_events WHERE kind='rx' AND ts>=?", (now - 60,))
    return jsonify({
        "mode": ns, "kind": "simulated" if ns == "simulation" else "measured",
        "note": ("Statistics produced by the built-in network model (simulation mode)." if ns == "simulation" else
                 "Statistics measured by the gateway from received frames. Relays are not individually observable; "
                 "relay-assisted delivery is inferred from hopCount. RSSI/SNR appear only if the radio driver reports them."),
        "protocol": "custom raw-LoRa, application-level relay (not LoRaWAN)",
        "counters": c, "pdr": _pdr(c), "frames_last_minute": rate,
        "latency_ms": {"avg": None if lat["avg"] is None else round(lat["avg"], 1), "max": lat["max"], "n": lat["n"],
                       "note": "simulated transmit-to-gateway delay" if ns == "simulation" else "only for time-synchronized devices"},
        "topology": {"nodes": nodes, "links": links}, "devices": devices, "relays": relays, "events": events,
        "simulation_engine": None if not sim else sim["stats"],
    })


@bp.get("/network/research")
@require("network.read")
def network_research():
    """Results imported from the OMNeT++/FLoRa research project (offline simulation, 20 patients / 3 relays / 1 gateway)."""
    d = S().cfg.RESEARCH_DIR
    out = []
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith(".json"):
                with open(os.path.join(d, f)) as fh:
                    out.append(json.load(fh))
    return jsonify({"kind": "omnetpp_flora_simulation", "note": "Offline OMNeT++ 6.5.0 / INET 4.6.0 / FLoRa 1.3.2 results. "
                    "Not live data and not connected to physical radios.", "runs": out})


# ======================================================================== machine learning
def _model_files(svc, version):
    d = os.path.join(svc.cfg.MODEL_DIR, version)
    out = {}
    for name in ("metadata", "metrics", "curves"):
        p = os.path.join(d, name + ".json")
        if os.path.isfile(p):
            with open(p) as f:
                out[name] = json.load(f)
    return out


@bp.get("/ml/model")
@require("ml.read")
def ml_model():
    svc = S()
    st = svc.predictor.status()
    files = _model_files(svc, st["model_version"]) if st["model_version"] else {}
    return jsonify({"runtime": st, "versions": svc.predictor.versions(), **files,
                    "disclaimer": "All metrics are computed by ml/train.py on a held-out SYNTHETIC test set split by patient. "
                                  "They are not clinical performance."})


@bp.post("/ml/deploy")
@require("ml.deploy")
def ml_deploy():
    svc, d = S(), body()
    from .inference import ModelUnavailable
    version = svc.predictor.previous_version() if d.get("rollback") else d.get("version")
    if not version:
        return err("no version given (or no previous version to roll back to)", "E_VALIDATION", 400)
    try:
        st = svc.predictor.set_active(str(version))
    except ModelUnavailable as e:
        svc.audit.log("model.deploy", g.user, "model", version, outcome="failed", detail=str(e)[:200])
        return err(str(e), "E_MODEL", 400)
    svc.audit.log("model.rollback" if d.get("rollback") else "model.deploy", g.user, "model", version)
    svc.store.system.x("UPDATE model_versions SET status='archived' WHERE status='active'")
    svc.store.system.x("""INSERT INTO model_versions(name,version,path,status,deployed_at,deployed_by) VALUES(?,?,?,?,?,?)
                          ON CONFLICT(version) DO UPDATE SET status='active', deployed_at=excluded.deployed_at, deployed_by=excluded.deployed_by""",
                       (st["model_name"], version, os.path.join(svc.cfg.MODEL_DIR, str(version)), "active", svc.clock(), g.user["id"]))
    return jsonify({"runtime": st})


@bp.get("/ml/predictions")
@require("predictions.read")
def ml_predictions():
    svc, ns = S(), NS()
    db = svc.store.ns(ns)
    ids = svc.visible_patient_ids(g.user, ns)
    rows = [r for r in db.q("""SELECT p.id, p.patient_id, p.ts, p.status, p.score, p.probability, p.risk_category, p.model_version,
                               p.latency_ms, p.explanation FROM predictions p ORDER BY p.id DESC LIMIT 400""") if r["patient_id"] in ids][:150]
    names = {p["id"]: p["code"] for p in db.q("SELECT id, code FROM patients")}
    for r in rows:
        r["explanation"] = json.loads(r["explanation"] or "[]")
        r["patient_code"] = names.get(r["patient_id"])
    dist = {}
    for r in db.q("SELECT patient_id, risk_category, status, COUNT(*) AS n FROM predictions GROUP BY 1,2,3"):
        if r["patient_id"] in ids:
            k = r["risk_category"] if r["status"] == "ok" else r["status"]
            dist[k] = dist.get(k, 0) + r["n"]
    return jsonify({"mode": ns, "predictions": rows, "distribution": dist})


# ======================================================================== simulation control
@bp.get("/simulation")
@require("simulation.read")
def sim_status():
    svc = S()
    st = svc.simulator.status()
    if "simulation.control" not in g.perms:
        st = {k: st[k] for k in ("state", "session_id", "config", "sim_time_s", "scenarios")}
    return jsonify({"mode": NS(), "simulation": st})


@bp.post("/simulation/<action>")
@require("simulation.control")
def sim_control(action):
    svc = S()
    d = request.get_json(silent=True) or {}
    sim = svc.simulator
    if action == "start":
        st = sim.start(d, g.user)
    elif action == "pause":
        st = sim.pause(g.user)
    elif action == "resume":
        st = sim.resume(g.user)
    elif action == "stop":
        st = sim.stop(g.user)
    elif action == "reset":
        st = sim.reset(d or sim.config, g.user)
    elif action == "event":
        if not isinstance(d.get("patient_id"), int):
            return err("patient_id is required", "E_VALIDATION", 400)
        st = sim.trigger(d["patient_id"], d.get("event"), g.user)
    else:
        return err("unknown simulation action", "E_NOT_FOUND", 404)
    return jsonify({"mode": NS(), "simulation": st})


# ======================================================================== reports / export
def _download(data, mime, filename):
    return Response(data, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                                  "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@bp.get("/reports/patient/<int:pid>.<fmt>")
@require("reports.export")
def report_patient(pid, fmt):
    svc, ns = S(), NS()
    p = patient_or_404(pid)
    if fmt not in ("csv", "pdf"):
        return err("format must be csv or pdf", "E_NOT_FOUND", 404)
    db = svc.store.ns(ns)
    t_from, t_to = _time_window(svc)
    meas = db.q("""SELECT ts, seq_no, heart_rate, spo2, temperature, fall_detected, alert_level, quality, hop_count, routing_mode, rssi, snr, data_source
                   FROM measurements WHERE patient_id=? AND ts BETWEEN ? AND ? ORDER BY ts LIMIT 200000""", (pid, t_from, t_to))
    now = svc.clock()
    svc.audit.log("report.export", g.user, "patient", pid, ns, detail={"format": fmt, "rows": len(meas)})
    src = "SIMULATION (synthetic)" if ns == "simulation" else "hardware"
    if fmt == "csv":
        head = [f"Remote Patient Monitoring - measurement export for {p['code']}", f"Data source: {src}",
                f"Period (UTC): {reports.iso(t_from)} to {reports.iso(t_to)}", f"Generated (UTC): {reports.iso(now)} by {g.user['username']}",
                reports.DISCLAIMER]
        cols = ["ts_utc", "ts", "seq_no", "heart_rate", "spo2", "temperature", "fall_detected", "alert_level", "quality",
                "hop_count", "routing_mode", "rssi", "snr", "data_source"]
        return _download(reports.to_csv(head, cols, meas), "text/csv", f"{p['code']}_measurements.csv")
    alerts = db.q("SELECT * FROM alerts WHERE patient_id=? AND created_at BETWEEN ? AND ? ORDER BY created_at", (pid, t_from, t_to))
    preds = db.q("SELECT status, risk_category, model_name, model_version, prediction_type FROM predictions WHERE patient_id=? AND ts BETWEEN ? AND ? ORDER BY ts",
                 (pid, t_from, t_to))
    return _download(reports.patient_pdf(p, ns, t_from, t_to, meas, alerts, preds, now, g.user["full_name"]),
                     "application/pdf", f"{p['code']}_report.pdf")


@bp.get("/reports/alerts.csv")
@require("reports.export")
def report_alerts():
    svc, ns = S(), NS()
    t_from, t_to = _time_window(svc)
    rows, _ = _alert_rows(svc, ns, " AND created_at BETWEEN ? AND ?", (t_from, t_to), 100000)
    svc.audit.log("report.export", g.user, "alerts", None, ns, detail={"rows": len(rows)})
    head = ["Remote Patient Monitoring - alert report", f"Data source: {'SIMULATION (synthetic)' if ns == 'simulation' else 'hardware'}",
            f"Period (UTC): {reports.iso(t_from)} to {reports.iso(t_to)}", f"Generated (UTC): {reports.iso(svc.clock())} by {g.user['username']}",
            reports.DISCLAIMER]
    cols = ["id", "created_at_utc", "patient_code", "type", "category", "severity", "status", "message", "trigger_count",
            "acknowledged_at_utc", "resolved_at_utc", "escalation_level", "note"]
    return _download(reports.to_csv(head, cols, rows), "text/csv", "alerts.csv")


@bp.get("/reports/network.csv")
@require("reports.export", "network.read")
def report_network():
    svc, ns = S(), NS()
    rows = _visible_devices(svc, ns)
    svc.audit.log("report.export", g.user, "network", None, ns, detail={"rows": len(rows)})
    head = ["Remote Patient Monitoring - device connectivity / network performance report",
            f"Statistics kind: {'SIMULATED (network model)' if ns == 'simulation' else 'measured by the gateway'}",
            f"Generated (UTC): {reports.iso(svc.clock())} by {g.user['username']}", "Custom raw-LoRa protocol (not LoRaWAN)."]
    cols = ["id", "serial", "patient_id", "status", "online", "last_seen_at_utc", "rx_count", "lost_estimate", "dup_count", "pdr",
            "avg_latency_ms", "last_rssi", "last_snr", "last_hop_count", "auth_fail_count", "replay_count", "out_of_order_count"]
    return _download(reports.to_csv(head, cols, rows), "text/csv", "network.csv")


@bp.get("/reports/model.pdf")
@require("reports.export", "ml.read")
def report_model():
    svc = S()
    st = svc.predictor.status()
    files = _model_files(svc, st["model_version"]) if st["model_version"] else {}
    if "metadata" not in files or "metrics" not in files:
        return err("no active model with evaluation artifacts", "E_NOT_FOUND", 404)
    svc.audit.log("report.export", g.user, "model", st["model_version"])
    return _download(reports.model_pdf(files["metadata"], files["metrics"], svc.clock()), "application/pdf",
                     f"model_{st['model_version']}_evaluation.pdf")


# ======================================================================== audit
@bp.get("/audit")
@require("audit.read")
def audit_list():
    page, per, off = paging()
    db = S().store.system
    where, args = "", []
    if request.args.get("action"):
        where = " WHERE action LIKE ?"; args.append(request.args["action"] + "%")
    rows = db.q(f"SELECT id, ts, username, action, target_type, target_id, ns, ip, outcome, detail FROM audit_log{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                (*args, per, off))
    return jsonify({"entries": rows, "total": db.scalar(f"SELECT COUNT(*) FROM audit_log{where}", args), "page": page, "per_page": per})


# ======================================================================== caregiver (restricted views only)
def _caregiver_view(svc, ns, link, now):
    db = svc.store.ns(ns)
    p = db.one("SELECT * FROM patients WHERE id=?", (link["patient_id"],))
    dev = db.one("SELECT online, last_seen_at FROM devices WHERE patient_id=? AND status='active'", (p["id"],))
    m = db.one("SELECT ts, heart_rate, spo2, temperature, fall_detected FROM measurements WHERE patient_id=? ORDER BY ts DESC, id DESC LIMIT 1", (p["id"],))
    warnings = db.q(f"""SELECT type, severity, created_at, status FROM alerts WHERE patient_id=? AND type IN ({','.join('?' * len(CAREGIVER_TYPES))})
                        AND severity IN ('critical','high') AND created_at>=? ORDER BY created_at DESC LIMIT 10""",
                    (p["id"], *sorted(CAREGIVER_TYPES), now - 7 * 86400))
    open_w = [w for w in warnings if w["status"] in OPEN]
    stale = bool(m) and now - m["ts"] > svc.cfg.STALE_AFTER_S
    if not dev or not m:
        state = "no_data"
    elif any(w["severity"] == "critical" for w in open_w):
        state = "urgent"
    elif open_w:
        state = "attention"
    elif not dev["online"] or stale:
        state = "offline"
    else:
        state = "ok"
    doctor = svc.auth.user(p["primary_doctor_id"]) if p["primary_doctor_id"] else None
    out = {"patient_id": p["id"], "name": p["full_name"], "relationship": link["relationship"], "state": state,
           "device_connected": bool(dev and dev["online"]), "last_measurement_ts": m["ts"] if m else None, "stale": stale,
           "vitals": None, "location": None,
           "warnings": [{"label": TYPE_LABEL[w["type"]], "severity": w["severity"], "created_at": w["created_at"],
                         "active": w["status"] in OPEN} for w in warnings],
           "contact": {"doctor_name": doctor["full_name"] if doctor else None, "doctor_phone": doctor["phone"] if doctor else None,
                       "procedure": "In an emergency call the local emergency number first. For questions contact the care team during working hours."},
           "is_simulation": ns == "simulation"}
    if link["can_view_vitals"] and m:
        out["vitals"] = {"heart_rate": m["heart_rate"], "spo2": m["spo2"], "temperature": m["temperature"],
                         "fall_detected": m["fall_detected"], "ts": m["ts"]}
    if link["can_view_location"]:
        out["location"] = _location(db, p["id"], now, svc)
    return out


@bp.get("/caregiver/patients")
@require("caregiver.view")
def caregiver_patients():
    svc, ns = S(), NS()
    now = svc.clock()
    out = []
    for pid in sorted(svc.visible_patient_ids(g.user, ns)):
        link = svc.caregiver_link(g.user, ns, pid)
        if link:
            out.append(_caregiver_view(svc, ns, link, now))
    return jsonify({"mode": ns, "patients": out})


@bp.get("/caregiver/patients/<int:pid>/history")
@require("caregiver.view")
def caregiver_history(pid):
    """Simplified history: hourly averages for the last 24 h (no raw records, no clinical notes, no predictions)."""
    svc, ns = S(), NS()
    link = svc.caregiver_link(g.user, ns, pid)
    if not link:
        svc.audit.log("patient.access_denied", g.user, "patient", pid, ns, outcome="denied")
        return err("unknown patient", "E_NOT_FOUND", 404)
    if not link["can_view_vitals"]:
        return jsonify({"patient_id": pid, "hours": []})
    now = svc.clock()
    rows = svc.store.ns(ns).q("""SELECT CAST(ts/3600 AS INTEGER)*3600 AS ts, ROUND(AVG(heart_rate)) AS heart_rate, ROUND(AVG(spo2)) AS spo2,
                                 ROUND(AVG(temperature),1) AS temperature, COUNT(*) AS n FROM measurements
                                 WHERE patient_id=? AND ts>=? GROUP BY 1 ORDER BY 1""", (pid, now - 86400))
    svc.audit.log("patient.view", g.user, "patient", pid, ns, detail="caregiver history")
    return jsonify({"patient_id": pid, "hours": rows})


# ======================================================================== real-time stream (SSE)
def _make_view(svc, user, perms):
    state = {"ids": set(), "links": {}, "at": 0.0, "ns": None}

    def refresh(ns):
        now = time.time()
        if now - state["at"] > 5 or state["ns"] != ns:
            state["ids"] = svc.visible_patient_ids(user, ns)
            if user["role"] == "caregiver":
                state["links"] = {pid: svc.caregiver_link(user, ns, pid) for pid in state["ids"]}
            state["at"], state["ns"] = now, ns

    def view(ev):
        ns = svc.store.mode()
        if ev["ns"] not in (None, ns):
            return None
        if ev["type"] == "system":
            return ev
        if ev["type"] == "notification":
            return ev if ev.get("user_id") == user["id"] else None
        refresh(ns)
        pid = ev.get("patient_id")
        if user["role"] == "caregiver":
            link = state["links"].get(pid)
            if not link:
                return None
            d = ev["data"]
            if ev["type"] == "measurement" and link["can_view_vitals"]:
                return {"type": "measurement", "ns": ns, "patient_id": pid,
                        "data": {k: d[k] for k in ("patient_id", "ts", "heart_rate", "spo2", "temperature", "fall_detected")}}
            if ev["type"] in ("alert", "alert_update") and d["type"] in CAREGIVER_TYPES and d["severity"] in ("critical", "high"):
                return {"type": ev["type"], "ns": ns, "patient_id": pid,
                        "data": {"label": d["label"], "severity": d["severity"], "created_at": d["created_at"], "status": d["status"]}}
            if ev["type"] == "device":
                return ev
            if ev["type"] == "location" and link["can_view_location"]:
                return ev
            return None
        if ev["type"] == "simulation":
            return ev
        if pid is None:
            return ev if "system.read" in perms or ev["type"] == "network" and "network.read" in perms else None
        if pid not in state["ids"]:
            return None
        if ev["type"] == "network" and "network.read" not in perms:
            return None
        if ev["type"] == "prediction" and "predictions.read" not in perms:
            return None
        if ev["type"] == "location" and "location.read" not in perms:
            return None
        return ev
    return view


@bp.get("/stream")
@require()
def stream():
    svc = S()
    user, perms = dict(g.user), set(g.perms)
    token, ua = request.cookies.get(COOKIE), request.headers.get("User-Agent", "")
    sid, q = svc.broker.subscribe(_make_view(svc, user, perms))

    def gen():
        try:
            yield "retry: 3000\n\n" + sse_format({"type": "hello", "data": {"server_time": svc.clock(), "mode": svc.store.mode()}})
            last_check = time.time()
            while True:
                try:
                    yield sse_format(q.get(timeout=15))
                except queue.Empty:
                    yield ": keep-alive\n\n"
                if time.time() - last_check > 30:          # stop streaming when the session ended
                    last_check = time.time()
                    if not svc.auth.session(token, ua):
                        return
        finally:
            svc.broker.unsubscribe(sid)

    return Response(stream_with_context(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# ======================================================================== hardware gateway ingestion
def _gateway_auth():
    svc = S()
    tok = svc.cfg.GATEWAY_INGEST_TOKEN
    if not tok:
        return err("hardware ingestion is disabled: RPM_GATEWAY_INGEST_TOKEN is not configured", "E_DISABLED", 503)
    h = request.headers.get("Authorization", "")
    sent = h[7:].strip() if h.startswith("Bearer ") else ""
    if not sent or not hmac.compare_digest(sent.encode(), tok.encode()):
        svc.audit.log("ingest.auth", None, outcome="denied")
        return err("invalid gateway credential", "E_AUTH", 401)
    return None


@bp.post("/ingest/frame")
def ingest_frame():
    """Called ONLY by the hardware gateway service. Always writes to the hardware namespace, whatever the UI mode."""
    bad = _gateway_auth()
    if bad:
        return bad
    d = body()
    try:
        raw = bytes.fromhex(str(d.get("frame_hex") or ""))
    except ValueError:
        return err("frame_hex must be hexadecimal", "E_VALIDATION", 400)
    num = lambda v: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None  # noqa: E731
    svc = S()
    if len(raw) == 16:
        res = svc.pipeline.handle_v1(raw, num(d.get("rssi")), num(d.get("snr")))
    else:
        res = svc.pipeline.handle_frame("hardware", raw, num(d.get("rssi")), num(d.get("snr")))
    return jsonify({"outcome": res["outcome"], "detail": res.get("detail"), "alerts": res.get("alerts", [])})
