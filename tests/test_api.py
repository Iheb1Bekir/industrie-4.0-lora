import dataclasses
import pytest
from gateway.app import create_app
from conftest import vitals, DOC, ADM, T0


def post(client, H, d): return client.post("/api/vitals", json=d, headers=H)


def test_health_is_public(client):
    r = client.get("/api/health"); assert r.status_code == 200 and r.json["ok"] and r.json["allowed_horizons"] == [15]


def test_app_refuses_to_start_without_tokens(cfg):
    with pytest.raises(RuntimeError): create_app(dataclasses.replace(cfg, DOCTOR_TOKEN=""))


@pytest.mark.parametrize("path", ["/api/patients", "/api/alerts", "/api/patient/P001/latest", "/api/patient/P001/history", "/api/patient/P001/predict"])
def test_protected_get_requires_token(client, path):
    r = client.get(path); assert r.status_code == 401 and r.json["code"] == "E_AUTH"
    assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get(path, headers={"Authorization": "Basic " + DOC}).status_code == 401


def test_vitals_requires_token(client, clock): assert client.post("/api/vitals", json=vitals(clock)).status_code == 401


def test_report_example_request_is_accepted(client, H, clock):
    r = post(client, H, {"pid": "P001", "hr": 78, "spo2": 97, "temp": 36.7, "fall": 0, "ts": int(clock())})
    assert r.status_code == 201 and r.json["ok"] is True and r.json["stored"] is True


@pytest.mark.parametrize("bad", [dict(pid="P01"), dict(pid="x"), dict(pid=None), dict(pid="P000"), dict(hr=300), dict(hr="a"), dict(hr=True),
                                 dict(hr=None), dict(spo2=101), dict(temp=60), dict(fall=2), dict(ts=-1), dict(ts="now"), dict(ts=T0 + 10**6),
                                 dict(flags=300), dict(seq=-1), dict(hr=float("nan"))])
def test_invalid_payloads_rejected(client, H, clock, bad):
    r = post(client, H, vitals(clock, **bad)); assert r.status_code == 400 and r.json["code"] == "E_VALIDATION"


def test_malformed_json(client, H):
    r = client.post("/api/vitals", data="{nope", headers={**H, "Content-Type": "application/json"})
    assert r.status_code == 400 and r.json["code"] == "E_BAD_JSON"
    assert client.post("/api/vitals", json=[1, 2], headers=H).status_code == 400


def test_latest_history_and_404(client, H, clock):
    assert client.get("/api/patient/P001/latest", headers=H).status_code == 404
    post(client, H, vitals(clock)); clock.advance(60); post(client, H, vitals(clock, hr=80))
    lat = client.get("/api/patient/P001/latest", headers=H).json["latest"]
    assert lat["hr"] == 80 and lat["age_s"] == 0
    h = client.get("/api/patient/P001/history?hours=24", headers=H).json
    assert h["count"] == 2 and [x["hr"] for x in h["readings"]] == [78, 80]
    assert client.get("/api/patient/P001/history?hours=0", headers=H).status_code == 400
    assert client.get("/api/patient/P001/history?hours=abc", headers=H).status_code == 400
    assert client.get("/api/patient/P001/history?hours=99999", headers=H).status_code == 400
    assert client.get("/api/patient/P404/latest", headers=H).status_code == 404
    assert client.get("/api/patient/bad!/latest", headers=H).status_code == 404


def test_history_window_excludes_old_readings(client, H, clock):
    post(client, H, vitals(clock)); clock.advance(3 * 3600); post(client, H, vitals(clock))
    assert client.get("/api/patient/P001/history?hours=1", headers=H).json["count"] == 1
    assert client.get("/api/patient/P001/history?hours=24", headers=H).json["count"] == 2


def test_patients_list_multi(client, H, clock):
    post(client, H, vitals(clock)); post(client, H, vitals(clock, pid="P002"))
    assert [p["pid"] for p in client.get("/api/patients", headers=H).json["patients"]] == ["P001", "P002"]


def test_rate_limit_one_write_per_30s_default(cfg, clock, H):
    import dataclasses
    c = create_app(dataclasses.replace(cfg, VITALS_MIN_INTERVAL_S=30.0), clock=clock).test_client()
    assert post(c, H, vitals(clock)).status_code == 201
    clock.advance(10); r = post(c, H, vitals(clock))
    assert r.status_code == 429 and r.json["code"] == "E_RATE" and int(r.headers["Retry-After"]) == 20
    assert post(c, H, vitals(clock, pid="P002")).status_code == 201     # limit is per patient
    clock.advance(20); assert post(c, H, vitals(clock)).status_code == 201


