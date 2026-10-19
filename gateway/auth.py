"""Bearer-token auth: doctor token for normal endpoints, admin token only for retrain (report section 5.3)."""
import hmac
from functools import wraps
from flask import current_app, jsonify, request


def err(msg, code, status):
    return jsonify({"error": msg, "code": code}), status


def _bearer():
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.startswith("Bearer ") else ""


def _eq(a, b):
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


def token_required(fn):
    @wraps(fn)
    def w(*a, **k):
        t, cfg = _bearer(), current_app.config["RPM"]
        if not (_eq(t, cfg.DOCTOR_TOKEN) or _eq(t, cfg.ADMIN_TOKEN)):
            return err("missing or invalid token", "E_AUTH", 401)
        return fn(*a, **k)
    return w


def admin_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if not _eq(_bearer(), current_app.config["RPM"].ADMIN_TOKEN):
            return err("admin token required", "E_AUTH", 401)
        return fn(*a, **k)
    return w
