"""Security tests: authentication, sessions, CSRF, RBAC, IDOR, injection, leakage, audit integrity."""
import json

import pytest

from gateway import security as S
from v2_harness import PW

API = "/api/v1"


# ------------------------------------------------------------------ authentication
def test_passwords_are_hashed_with_scrypt_and_never_returned(v2):
    row = v2.svc.store.system.one("SELECT password_hash FROM users WHERE username='doc'")
    assert row["password_hash"].startswith("scrypt:") and PW not in row["password_hash"]
    c = v2.login("doc")
    blob = json.dumps(c.get(f"{API}/auth/me").json) + json.dumps(c.get(f"{API}/users").json)
    assert "password_hash" not in blob and "scrypt" not in blob and "totp_secret" not in blob


@pytest.mark.parametrize("pw", ["short1A!", "alllowercaseletters", "doc-Password-123", "x" * 300])
def test_weak_passwords_rejected(v2, pw):
    with pytest.raises(ValueError):
        v2.svc.auth.create_user("doc" if "doc" in pw else "newuser", pw, "assistant", "N")


def test_login_failure_is_generic_and_unknown_user_indistinguishable(v2):
    c = v2.app.test_client()
    a = c.post(f"{API}/auth/login", json={"username": "doc", "password": "wrong"})
    b = c.post(f"{API}/auth/login", json={"username": "nobody", "password": "wrong"})
    assert a.status_code == b.status_code == 401 and a.json == b.json


def test_progressive_lockout_then_recovery(v2):
    c = v2.app.test_client()
    for _ in range(5):
        assert c.post(f"{API}/auth/login", json={"username": "asst", "password": "bad"}).status_code == 401
    r = c.post(f"{API}/auth/login", json={"username": "asst", "password": PW})      # correct password, but locked
    assert r.status_code == 423 and r.json["code"] == "E_LOCKED"
    v2.clock.advance(31)
    assert c.post(f"{API}/auth/login", json={"username": "asst", "password": "bad"}).status_code == 401   # 6th failure -> 60 s
    v2.clock.advance(31)
    assert c.post(f"{API}/auth/login", json={"username": "asst", "password": PW}).status_code == 423
    v2.clock.advance(61)
    assert c.post(f"{API}/auth/login", json={"username": "asst", "password": PW}).status_code == 200