def test_default_production_rate_limit_is_30s():
    from gateway.config import Config
    assert Config().VITALS_MIN_INTERVAL_S == 30 and Config().RETENTION_DAYS == 30


def test_duplicate_sequence_not_stored_twice(client, H, clock):
    d = vitals(clock, seq=5, uptime=300)
    assert post(client, H, d).status_code == 201
    r = post(client, H, d); assert r.status_code == 200 and r.json == {"ok": True, "stored": False, "duplicate": True}
    assert client.get("/api/patient/P001/history", headers=H).json["count"] == 1


def test_alert_created_deduplicated_listed_and_acked(client, H, clock):
    r = post(client, H, vitals(clock, spo2=88)); assert r.json["alerts"] == ["LOW_SPO2"]
    assert post(client, H, vitals(clock, spo2=87)).json["alerts"] == []          # no duplicate active alert
    al = client.get("/api/alerts", headers=H).json["alerts"]; assert len(al) == 1 and al[0]["severity"] == "high"
    assert client.get("/api/alerts?pid=P002", headers=H).json["alerts"] == []
    aid = al[0]["id"]
    assert client.post(f"/api/alerts/{aid}/ack", headers=H).json == {"ok": True, "id": aid, "already_acknowledged": False}
    assert client.post(f"/api/alerts/{aid}/ack", headers=H).json["already_acknowledged"] is True
    assert client.get("/api/alerts", headers=H).json["alerts"] == []
    assert len(client.get("/api/alerts?status=acknowledged", headers=H).json["alerts"]) == 1
    assert client.post("/api/alerts/9999/ack", headers=H).status_code == 404
    assert client.get("/api/alerts?status=bogus", headers=H).status_code == 400
    assert post(client, H, vitals(clock, spo2=86)).json["alerts"] == ["LOW_SPO2"]   # new alert after ack


def test_stale_data_alert(client, H, clock):
    post(client, H, vitals(clock)); clock.advance(500)
    assert [a["kind"] for a in client.get("/api/alerts", headers=H).json["alerts"]] == ["STALE_DATA"]
    assert len(client.get("/api/alerts", headers=H).json["alerts"]) == 1


def test_predict_endpoint_and_horizons(client, H, clock):
    assert client.get("/api/patient/P001/predict", headers=H).status_code == 404
    for i in range(12): post(client, H, vitals(clock, ts=int(clock()))); clock.advance(60)
    r = client.get("/api/patient/P001/predict?horizon=15", headers=H)
    assert r.status_code == 200 and r.json["status"] == "regression_fallback" and r.json["risk"] == "low" and len(r.json["pred"]["hr"]) == 3
    assert client.get("/api/patient/P001/predict", headers=H).status_code == 200      # default horizon 15
    for h in ("30", "0", "-5", "abc"):
        x = client.get(f"/api/patient/P001/predict?horizon={h}", headers=H); assert x.status_code == 400 and x.json["code"] == "E_HORIZON"


def test_predict_insufficient_history(client, H, clock):
    post(client, H, vitals(clock))
    r = client.get("/api/patient/P001/predict", headers=H); assert r.status_code == 200 and r.json["status"] == "insufficient_data"


def test_retrain_requires_admin(client, H, HA):
    assert client.post("/api/model/retrain").status_code == 401
    assert client.post("/api/model/retrain", headers=H).status_code == 401          # doctor token is NOT enough
    r = client.post("/api/model/retrain", headers=HA); assert r.status_code == 501 and r.json["code"] == "E_UNSUPPORTED"
    r = client.post("/api/model/retrain", json={"action": "reload"}, headers=HA)
    assert r.status_code == 200 and r.json["model_status"]["trained_artifact_loaded"] is False


def test_admin_token_also_accepted_for_doctor_endpoints(client, HA): assert client.get("/api/patients", headers=HA).status_code == 200


def test_error_body_format_and_unknown_route(client, H):
    r = client.get("/api/nope", headers=H); assert r.status_code == 404 and set(r.json) == {"error", "code"}


def test_dashboard_served(client):
    r = client.get("/"); assert r.status_code == 200 and b"Doctor" in r.data
    assert client.get("/static/app.js").status_code == 200
    assert DOC.encode() not in r.data and ADM.encode() not in r.data and DOC.encode() not in client.get("/static/app.js").data
