"""End-to-end: synthetic telemetry -> gateway simulator -> Flask API -> SQLite -> alerts + prediction -> dashboard API."""
import pytest
from gateway.bridge import Gateway
from gateway.radio import SimulationTransport
from simulated_patients import lines, SCENARIOS


def run(client, H, clock, pid, scenario, count):
    def fwd(payload):
        r = client.post("/api/vitals", json=payload, headers=H); return r.status_code, r.json
    gw = Gateway(SimulationTransport(lines(pid, scenario, count)), fwd, clock=clock)
    # advance fake time per packet like a real 60 s cycle
    orig = gw.handle
    def handle(raw): out = orig(raw); clock.advance(60); return out
    gw.handle = handle
    return gw.run()


def test_normal_stream_flows_to_dashboard_endpoints(client, H, clock):
    stats = run(client, H, clock, "P001", "NORMAL", 15)
    assert stats["forwarded"] == 15 and stats["lost_estimate"] == 0
    lat = client.get("/api/patient/P001/latest", headers=H).json["latest"]
    assert lat["synthetic"] == 1 and lat["source"] == "sim-serial" and lat["fall"] == 0
    assert client.get("/api/patient/P001/history", headers=H).json["count"] == 15
    p = client.get("/api/patient/P001/predict", headers=H).json
    assert p["status"] == "regression_fallback" and p["risk"] == "low" and p["synthetic_input"] is True
    assert client.get("/api/alerts", headers=H).json["alerts"] == []


@pytest.mark.parametrize("scenario,kind", [("LOW_SPO2", "LOW_SPO2"), ("HIGH_HR", "HIGH_HR"), ("HIGH_TEMP", "HIGH_TEMP"),
                                           ("FALL", "FALL"), ("SENSOR_ERROR", "SENSOR_ERROR")])
def test_each_scenario_produces_exactly_one_active_alert(client, H, clock, scenario, kind):
    run(client, H, clock, "P002", scenario, 3)
    al = client.get("/api/alerts?pid=P002", headers=H).json["alerts"]
    assert [a["kind"] for a in al] == [kind]
    assert client.post(f"/api/alerts/{al[0]['id']}/ack", headers=H).status_code == 200
    assert client.get("/api/alerts?pid=P002", headers=H).json["alerts"] == []


def test_sensor_error_stores_nulls_and_flags(client, H, clock):
    run(client, H, clock, "P003", "SENSOR_ERROR", 1)
    r = client.get("/api/patient/P003/latest", headers=H).json["latest"]
    assert r["hr"] is None and r["spo2"] is None and r["temp"] is None and r["flags"] & 12 == 12


def test_replaying_same_packets_creates_no_duplicates(client, H, clock):
    run(client, H, clock, "P004", "NORMAL", 3); run(client, H, clock, "P004", "NORMAL", 3)
    assert client.get("/api/patient/P004/history", headers=H).json["count"] == 3


def test_multiple_patients_in_one_stream(client, H, clock):
    run(client, H, clock, "P001", "NORMAL", 2); run(client, H, clock, "P002", "FALL", 2)
    ps = {p["pid"]: p for p in client.get("/api/patients", headers=H).json["patients"]}
    assert set(ps) == {"P001", "P002"} and ps["P002"]["active_alerts"] == 1 and ps["P001"]["active_alerts"] == 0


def test_simulator_cli_generate_backfills_virtual_timestamps(cfg, monkeypatch, capsys, tmp_path):
    """Runs the real CLI against a live server thread-free via a patched forwarder (no network)."""
    import time, json
    import gateway_simulator as gs
    from gateway.app import create_app
    c = create_app(cfg).test_client()
    monkeypatch.setattr(gs, "HttpForwarder", lambda url, tok: (lambda p: (lambda r: (r.status_code, r.json))(c.post("/api/vitals", json=p, headers={"Authorization": "Bearer doctor-test-token"}))))
    gs.main(["--generate", "NORMAL", "--pid", "P001", "--count", "12", "--token", "x"])
    out = json.loads(capsys.readouterr().out)
    assert out["forwarded"] == 12
    H = {"Authorization": "Bearer doctor-test-token"}
    ts = [r["ts"] for r in c.get("/api/patient/P001/history", headers=H).json["readings"]]
    assert ts == sorted(ts) and ts[-1] - ts[0] == 660 and abs(ts[-1] - time.time()) < 5
    assert c.get("/api/patient/P001/predict", headers=H).json["status"] == "regression_fallback"