def test_login_rate_limit_per_ip(v2):
    c = v2.app.test_client()
    codes = [c.post(f"{API}/auth/login", json={"username": f"u{i}", "password": "x"}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]


def test_session_idle_and_absolute_expiry(v2):
    c = v2.login("doc")
    assert c.get(f"{API}/auth/me").status_code == 200
    v2.clock.advance(v2.cfg.SESSION_IDLE_S + 1)
    assert c.get(f"{API}/auth/me").status_code == 401                       # idle timeout
    c = v2.login("doc")
    for _ in range(30):                                                     # stay active past the absolute lifetime
        v2.clock.advance(1500)
        last = c.get(f"{API}/auth/me").status_code
    assert last == 401


def test_invalid_and_stolen_session_tokens(v2):
    c = v2.login("doc")
    anon = v2.app.test_client()
    anon.set_cookie(S.COOKIE, "not-a-real-token")
    assert anon.get(f"{API}/patients").status_code == 401
    token = c.get_cookie(S.COOKIE).value
    thief = v2.app.test_client()
    thief.set_cookie(S.COOKIE, token)
    assert thief.get(f"{API}/auth/me", headers={"User-Agent": "other-browser"}).status_code == 401   # UA binding
    assert c.get(f"{API}/auth/me").status_code == 401                        # ... and the session is revoked


def test_session_cookie_flags(v2):
    r = v2.app.test_client().post(f"{API}/auth/login", json={"username": "doc", "password": PW})
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert PW not in r.get_data(as_text=True)


def test_logout_revokes_session(v2):
    c = v2.login("doc")
    assert c.post(f"{API}/auth/logout", json={}, headers=c.csrf).status_code == 200
    assert c.get(f"{API}/auth/me").status_code == 401


def test_csrf_token_required_for_state_changes(v2):
    c = v2.login("doc")
    assert c.post(f"{API}/patients", json={"full_name": "No Csrf"}).status_code == 403
    assert c.post(f"{API}/patients", json={"full_name": "Bad Csrf"}, headers={"X-CSRF-Token": "x"}).json["code"] == "E_CSRF"
    assert c.post(f"{API}/patients", json={"full_name": "With Csrf"}, headers=c.csrf).status_code == 201


def test_password_change_and_admin_reset_flow(v2):
    c = v2.login("asst")
    assert c.post(f"{API}/auth/password", json={"current_password": "nope", "new_password": "An0ther-Good-Pass!"}, headers=c.csrf).status_code == 403
    assert c.post(f"{API}/auth/password", json={"current_password": PW, "new_password": "weak"}, headers=c.csrf).status_code == 400
    assert c.post(f"{API}/auth/password", json={"current_password": PW, "new_password": "An0ther-Good-Pass!"}, headers=c.csrf).status_code == 200
    v2.login("asst", "An0ther-Good-Pass!")
    admin = v2.login("doc")
    tok = admin.post(f"{API}/users/{v2.ids['asst']}/reset-token", json={}, headers=admin.csrf).json["reset_token"]
    anon = v2.app.test_client()
    assert anon.post(f"{API}/auth/reset/complete", json={"token": "wrong", "new_password": "Reset-Passw0rd-OK"}).status_code == 400
    assert anon.post(f"{API}/auth/reset/complete", json={"token": tok, "new_password": "Reset-Passw0rd-OK"}).status_code == 200
    assert anon.post(f"{API}/auth/reset/complete", json={"token": tok, "new_password": "Reset-Passw0rd-OK2"}).status_code == 400  # one-time
    v2.login("asst", "Reset-Passw0rd-OK")


def test_new_accounts_must_change_password_first(v2):
    admin = v2.login("doc")
    r = admin.post(f"{API}/users", json={"username": "nurse1", "password": "Initial-Passw0rd!", "role": "assistant", "full_name": "Nurse"}, headers=admin.csrf)
    assert r.status_code == 201
    c = v2.login("nurse1", "Initial-Passw0rd!")
    assert c.get(f"{API}/patients").json["code"] == "E_PASSWORD_CHANGE"
    assert c.post(f"{API}/auth/password", json={"current_password": "Initial-Passw0rd!", "new_password": "My-Own-Passw0rd!"}, headers=c.csrf).status_code == 200
    assert c.get(f"{API}/patients").status_code == 200


def test_totp_two_factor(v2):
    c = v2.login("doc")
    secret_b32 = c.post(f"{API}/auth/totp/enroll", json={}, headers=c.csrf).json["secret_base32"]
    import base64
    secret = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    assert c.post(f"{API}/auth/totp/confirm", json={"otp": "000000"}, headers=c.csrf).status_code == 400
    assert c.post(f"{API}/auth/totp/confirm", json={"otp": S.totp_now(secret, v2.clock())}, headers=c.csrf).status_code == 200
    anon = v2.app.test_client()
    assert anon.post(f"{API}/auth/login", json={"username": "doc", "password": PW}).json["code"] == "E_OTP_REQUIRED"
    assert anon.post(f"{API}/auth/login", json={"username": "doc", "password": PW, "otp": "123456"}).status_code == 401
    assert anon.post(f"{API}/auth/login", json={"username": "doc", "password": PW, "otp": S.totp_now(secret, v2.clock())}).status_code == 200
    assert v2.login("asst").post(f"{API}/auth/totp/enroll", json={}, headers={"X-CSRF-Token": "x"}).status_code == 403


def test_totp_matches_rfc6238_vector():
    assert S.totp_now(b"12345678901234567890", 59, digits=8) == "94287082"


def test_demo_accounts_refused_in_production(v2):
    v2.cfg.ENV = "production"
    assert v2.app.test_client().post(f"{API}/auth/login", json={"username": "fam", "password": PW}).status_code == 401


def test_master_key_is_mandatory_in_production(tmp_path, monkeypatch):
    from gateway.settings import PlatformConfig, load_master_key
    monkeypatch.delenv("RPM_MASTER_KEY", raising=False)
    with pytest.raises(RuntimeError):
        load_master_key(PlatformConfig(ENV="production", DATA_DIR=str(tmp_path)))


# ------------------------------------------------------------------ authorization (RBAC + IDOR)
PROTECTED = ["/patients", "/patients/1", "/patients/1/measurements", "/alerts", "/overview", "/network", "/devices", "/ml/model", "/ml/predictions",
             "/simulation", "/users", "/audit", "/system/health", "/system/status", "/notifications", "/stream", "/caregiver/patients",
             "/reports/patient/1.csv", "/reports/alerts.csv", "/staff", "/settings/thresholds"]


@pytest.mark.parametrize("path", PROTECTED)
def test_every_endpoint_requires_authentication(v2, path):
    r = v2.app.test_client().get(API + path)
    assert r.status_code == 401 and r.json["code"] == "E_AUTH"


def test_role_matrix_is_enforced_server_side(v2):
    v2.start_sim()
    v2.run_sim(20)
    doc, asst, fam = v2.login("doc"), v2.login("asst"), v2.login("fam")
    admin_only = ["/users", "/audit", "/system/health"]
    for p in admin_only:
        assert doc.get(API + p).status_code == 200
        assert asst.get(API + p).status_code == 403 and fam.get(API + p).status_code == 403
    for p in ["/patients", "/alerts", "/overview", "/network", "/devices", "/ml/predictions", "/patients/1/measurements?range=1h"]:
        assert asst.get(API + p).status_code == 200, p
        assert fam.get(API + p).status_code == 403, p               # caregivers never reach clinical endpoints
    assert asst.get(f"{API}/ml/model").status_code == 403
    assert asst.get(f"{API}/reports/patient/1.csv?range=1h").status_code == 403
    for method, path, body in [("post", "/patients", {"full_name": "X Y"}), ("post", "/devices", {"serial": "ABC-1"}),
                               ("post", "/simulation/stop", {}), ("post", "/system/mode", {"mode": "hardware"}),
                               ("put", "/patients/1/thresholds", {"hr_high": 130}), ("post", "/patients/1/caregivers", {"user_id": 1}),
                               ("post", "/ml/deploy", {"version": "x"}), ("post", "/users", {"username": "h4x"}),
                               ("post", "/patients/1/staff", {"user_id": 1}), ("post", "/devices/60001/disable", {})]:
        for c in (asst, fam):
            r = getattr(c, method)(API + path, json=body, headers=c.csrf)
            assert r.status_code == 403, (path, r.status_code)
    assert v2.svc.store.mode() == "simulation" and v2.svc.simulator.state == "running"


def test_role_sent_by_client_is_ignored(v2):
    c = v2.login("asst")
    r = c.get(f"{API}/users", headers={"X-Role": "doctor", "X-Admin": "1"})
    assert r.status_code == 403
    r = c.post(f"{API}/patients", json={"full_name": "Sneaky", "role": "doctor", "is_admin": True}, headers=c.csrf)
    assert r.status_code == 403


def test_idor_patient_scope_for_assistant_and_non_admin_doctor(v2):
    v2.start_sim(patient_count=5)                       # assistant is assigned to patients 1..3 only
    v2.run_sim(15)
    asst, doc2 = v2.login("asst"), v2.login("doc2")
    assert [p["id"] for p in asst.get(f"{API}/patients").json["patients"]] == [1, 2, 3]
    for p in ("/patients/5", "/patients/5/measurements?range=1h", "/patients/5/predictions?range=1h", "/patients/5/notes", "/patients/99"):
        assert asst.get(API + p).status_code == 404
    assert asst.get(f"{API}/alerts?patient_id=5").json["alerts"] == []
    assert doc2.get(f"{API}/patients").json["patients"] == []           # not assigned to any patient
    assert doc2.get(f"{API}/patients/1").status_code == 404
    assert doc2.get(f"{API}/reports/patient/1.pdf?range=1h").status_code == 404
    assert all(d["patient_id"] in (1, 2, 3) for d in asst.get(f"{API}/devices").json["devices"])
    denied = v2.svc.store.system.scalar("SELECT COUNT(*) FROM audit_log WHERE action='patient.access_denied'")
    assert denied >= 6


def test_assistant_alert_permissions(v2):
    v2.start_sim(scenario="C")
    v2.run_sim(40)
    asst = v2.login("asst")
    fall = next(a for a in asst.get(f"{API}/alerts").json["alerts"] if a["type"] == "FALL")
    act = lambda action: asst.post(f"{API}/alerts/{fall['id']}/action", json={"action": action}, headers=asst.csrf)  # noqa: E731
    assert act("resolve").status_code == 403 and act("false_positive").status_code == 403 and act("assign").status_code in (400, 403)
    assert act("acknowledge").status_code == 200 and act("escalate").status_code == 200
    r = asst.post(f"{API}/patients/2/notes", json={"kind": "clinical", "body": "x"}, headers=asst.csrf)
    assert r.status_code == 403
    assert asst.post(f"{API}/patients/2/notes", json={"kind": "observation", "body": "Patient looks tired"}, headers=asst.csrf).status_code == 201
    doc = v2.login("doc")
    doc.post(f"{API}/patients/2/notes", json={"kind": "clinical", "body": "CONFIDENTIAL clinical note"}, headers=doc.csrf)
    kinds = {n["kind"] for n in asst.get(f"{API}/patients/2/notes").json["notes"]}
    assert kinds == {"observation"}                                     # clinical notes are doctor-only


# ------------------------------------------------------------------ injection / XSS / leakage
def test_sql_injection_attempts_are_inert(v2):
    c = v2.login("doc")
    evil = "Robert'); DROP TABLE patients;--"
    r = c.post(f"{API}/patients", json={"full_name": evil}, headers=c.csrf)
    assert r.status_code == 201
    assert c.get(f"{API}/patients/{r.json['patient']['id']}").json["patient"]["full_name"] == evil
    assert c.get(f"{API}/alerts?status=open' OR '1'='1").json["alerts"] == []
    assert c.get(f"{API}/alerts?category=x' UNION SELECT password_hash FROM users--").json["alerts"] == []
    assert c.get(f"{API}/patients/1 OR 1=1").status_code == 404
    assert c.get(f"{API}/audit?action=' OR 1=1--").json["entries"] == []
    assert v2.app.test_client().post(f"{API}/auth/login", json={"username": "doc' OR '1'='1", "password": "x"}).status_code == 401
    assert v2.svc.store.ns("simulation").scalar("SELECT COUNT(*) FROM patients") == 1


def test_xss_payload_is_stored_verbatim_and_served_as_json_with_csp(v2):
    c = v2.login("doc")
    payload = "<script>alert(1)</script><img src=x onerror=alert(2)>"
    pid = c.post(f"{API}/patients", json={"full_name": payload}, headers=c.csrf).json["patient"]["id"]
    r = c.get(f"{API}/patients/{pid}")
    assert r.mimetype == "application/json" and r.json["patient"]["full_name"] == payload
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["Cache-Control"] == "no-store"
    page = v2.app.test_client().get("/")
    csp = page.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0] and "frame-ancestors 'none'" in csp
    assert page.headers["X-Frame-Options"] == "DENY" and page.headers["Referrer-Policy"] == "no-referrer"
    html = page.get_data(as_text=True)
    assert "<script>" not in html.replace('<script src="/assets', "").replace('<script type="module" src="/assets', "")   # no inline script


