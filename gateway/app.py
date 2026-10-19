"""Flask app: JSON API + doctor dashboard in one process (report section 5.1)."""
import math
import re
import time
from pathlib import Path
from flask import Flask, jsonify, render_template, request

from . import alerts as A
from . import telemetry as T
from .auth import admin_required, err, token_required
from .config import Config
from .database import Database
from .prediction import PredictionService

ROOT = Path(__file__).resolve().parent.parent
PID_RE = T.PID_RE


def create_app(config=None, clock=time.time):
    cfg = config or Config.from_env()
    if not cfg.DOCTOR_TOKEN or not cfg.ADMIN_TOKEN:
        raise RuntimeError("DOCTOR_TOKEN and ADMIN_TOKEN must be set (see .env.example)")
    app = Flask(__name__, template_folder=str(ROOT / "dashboard" / "templates"), static_folder=str(ROOT / "dashboard" / "static"))
    app.config["RPM"] = cfg
    db = Database(cfg.DB_PATH); db.init()
    pred = PredictionService(cfg)
    app.config.update(DB=db, PRED=pred, CLOCK=clock)

    # ---- helpers --------------------------------------------------------
    def num(v, lo, hi, nullable, name):
        if v is None:
            if nullable: return None
            raise ValueError(f"{name} is required")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{name} must be a number")
        if not lo <= v <= hi: raise ValueError(f"{name} out of range {lo}..{hi}")
        return v

    def validate(d):
        if not isinstance(d, dict): raise ValueError("JSON object expected")
        pid = d.get("pid")
        if not isinstance(pid, str) or not PID_RE.match(pid) or pid == "P000": raise ValueError("invalid pid (expected P001..P999)")
        flags = d.get("flags", 0)
        if isinstance(flags, bool) or not isinstance(flags, int) or not 0 <= flags <= 255 or flags & T.RESERVED_MASK: raise ValueError("invalid flags")
        fall = d.get("fall", 0)
        if fall not in (0, 1, True, False): raise ValueError("fall must be 0 or 1")
        hr_ok, tp_ok = bool(flags & T.F_HRSPO2_FAULT), bool(flags & T.F_TEMP_FAULT)
        out = {"pid": pid, "flags": flags, "fall": int(fall),
               "hr": num(d.get("hr"), 20, 250, hr_ok, "hr"), "spo2": num(d.get("spo2"), 50, 100, hr_ok, "spo2"),
               "temp": num(d.get("temp"), 20, 45, tp_ok, "temp"),
               "synthetic": bool(d.get("synthetic", False)), "source": str(d.get("source", "api"))[:32]}
        now = int(clock())
        ts = d.get("ts", now)
        if isinstance(ts, bool) or not isinstance(ts, int) or ts < 0 or ts > now + 300: raise ValueError("invalid ts")
        out["ts"] = ts
        for k, hi in (("seq", 65535), ("uptime", 0xFFFFFFFF)):
            v = d.get(k)
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= hi): raise ValueError(f"invalid {k}")
            out[k] = v
        return out

    def stale_check():
        now = int(clock())
        for p in db.list_patients():
            if now - p["last_seen"] > cfg.STALE_AFTER_S:
                db.create_alert(p["pid"], "STALE_DATA", A.SEV["STALE_DATA"], f"No data for {now - p['last_seen']} s", now)

    # ---- error handlers -------------------------------------------------
    @app.errorhandler(404)
    def _404(e): return err("not found", "E_NOT_FOUND", 404)

    @app.errorhandler(405)
    def _405(e): return err("method not allowed", "E_METHOD", 405)

    @app.errorhandler(500)
    def _500(e): return err("internal server error", "E_INTERNAL", 500)

    # ---- routes ---------------------------------------------------------
    @app.get("/")
    def index(): return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "time": int(clock()), "allowed_horizons": list(cfg.ALLOWED_HORIZONS), "model": pred.status()["model"]})

    @app.post("/api/vitals")
    @token_required
    def vitals():
        d = request.get_json(silent=True)
        if d is None: return err("bad JSON", "E_BAD_JSON", 400)
        try:
            r = validate(d)
        except ValueError as e:
            return err(str(e), "E_VALIDATION", 400)
        if db.is_duplicate(r["pid"], r["seq"], r["uptime"]):
            return jsonify({"ok": True, "stored": False, "duplicate": True}), 200
        now = clock()
        p = db.patient(r["pid"])
        if p and now - p["last_write_at"] < cfg.VITALS_MIN_INTERVAL_S:
            resp = jsonify({"error": "rate limit: 1 write per %gs per patient" % cfg.VITALS_MIN_INTERVAL_S, "code": "E_RATE"})
            resp.headers["Retry-After"] = str(math.ceil(cfg.VITALS_MIN_INTERVAL_S - (now - p["last_write_at"])))
            return resp, 429
        rid = db.insert_reading(r, now)
        if rid is None: return jsonify({"ok": True, "stored": False, "duplicate": True}), 200
        created = []
        for kind, sev, msg in A.evaluate(r, cfg):
            if db.create_alert(r["pid"], kind, sev, msg, r["ts"], rid): created.append(kind)
        return jsonify({"ok": True, "stored": True, "alerts": created}), 201

    @app.get("/api/patients")
    @token_required
    def patients():
        now = int(clock())
        ps = db.list_patients()
        for p in ps: p["age_s"] = now - p["last_seen"]
        return jsonify({"patients": ps})

    def known(pid):
        return bool(PID_RE.match(pid)) and db.patient(pid) is not None

    @app.get("/api/patient/<pid>/latest")
    @token_required
    def latest(pid):
        if not known(pid): return err("unknown patient", "E_NOT_FOUND", 404)
        r = db.latest(pid)
        if r is None: return err("patient has no stored readings", "E_NOT_FOUND", 404)
        r["age_s"] = int(clock()) - r["ts"]
        return jsonify({"pid": pid, "latest": r})

    @app.get("/api/patient/<pid>/history")
    @token_required
    def history(pid):
        if not known(pid): return err("unknown patient", "E_NOT_FOUND", 404)
        try:
            hours = int(request.args.get("hours", 24))
            if not 1 <= hours <= 24 * cfg.RETENTION_DAYS: raise ValueError
        except ValueError:
            return err(f"hours must be an integer 1..{24 * cfg.RETENTION_DAYS}", "E_VALIDATION", 400)
        rows = db.history(pid, int(clock()) - hours * 3600)
        return jsonify({"pid": pid, "hours": hours, "count": len(rows), "readings": rows})

    @app.get("/api/patient/<pid>/predict")
    @token_required
    def predict(pid):
        if not known(pid): return err("unknown patient", "E_NOT_FOUND", 404)
        try:
            horizon = int(request.args.get("horizon", 15))
        except ValueError:
            return err("horizon must be an integer", "E_HORIZON", 400)
        if horizon not in cfg.ALLOWED_HORIZONS:
            return err(f"unsupported horizon; allowed: {list(cfg.ALLOWED_HORIZONS)}", "E_HORIZON", 400)
        return jsonify(pred.predict(pid, db.last_n(pid, cfg.WINDOW), horizon, clock())), 200

    @app.get("/api/alerts")
    @token_required
    def alerts():
        status = request.args.get("status", "active")
        if status not in ("active", "acknowledged", "all"): return err("status must be active|acknowledged|all", "E_VALIDATION", 400)
        pid = request.args.get("pid")
        if pid and not PID_RE.match(pid): return err("invalid pid", "E_VALIDATION", 400)
        stale_check()
        return jsonify({"alerts": db.list_alerts(status, pid)})

    @app.post("/api/alerts/<int:aid>/ack")
    @token_required
    def ack(aid):
        ts = int(clock())
        found, already = db.ack_alert(aid, ts)
        if not found: return err("unknown alert", "E_NOT_FOUND", 404)
        return jsonify({"ok": True, "id": aid, "already_acknowledged": already})

    @app.post("/api/model/retrain")
    @admin_required
    def retrain():
        d = request.get_json(silent=True) or {}
        if d.get("action") == "reload":
            return jsonify({"ok": True, "action": "reload", "model_status": pred.reload()})
        return err("Retraining runs offline (ml/train_model.py) and needs a dataset + TensorFlow; "
                   "POST {\"action\":\"reload\"} to reload the model artifact", "E_UNSUPPORTED", 501)

    return app


if __name__ == "__main__":
    c = Config.from_env()
    create_app(c).run(host=__import__("os").environ.get("HOST", "127.0.0.1"), port=int(__import__("os").environ.get("PORT", 5000)))
