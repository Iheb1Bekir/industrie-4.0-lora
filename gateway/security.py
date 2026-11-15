"""Authentication, sessions, CSRF, role-based access control, audit trail, secret wrapping.

* Passwords: scrypt (werkzeug.security, per-password random salt). Never stored or logged in clear.
* Sessions: 256-bit random token in an HttpOnly, SameSite=Strict cookie; only its SHA-256 is stored.
  Idle + absolute expiry; bound to a hash of the User-Agent (cheap session-theft signal).
* CSRF: per-session token that must be echoed in the X-CSRF-Token header on every state-changing request.
* RBAC: explicit permission table below; the role is read from the database on every request - nothing
  sent by the browser is trusted.
* Audit: append-only table with a SHA-256 hash chain (tamper evidence, see `Audit.verify`).
* Device keys / TOTP secrets: AES-256-GCM with the master key (cryptography library).
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import current_app, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

COOKIE = "rpm_session"

# ---- explicit permission matrix (server-side source of truth) -------------------------------------------
PERMISSIONS = {
    "doctor": {
        "patients.read", "patients.write", "patients.register", "patients.assign",
        "devices.read", "devices.manage",
        "alerts.read", "alerts.acknowledge", "alerts.assign", "alerts.escalate", "alerts.resolve",
        "alerts.false_positive",
        "notes.clinical.read", "notes.clinical.write", "notes.observation.read", "notes.observation.write",
        "caregivers.manage", "location.read", "location.write", "thresholds.write",
        "reports.export", "network.read", "ml.read", "predictions.read", "simulation.read",
    },
    "assistant": {
        "patients.read", "devices.read",
        "alerts.read", "alerts.acknowledge", "alerts.escalate",
        "notes.observation.read", "notes.observation.write",
        "location.read", "network.read", "predictions.read", "simulation.read",
    },
    "caregiver": {"caregiver.view"},
}
ADMIN_PERMISSIONS = {  # doctor accounts with is_admin = 1
    "users.manage", "simulation.control", "mode.switch", "ml.deploy", "audit.read",
    "settings.write", "system.read", "patients.read_all",
}


def permissions_of(user):
    p = set(PERMISSIONS.get(user["role"], ()))
    if user["role"] == "doctor" and user.get("is_admin"):
        p |= ADMIN_PERMISSIONS
    return p


def err(msg, code, status):
    return jsonify({"error": msg, "code": code}), status


# ---- passwords -------------------------------------------------------------------------------------------
def hash_password(pw: str) -> str:
    return generate_password_hash(pw, method="scrypt")


def verify_password(pw_hash: str, pw: str) -> bool:
    try:
        return check_password_hash(pw_hash, pw)
    except ValueError:
        return False


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))  # equalizes timing for unknown usernames


def password_problem(pw, cfg, username=""):
    if not isinstance(pw, str) or len(pw) < cfg.PASSWORD_MIN_LEN:
        return f"password must have at least {cfg.PASSWORD_MIN_LEN} characters"
    if len(pw) > 256:
        return "password too long"
    if username and username.lower() in pw.lower():
        return "password must not contain the username"
    classes = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        return "password must mix at least 3 of: lower case, upper case, digits, symbols"
    return None


# ---- secret wrapping ---------------------------------------------------------------------------------------
def wrap(master_key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(master_key).encrypt(nonce, plaintext, aad)


def unwrap(master_key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    return AESGCM(master_key).decrypt(bytes(blob[:12]), bytes(blob[12:]), aad)


# ---- TOTP (RFC 6238, SHA-1, 30 s, 6 digits) ---------------------------------------------------------------
def totp_now(secret: bytes, t=None, step=30, digits=6, offset=0):
    counter = int((time.time() if t is None else t) // step) + offset
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    return str((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)


def totp_verify(secret: bytes, code, t=None):
    code = str(code or "").strip()
    return len(code) == 6 and any(hmac.compare_digest(totp_now(secret, t, offset=o), code) for o in (-1, 0, 1))


def totp_uri(secret: bytes, username, issuer="RPM-LoRa"):
    b32 = base64.b32encode(secret).decode().rstrip("=")
    return b32, f"otpauth://totp/{issuer}:{username}?secret={b32}&issuer={issuer}&digits=6&period=30"


# ---- in-memory sliding-window rate limiter -----------------------------------------------------------------
class RateLimiter:
    def __init__(self):
        self._hits, self._lock = defaultdict(deque), threading.Lock()

    def allow(self, key, limit, window_s, now=None):
        now = time.time() if now is None else now
        with self._lock:
            d = self._hits[key]
            while d and d[0] <= now - window_s:
                d.popleft()
            if len(d) >= limit:
                return False
            d.append(now)
            return True


# ---- audit trail -------------------------------------------------------------------------------------------
class Audit:
    """Append-only, hash-chained. Never pass passwords, tokens or measurement values in `detail`."""

    def __init__(self, db, clock=time.time):
        self.db, self.clock = db, clock

    def log(self, action, user=None, target_type=None, target_id=None, ns=None, outcome="ok", detail=None, ip=None):
        if ip is None:
            try:
                ip = request.remote_addr
            except RuntimeError:
                ip = None
        ts = self.clock()
        uid, uname = (user or {}).get("id"), (user or {}).get("username")
        detail_s = json.dumps(detail, sort_keys=True) if isinstance(detail, (dict, list)) else detail
        with self.db.tx() as c:
            prev = c.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = prev[0] if prev else "0" * 64
            h = self._hash(prev_hash, ts, uid, uname, action, target_type, target_id, ns, outcome, detail_s)
            c.execute("""INSERT INTO audit_log(ts,user_id,username,action,target_type,target_id,ns,ip,outcome,detail,prev_hash,hash)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (ts, uid, uname, action, target_type, None if target_id is None else str(target_id), ns, ip,
                       outcome, detail_s, prev_hash, h))

    @staticmethod
    def _hash(prev_hash, ts, uid, uname, action, ttype, tid, ns, outcome, detail):
        payload = json.dumps([prev_hash, repr(float(ts)), uid, uname, action, ttype, None if tid is None else str(tid),
                              ns, outcome, detail], separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def verify(self):
        """Recompute the chain. Returns (ok, number_of_entries, first_bad_id)."""
        prev, n = "0" * 64, 0
        for r in self.db.q("SELECT * FROM audit_log ORDER BY id"):
            n += 1
            h = self._hash(prev, r["ts"], r["user_id"], r["username"], r["action"], r["target_type"], r["target_id"],
                           r["ns"], r["outcome"], r["detail"])
            if r["prev_hash"] != prev or r["hash"] != h:
                return False, n, r["id"]
            prev = r["hash"]
        return True, n, None


# ---- users + sessions --------------------------------------------------------------------------------------
PUBLIC_USER_FIELDS = ("id", "username", "full_name", "email", "phone", "role", "is_admin", "is_demo", "is_active",
                      "totp_enabled", "must_change_password", "created_at", "last_login_at")


def public_user(u):
    return {k: u[k] for k in PUBLIC_USER_FIELDS}


class Auth:
    def __init__(self, store, cfg, audit, clock=time.time):
        self.db, self.cfg, self.audit, self.clock = store.system, cfg, audit, clock
        self.limiter = RateLimiter()

    # -- user management
    def create_user(self, username, password, role, full_name, is_admin=False, email=None, phone=None, is_demo=False,
                    must_change=False):
        if role not in PERMISSIONS:
            raise ValueError("invalid role")
        if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", username or ""):
            raise ValueError("username must be 3-40 characters: letters, digits, . _ -")
        if is_admin and role != "doctor":
            raise ValueError("only doctor accounts can be administrators")
        problem = password_problem(password, self.cfg, username)
        if problem:
            raise ValueError(problem)
        if self.db.one("SELECT 1 FROM users WHERE username=?", (username,)):
            raise ValueError("username already exists")
        return self.db.x("""INSERT INTO users(username,full_name,email,phone,role,is_admin,password_hash,is_demo,
                            must_change_password,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                         (username, (full_name or username)[:120], email, phone, role, int(bool(is_admin)),
                          hash_password(password), int(bool(is_demo)), int(bool(must_change)), self.clock()))

    def user(self, uid):
        return self.db.one("SELECT * FROM users WHERE id=?", (uid,))

    def set_password(self, uid, new_password, keep_session_token=None):
        self.db.x("UPDATE users SET password_hash=?, must_change_password=0, failed_logins=0, locked_until=0 WHERE id=?",
                  (hash_password(new_password), uid))
        keep = hashlib.sha256(keep_session_token.encode()).hexdigest() if keep_session_token else ""
        self.db.x("UPDATE sessions SET revoked=1 WHERE user_id=? AND token_hash<>?", (uid, keep))

    # -- login
    def login(self, username, password, otp=None, ip=None, user_agent=""):
        """Returns (session_token, csrf, user) or raises AuthFailure(code, message, status)."""
        now = self.clock()
        if not self.limiter.allow(("login", ip), self.cfg.LOGIN_RATE_PER_MIN, 60, now):
            raise AuthFailure("E_RATE", "too many login attempts, wait a minute", 429)
        u = self.db.one("SELECT * FROM users WHERE username=?", (username or "",))
        if not u:
            verify_password(_DUMMY_HASH, password or "")
            self.audit.log("auth.login", {"username": str(username)[:40]}, outcome="denied", detail="unknown user", ip=ip)
            raise AuthFailure("E_AUTH", "invalid username or password", 401)
        if u["locked_until"] > now:
            self.audit.log("auth.login", u, outcome="denied", detail="locked", ip=ip)
            raise AuthFailure("E_LOCKED", f"account temporarily locked, retry in {int(u['locked_until'] - now) + 1} s", 423)
        ok = verify_password(u["password_hash"], password or "")
        if ok and u["totp_enabled"]:
            secret = unwrap(self.cfg.MASTER_KEY, u["totp_secret_enc"], b"totp")
            if not otp:
                raise AuthFailure("E_OTP_REQUIRED", "one-time code required", 401)
            ok = totp_verify(secret, otp, now)
        if not ok:
            fails = u["failed_logins"] + 1
            lock = 0
            if fails >= self.cfg.LOCKOUT_AFTER:  # progressive delay: 30 s, 60 s, 120 s ... capped
                lock = now + min(self.cfg.LOCKOUT_MAX_S, self.cfg.LOCKOUT_BASE_S * 2 ** (fails - self.cfg.LOCKOUT_AFTER))
            self.db.x("UPDATE users SET failed_logins=?, locked_until=? WHERE id=?", (fails, lock, u["id"]))
            self.audit.log("auth.login", u, outcome="denied", detail="bad credentials", ip=ip)
            raise AuthFailure("E_AUTH", "invalid username or password", 401)
        if not u["is_active"]:
            self.audit.log("auth.login", u, outcome="denied", detail="inactive", ip=ip)
            raise AuthFailure("E_AUTH", "invalid username or password", 401)
        if u["is_demo"] and self.cfg.production:
            self.audit.log("auth.login", u, outcome="denied", detail="demo account in production", ip=ip)
            raise AuthFailure("E_AUTH", "demo accounts are disabled in production", 401)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        self.db.x("UPDATE users SET failed_logins=0, locked_until=0, last_login_at=? WHERE id=?", (now, u["id"]))
        self.db.x("""INSERT INTO sessions(token_hash,user_id,csrf_token,created_at,last_seen_at,expires_at,ip,ua_hash)
                     VALUES(?,?,?,?,?,?,?,?)""",
                  (hashlib.sha256(token.encode()).hexdigest(), u["id"], csrf, now, now, now + self.cfg.SESSION_ABSOLUTE_S,
                   ip, hashlib.sha256((user_agent or "").encode()).hexdigest()))
        self.audit.log("auth.login", u, ip=ip)
        return token, csrf, self.user(u["id"])

    def session(self, token, user_agent=""):
        """Resolve a cookie token to (session_row, user_row) or None. Slides the idle timer."""
        if not token:
            return None
        now = self.clock()
        s = self.db.one("SELECT * FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        if not s or s["revoked"] or now > s["expires_at"] or now - s["last_seen_at"] > self.cfg.SESSION_IDLE_S:
            return None
        if s["ua_hash"] != hashlib.sha256((user_agent or "").encode()).hexdigest():
            self.db.x("UPDATE sessions SET revoked=1 WHERE id=?", (s["id"],))
            self.audit.log("auth.session_mismatch", {"id": s["user_id"]}, outcome="denied", detail="user-agent changed")
            return None
        u = self.user(s["user_id"])
        if not u or not u["is_active"]:
            return None
        if now - s["last_seen_at"] > 15:
            self.db.x("UPDATE sessions SET last_seen_at=? WHERE id=?", (now, s["id"]))
        return s, u

    def logout(self, token):
        if token:
            self.db.x("UPDATE sessions SET revoked=1 WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    # -- password reset (administrator-issued one-time token; no e-mail dependency)
    def issue_reset(self, uid, by):
        token = secrets.token_urlsafe(24)
        self.db.x("INSERT INTO password_resets(user_id,token_hash,expires_at,created_by) VALUES(?,?,?,?)",
                  (uid, hashlib.sha256(token.encode()).hexdigest(), self.clock() + self.cfg.RESET_TOKEN_TTL_S, by))
        return token

    def complete_reset(self, token, new_password):
        now = self.clock()
        r = self.db.one("SELECT * FROM password_resets WHERE token_hash=?",
                        (hashlib.sha256((token or "").encode()).hexdigest(),))
        if not r or r["used_at"] or r["expires_at"] < now:
            raise AuthFailure("E_RESET", "reset token invalid or expired", 400)
        u = self.user(r["user_id"])
        problem = password_problem(new_password, self.cfg, u["username"])
        if problem:
            raise AuthFailure("E_VALIDATION", problem, 400)
        self.db.x("UPDATE password_resets SET used_at=? WHERE id=?", (now, r["id"]))
        self.set_password(u["id"], new_password)
        self.audit.log("auth.password_reset", u)
        return u


class AuthFailure(Exception):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---- Flask decorators --------------------------------------------------------------------------------------
def _services():
    return current_app.config["SERVICES"]


def load_session():
    """Populate g.user / g.session from the cookie (None when anonymous)."""
    g.user = g.session = None
    token = request.cookies.get(COOKIE)
    res = _services().auth.session(token, request.headers.get("User-Agent", ""))
    if res:
        g.session, g.user = res
        g.perms = permissions_of(g.user)
    return g.user


def require(*perms, csrf=True):
    """Authenticated user holding ALL listed permissions. State-changing methods also need the CSRF header."""
    def deco(fn):
        @wraps(fn)
        def w(*a, **k):
            if not load_session():
                return err("authentication required", "E_AUTH", 401)
            if csrf and request.method not in ("GET", "HEAD", "OPTIONS"):
                sent = request.headers.get("X-CSRF-Token", "")
                if not sent or not hmac.compare_digest(sent, g.session["csrf_token"]):
                    _services().audit.log("auth.csrf", g.user, outcome="denied", detail=request.path)
                    return err("CSRF token missing or invalid", "E_CSRF", 403)
            if g.user["must_change_password"] and not request.path.startswith("/api/v1/auth/"):
                return err("password change required", "E_PASSWORD_CHANGE", 403)
            missing = [p for p in perms if p not in g.perms]
            if missing:
                _services().audit.log("auth.forbidden", g.user, outcome="denied",
                                      detail={"path": request.path, "missing": missing})
                return err("you do not have permission for this operation", "E_FORBIDDEN", 403)
            return fn(*a, **k)
        return w
    return deco