def test_frontend_escapes_dynamic_values():
    """Static check: every template interpolation in the views goes through esc()/n()/pct()/badge()/fmt helpers or is numeric."""
    from pathlib import Path
    core = (Path(__file__).resolve().parent.parent / "web/assets/js/core.js").read_text(encoding="utf-8")
    assert "replace(/[&<>\"']/g" in core and "innerHTML = `<b>${esc(title)}</b>" in core
    for f in ("views-staff.js", "views-ops.js", "app.js"):
        src = (Path(__file__).resolve().parent.parent / "web/assets/js" / f).read_text(encoding="utf-8")
        for field in ("full_name", "message", "body", "note", "serial", "label", "username", "detail"):
            import re
            # allowed non-HTML sinks: setTitle() writes textContent; select `options` and the modal TITLE argument
            # are escaped inside formModal() / infoModal()
            raw = [ln.strip()[:90] for ln in src.splitlines() if re.search(r"\$\{[a-z]\w*\." + field + r"\}", ln)
                   and "setTitle(" not in ln and "options:" not in ln and "infoModal(`${" not in ln]
            assert not raw, (f, raw)                     # e.g. ${p.full_name} without esc(...) would be an XSS hole
        assert "eval(" not in src and "document.write" not in src


def test_csv_export_neutralises_formulas(v2):
    from gateway import reports
    out = reports.to_csv(["h"], ["message"], [{"message": "=HYPERLINK(\"http://evil\")"}, {"message": "+1"}, {"message": "ok"}]).decode()
    assert "'=HYPERLINK" in out and "'+1" in out


def test_errors_do_not_leak_internals(v2):
    c = v2.login("doc")
    r = c.post(f"{API}/patients", data="{broken", headers={**c.csrf, "Content-Type": "application/json"})
    assert r.status_code == 400 and set(r.json) == {"error", "code"}
    r = c.get(f"{API}/nope")
    assert r.status_code == 404 and "Traceback" not in r.get_data(as_text=True)
    big = c.post(f"{API}/patients", data="x" * 70000, headers={**c.csrf, "Content-Type": "application/json"})
    assert big.status_code == 413


def test_device_keys_are_encrypted_at_rest_and_shown_once(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    blob = bytes(hw.svc.store.ns("hardware").one("SELECT key_enc FROM devices WHERE id=?", (did,))["key_enc"])
    assert key not in blob and len(blob) == 12 + 32 + 16
    listing = json.dumps(hw.doc.get(f"{API}/devices").json) + json.dumps(hw.doc.get(f"{API}/patients/{pid}").json)
    assert key.hex() not in listing and "key_enc" not in listing
    audit = json.dumps(hw.doc.get(f"{API}/audit").json)
    assert key.hex() not in audit and PW not in audit
    with pytest.raises(Exception):
        S.unwrap(bytes(32), blob, f"dev:hardware:{did}".encode())            # wrong master key


# ------------------------------------------------------------------ audit
def test_audit_records_security_events_and_chain_detects_tampering(v2):
    c = v2.login("doc")
    v2.app.test_client().post(f"{API}/auth/login", json={"username": "doc", "password": "bad"})
    pid = c.post(f"{API}/patients", json={"full_name": "Audit Me"}, headers=c.csrf).json["patient"]["id"]
    c.get(f"{API}/patients/{pid}")
    c.post(f"{API}/devices", json={"serial": "AUD-1", "patient_id": pid}, headers=c.csrf)
    c.get(f"{API}/reports/patient/{pid}.csv?range=1h")
    v2.login("asst").get(f"{API}/users")
    actions = {e["action"] for e in c.get(f"{API}/audit?per_page=200").json["entries"]}
    assert {"auth.login", "patient.create", "patient.view", "device.register", "report.export", "auth.forbidden"} <= actions
    outcomes = {(e["action"], e["outcome"]) for e in c.get(f"{API}/audit?per_page=200").json["entries"]}
    assert ("auth.login", "denied") in outcomes
    assert v2.svc.audit.verify()[0] is True
    v2.svc.store.system.x("UPDATE audit_log SET username='someone-else' WHERE id=2")
    ok, _, bad = v2.svc.audit.verify()
    assert ok is False and bad == 2
