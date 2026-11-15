"""End-to-end acceptance scenarios (directive section 15.4, Tests 1-12) run in SIMULATION mode through the real
pipeline: simulator -> signed protocol frames -> network model -> ingestion -> inference -> alerts -> API."""
import json
import os

import pytest

from v2_harness import ROOT

API = "/api/v1"


def test_01_register_patient_and_associate_device(v2):
    c = v2.login("doc")
    assert c.get(f"{API}/system/status").json["mode"] == "simulation"
    p = c.post(f"{API}/patients", json={"full_name": "Test Patient", "date_of_birth": "1950-04-02", "sex": "F"}, headers=c.csrf)
    assert p.status_code == 201 and p.json["patient"]["code"] == "P001" and p.json["patient"]["is_synthetic"] == 1
    pid = p.json["patient"]["id"]
    d = c.post(f"{API}/devices", json={"serial": "VIRT-0001", "label": "node"}, headers=c.csrf)
    assert d.status_code == 201 and d.json["device"]["status"] == "provisioned" and len(d.json["provisioning"]["device_key_hex"]) == 64
    did = d.json["device"]["id"]
    assert str(did) in d.json["provisioning"]["serial_command"]
    r = c.post(f"{API}/devices/{did}/pair", json={"patient_id": pid}, headers=c.csrf)
    assert r.json["device"]["status"] == "active" and r.json["device"]["patient_id"] == pid and r.json["device"]["online"] == 0
    detail = c.get(f"{API}/patients/{pid}").json["patient"]
    assert detail["device"]["id"] == did and detail["state"] == "no_data" and detail["devices"][0]["serial"] == "VIRT-0001"
    assert c.post(f"{API}/patients", json={"full_name": "x"}, headers=c.csrf).status_code == 400
    assert c.post(f"{API}/patients", json={"full_name": "Dup", "id": pid}, headers=c.csrf).status_code == 409
    assert c.post(f"{API}/devices", json={"serial": "VIRT-0001"}, headers=c.csrf).status_code == 409


def test_02_normal_measurements_flow_in_real_time(v2):
    c = v2.login("doc")
    events = []
    v2.svc.broker.subscribe(lambda e: events.append(e) or None)
    v2.start_sim(scenario="A")
    v2.run_sim(60)                                                     # 10 simulated minutes at x10
    o = c.get(f"{API}/overview").json
    assert o["mode"] == "simulation" and o["data_source"].startswith("SIMULATION")
    assert o["kpi"]["patients_total"] == 3 and o["kpi"]["patients_connected"] == 3 and o["kpi"]["alerts_open"] == 0
    assert all(p["state"] == "normal" and not p["latest"]["stale"] for p in o["patients"])
    assert o["network"]["valid"] >= 55 and o["network"]["pdr"] > 0.9 and o["network"]["kind"] == "simulated"
    types = {e["type"] for e in events}
    assert {"measurement", "prediction", "network", "simulation", "device"} <= types      # pushed live, no polling needed
    m = [e for e in events if e["type"] == "measurement"]
    assert len(m) == o["network"]["valid"] and abs(m[-1]["data"]["ts"] - v2.clock()) < 5   # real (current) timestamps
    pts = c.get(f"{API}/patients/1/measurements?range=15m").json["points"]
    assert len(pts) >= 15 and all(50 < p["heart_rate"] < 110 and p["spo2"] >= 92 for p in pts)
    assert c.get(f"{API}/network").json["counters"]["relay_assisted"] > 0                 # patient 3 is relayed


def test_03_abnormal_heart_rate_creates_alert(v2):
    c = v2.login("doc")
    v2.start_sim(scenario="A")
    v2.run_sim(10)
    c.post(f"{API}/simulation/event", json={"patient_id": 2, "event": "hr_rise"}, headers=c.csrf)
    v2.run_sim(70)
    assert "HIGH_HR" in v2.open_alerts("simulation", 2)
    a = next(x for x in c.get(f"{API}/alerts?patient_id=2").json["alerts"] if x["type"] == "HIGH_HR")
    assert a["category"] == "threshold" and a["severity"] in ("high", "critical") and "120" in a["message"]
    assert c.get(f"{API}/patients/2").json["patient"]["state"] == "critical"
    assert v2.open_alerts("simulation", 1) == [] or "HIGH_HR" not in v2.open_alerts("simulation", 1)


def test_04_fall_creates_high_priority_alert(v2):
    c = v2.login("doc")
    v2.start_sim(scenario="C")
    v2.run_sim(30)
    falls = [a for a in c.get(f"{API}/alerts").json["alerts"] if a["type"] == "FALL"]
    assert len(falls) == 1 and falls[0]["severity"] == "critical" and falls[0]["patient_id"] == 2
    m = v2.svc.store.ns("simulation").one("SELECT payload_type, alert_level, critical FROM measurements WHERE id=?", (falls[0]["measurement_id"],))
    assert (m["payload_type"], m["alert_level"], m["critical"]) == (3, 3, 1)               # event frame, alertLevel 3
    notes = c.get(f"{API}/notifications").json
    assert notes["unread"] >= 1 and "Fall detected" in notes["notifications"][-1]["body"]


def test_05_gradual_trend_is_predicted_before_the_threshold_alert(v2):
    """Scenario G. The model must warn BEFORE the immediate threshold alert, with an explanation."""
    c = v2.login("doc")
    v2.start_sim(scenario="G", speed=4)
    v2.run_sim(330)
    db = v2.svc.store.ns("simulation")
    alerts = {a["type"]: a for a in db.q("SELECT * FROM alerts WHERE patient_id=1 ORDER BY id")}
    assert "PREDICTED_DETERIORATION" in alerts and "HIGH_HR" in alerts, sorted(alerts)
    pred, thr = alerts["PREDICTED_DETERIORATION"], alerts["HIGH_HR"]
    assert pred["created_at"] < thr["created_at"]
    assert pred["category"] == "predictive" and pred["severity"] == "warning" and pred["prediction_id"]
    p = db.one("SELECT * FROM predictions WHERE id=?", (pred["prediction_id"],))
    expl = json.loads(p["explanation"])
    assert p["status"] == "ok" and p["risk_category"] == "high" and p["score"] >= p["threshold"] and p["model_version"]
    assert expl and all({"feature", "label", "value", "contribution", "direction"} <= set(e) for e in expl)
    assert any(e["feature"].startswith("hr_") and e["contribution"] > 0 for e in expl)       # heart-rate trend drives it
    hist = c.get(f"{API}/patients/1/predictions?range=1h").json["predictions"]
    assert {h["risk_category"] for h in hist if h["status"] == "ok"} >= {"low", "high"}
    assert c.get(f"{API}/ml/model").json["runtime"]["latency_ms"]["n"] > 0
    # the unaffected patients never get a predictive alert in this scenario
    assert "PREDICTED_DETERIORATION" not in v2.open_alerts("simulation", 2)


def test_06_patients_appear_on_the_mahdia_map(v2):
    c = v2.login("doc")
    v2.start_sim(scenario="C")
    v2.run_sim(30)
    pats = c.get(f"{API}/patients").json["patients"]
    for p in pats:
        loc = p["location"]
        assert loc["source"] == "simulated" and loc["is_current"] and loc["accuracy_m"] == 25.0      # labelled fictional
        assert abs(loc["lat"] - 35.5047) < 0.05 and abs(loc["lon"] - 11.0622) < 0.06                 # Mahdia demo area
    assert {p["id"]: p["state"] for p in pats}[2] == "critical"                                      # fall -> critical marker
    first = {p["id"]: (p["location"]["lat"], p["location"]["lon"]) for p in pats}
    v2.run_sim(60)
    moved = {p["id"]: (p["location"]["lat"], p["location"]["lon"]) for p in c.get(f"{API}/patients").json["patients"]}
    assert moved != first                                                                             # simulated movement


def test_07_doctor_sees_all_authorized_patients(v2):
    v2.start_sim(patient_count=5)
    v2.run_sim(15)
    doc = v2.login("doc")
    assert [p["id"] for p in doc.get(f"{API}/patients").json["patients"]] == [1, 2, 3, 4, 5]
    d = doc.get(f"{API}/patients/4").json["patient"]
    assert d["primary_doctor"]["id"] == v2.ids["doc"] and d["latest"] and d["thresholds"]["hr_high"] == 120
    for path in ("/alerts", "/network", "/ml/model", "/devices", "/simulation", "/users", "/audit", "/system/health"):
        assert doc.get(API + path).status_code == 200


def test_08_assistant_has_restricted_access(v2):
    v2.start_sim(patient_count=5)
    v2.run_sim(15)
    asst = v2.login("asst")
    me = asst.get(f"{API}/auth/me").json
    assert me["user"]["role"] == "assistant" and "alerts.acknowledge" in me["permissions"] and "alerts.resolve" not in me["permissions"]
    assert not {"patients.register", "devices.manage", "users.manage", "simulation.control", "reports.export", "ml.read"} & set(me["permissions"])
    assert [p["id"] for p in asst.get(f"{API}/patients").json["patients"]] == [1, 2, 3]
    assert asst.get(f"{API}/overview").json["kpi"]["patients_total"] == 3
    assert asst.get(f"{API}/patients/4").status_code == 404
    assert set(asst.get(f"{API}/simulation").json["simulation"]) == {"state", "session_id", "config", "sim_time_s", "scenarios"}


def test_09_caregiver_sees_only_the_consented_patient_in_reduced_form(v2):
    v2.start_sim(scenario="C", patient_count=3)
    v2.run_sim(30)
    doc, fam, fam2 = v2.login("doc"), v2.login("fam"), v2.login("fam2")
    mine = fam.get(f"{API}/caregiver/patients").json["patients"]
    assert [p["patient_id"] for p in mine] == [1] and mine[0]["is_simulation"] is True
    assert set(mine[0]) == {"patient_id", "name", "relationship", "state", "device_connected", "last_measurement_ts", "stale", "vitals",
                            "location", "warnings", "contact", "is_simulation"}
    blob = json.dumps(mine)
    for secret in ("explanation", "score", "rssi", "seq_no", "date_of_birth", "address", "note", "threshold"):
        assert secret not in blob
    assert fam.get(f"{API}/caregiver/patients/1/history").status_code == 200
    assert fam.get(f"{API}/caregiver/patients/2/history").status_code == 404        # another patient
    assert fam2.get(f"{API}/caregiver/patients").json["patients"] == []             # no consent -> nothing
    for path in ("/patients", "/patients/1", "/alerts", "/patients/1/notes", "/overview", "/patients/1/measurements"):
        assert fam.get(API + path).status_code == 403
    # grant fam2 access to patient 2 (the one who fell) without vitals; then revoke
    r = doc.post(f"{API}/patients/2/caregivers", json={"user_id": v2.ids["fam2"], "relationship": "son", "can_view_vitals": False}, headers=doc.csrf)
    assert r.status_code == 400                                                      # consent_given_by is mandatory
    r = doc.post(f"{API}/patients/2/caregivers", json={"user_id": v2.ids["fam2"], "relationship": "son", "can_view_vitals": False,
                                                       "consent_given_by": "Patient 2"}, headers=doc.csrf)
    assert r.status_code == 201
    view = fam2.get(f"{API}/caregiver/patients").json["patients"][0]
    assert view["patient_id"] == 2 and view["vitals"] is None and view["location"] is None and view["state"] == "urgent"
    assert [w["label"] for w in view["warnings"]] == ["Fall detected"]
    assert fam2.get(f"{API}/caregiver/patients/2/history").json["hours"] == []
    assert doc.delete(f"{API}/patients/2/caregivers/{r.json['link_id']}", headers=doc.csrf).status_code == 200
    assert fam2.get(f"{API}/caregiver/patients").json["patients"] == []             # revocation is immediate
    # expiry
    r = doc.post(f"{API}/patients/3/caregivers", json={"user_id": v2.ids["fam2"], "consent_given_by": "P3", "expires_at": v2.clock() + 3600}, headers=doc.csrf)
    assert len(fam2.get(f"{API}/caregiver/patients").json["patients"]) == 1
    v2.clock.advance(3601)
    fam2 = v2.login("fam2")
    assert fam2.get(f"{API}/caregiver/patients").json["patients"] == []


def test_10_disconnected_device_is_detected_by_the_backend(v2):
    c = v2.login("doc")
    v2.start_sim(scenario="A")
    v2.run_sim(20)
    c.post(f"{API}/simulation/event", json={"patient_id": 2, "event": "disconnect"}, headers=c.csrf)
    v2.run_sim(25)
    devs = {d["patient_id"]: d for d in c.get(f"{API}/devices").json["devices"]}
    assert devs[2]["online"] == 0 and devs[1]["online"] == 1 and devs[3]["online"] == 1
    assert v2.open_alerts("simulation", 2) == ["DEVICE_OFFLINE"]
    p2 = c.get(f"{API}/patients/2").json["patient"]
    assert p2["state"] == "critical" and p2["latest"]["heart_rate"] is not None       # last value kept, never shown as "normal now"
    assert c.get(f"{API}/overview").json["kpi"]["devices_offline"] == 1
    assert any(e["kind"] == "offline" for e in c.get(f"{API}/network").json["events"])
    c.post(f"{API}/simulation/event", json={"patient_id": 2, "event": "reconnect"}, headers=c.csrf)
    v2.run_sim(10)
    assert v2.open_alerts("simulation", 2) == [] and c.get(f"{API}/patients/2").json["patient"]["device"]["online"] == 1


def test_11_stopping_simulation_and_isolation_from_hardware_data(v2):
    c = v2.login("doc")
    hw_db, sim_db = v2.svc.store.ns("hardware"), v2.svc.store.ns("simulation")
    # a real patient exists in hardware mode before the simulation runs
    c.post(f"{API}/system/mode", json={"mode": "hardware"}, headers=c.csrf)
    pid, did, key = v2.hw_patient(c, name="Real Person")
    assert v2.ingest(v2.frame(pid, did, key, 1))["outcome"] == "stored"
    assert c.post(f"{API}/simulation/start", json={}, headers=c.csrf).status_code == 409   # cannot simulate in hardware mode
    c.post(f"{API}/system/mode", json={"mode": "simulation"}, headers=c.csrf)
    v2.start_sim(scenario="F", patient_count=5)
    v2.run_sim(40)
    n_sim = sim_db.scalar("SELECT COUNT(*) FROM measurements")
    assert n_sim > 30
    assert sim_db.scalar("SELECT COUNT(*) FROM measurements WHERE sim_session_id IS NULL OR data_source<>'simulation'") == 0
    assert sim_db.scalar("SELECT COUNT(*) FROM alerts WHERE sim_session_id IS NULL AND type<>'DEVICE_OFFLINE'") == 0
    assert sim_db.scalar("SELECT COUNT(*) FROM patients WHERE is_synthetic=0") == 0
    # hardware database untouched by the simulation
    assert hw_db.scalar("SELECT COUNT(*) FROM measurements") == 1 and hw_db.scalar("SELECT COUNT(*) FROM patients") == 1
    assert hw_db.scalar("SELECT COUNT(*) FROM alerts") == 0 and hw_db.scalar("SELECT COUNT(*) FROM devices WHERE is_virtual=1") == 0
    # a simulated frame replayed against the hardware pipeline is rejected (virtual device ids are unknown there)
    vp = v2.svc.simulator.patients[0]
    from gateway import protocol as P
    raw = P.encode({"patientId": vp.patient_id, "sourceId": vp.device_id, "destinationId": 1, "seqNo": 9999, "timestamp": int(v2.clock()),
                    "heartRate": 70, "spO2": 97, "temperature": 36.6}, vp.key)
    assert v2.ingest(raw)["outcome"] == "unknown_device"
    # pause / resume / stop
    assert c.post(f"{API}/simulation/pause", json={}, headers=c.csrf).json["simulation"]["state"] == "paused"
    v2.run_sim(20)
    assert sim_db.scalar("SELECT COUNT(*) FROM measurements") == n_sim                       # paused: nothing new
    assert c.post(f"{API}/simulation/resume", json={}, headers=c.csrf).json["simulation"]["state"] == "running"
    v2.run_sim(15)
    n2 = sim_db.scalar("SELECT COUNT(*) FROM measurements")
    assert n2 > n_sim
    assert c.post(f"{API}/simulation/stop", json={}, headers=c.csrf).json["simulation"]["state"] == "stopped"
    v2.run_sim(30)
    assert sim_db.scalar("SELECT COUNT(*) FROM measurements") == n2                          # stopped: no new synthetic data anywhere
    assert hw_db.scalar("SELECT COUNT(*) FROM measurements") == 1
    # switching to hardware shows only the real patient and stops any running engine; real data survives a simulation reset
    v2.start_sim()
    c.post(f"{API}/system/mode", json={"mode": "hardware"}, headers=c.csrf)
    assert v2.svc.simulator.state == "stopped"
    assert [p["full_name"] for p in c.get(f"{API}/patients").json["patients"]] == ["Real Person"]
    assert c.get(f"{API}/overview").json["data_source"] == "hardware"
    v2.svc.simulator.reset({}, v2.svc.auth.user(v2.ids["doc"]))
    assert hw_db.scalar("SELECT COUNT(*) FROM measurements") == 1 and hw_db.scalar("SELECT COUNT(*) FROM patients") == 1


def test_12_dashboard_model_metrics_equal_the_saved_evaluation_artifacts(v2):
    c = v2.login("doc")
    d = c.get(f"{API}/ml/model").json
    version = d["runtime"]["model_version"]
    assert d["runtime"]["loaded"] and version
    mdir = os.path.join(ROOT, "ml", "models", version)
    with open(os.path.join(mdir, "metrics.json")) as f:
        saved = json.load(f)
    with open(os.path.join(mdir, "metadata.json")) as f:
        meta = json.load(f)
    assert d["metrics"] == saved and d["metadata"] == meta                        # served verbatim, nothing hardcoded
    sel = saved["models"][meta["model_name"]]["test"]
    cm = sel["confusion_matrix"]
    n = cm["tn"] + cm["fp"] + cm["fn"] + cm["tp"]
    assert n == sel["n"] == meta["dataset"]["samples"]["test"]
    assert sel["accuracy"] == pytest.approx((cm["tp"] + cm["tn"]) / n)
    assert sel["precision"] == pytest.approx(cm["tp"] / (cm["tp"] + cm["fp"]))
    assert sel["recall"] == sel["sensitivity"] == pytest.approx(cm["tp"] / (cm["tp"] + cm["fn"]))
    assert sel["specificity"] == pytest.approx(cm["tn"] / (cm["tn"] + cm["fp"]))
    assert sel["fpr"] == pytest.approx(1 - sel["specificity"]) and sel["fnr"] == pytest.approx(1 - sel["recall"])
    assert sel["f1"] == pytest.approx(2 * sel["precision"] * sel["recall"] / (sel["precision"] + sel["recall"]))
    # the generated documentation quotes the same numbers
    doc_md = open(os.path.join(ROOT, "docs", "MODEL_EVALUATION.md"), encoding="utf-8").read()
    assert f"TN = {cm['tn']}" in doc_md and f"TP = {cm['tp']}" in doc_md and meta["version"] in doc_md and f"{sel['pr_auc']:.4f}" in doc_md
    # test patients are disjoint from the rest (split by patient)
    ds = meta["dataset"]
    assert len(set(ds["test_patient_ids"])) == ds["patients"]["test"] and sum(ds["patients"].values()) == 600


@pytest.mark.parametrize("scenario,expected", [("B", {1: {"HIGH_HR", "LOW_SPO2"}}), ("D", {1: {"LOW_SPO2"}}),
                                               ("F", {1: {"HIGH_HR"}, 2: {"FALL"}, 3: {"LOW_SPO2"}})])
def test_scenarios_produce_their_documented_events(v2, scenario, expected):
    v2.start_sim(scenario=scenario, patient_count=5 if scenario == "F" else 3)
    v2.run_sim(75)
    for pid, types in expected.items():
        assert types <= set(v2.open_alerts("simulation", pid)), (pid, v2.open_alerts("simulation", pid))


def test_scenario_e_network_failure(v2):
    c = v2.login("doc")
    v2.start_sim(scenario="E")
    v2.run_sim(45)
    assert "DEVICE_OFFLINE" in v2.open_alerts("simulation", 2)
    net = c.get(f"{API}/network").json
    d2 = next(d for d in net["devices"] if d["patient_id"] == 2)
    assert d2["lost_estimate"] > 0 and d2["pdr"] < 1 and net["simulation_engine"]["lost_injected"] > 0
    assert net["kind"] == "simulated" and "not LoRaWAN" in net["protocol"]


def test_simulated_network_loss_duplicates_delay_and_relays(v2):
    c = v2.login("doc")
    v2.start_sim(scenario="A", patient_count=20, base_loss=0.05, duplicate_rate=0.1, delay_rate=0.1)
    v2.run_sim(60)
    net = c.get(f"{API}/network").json
    st, cn = net["simulation_engine"], net["counters"]
    assert st["lost_injected"] > 0 and st["duplicated"] > 0 and st["delayed"] > 0 and st["relay_forwards"] > 0
    assert 0 < cn["duplicates"] <= st["duplicated"] and cn["lost_estimate"] > 0 and 0.8 < net["pdr"] < 1   # some copies still in flight
    assert len([n for n in net["topology"]["nodes"] if n["type"] == "relay"]) == 3
    assert len([n for n in net["topology"]["nodes"] if n["type"] == "patient"]) == 20         # research topology: 20 / 3 / 1
    relayed = [d for d in net["devices"] if d["last_hop_count"]]
    assert len(relayed) == 4 and {d["last_hop_count"] for d in relayed} <= {1, 2, 3}          # outer ring via relays, as in the NED file
    assert sum(r["forwarded"] for r in net["relays"]) == st["relay_forwards"]
    sim = c.get(f"{API}/simulation").json["simulation"]
    assert sum(p["delivered"] for p in sim["patients"]) == cn["valid"]


def test_simulation_config_validation_and_reset(v2):
    c = v2.login("doc")
    for bad in ({"scenario": "Z"}, {"patient_count": 0}, {"patient_count": 21}, {"speed": 1000}, {"interval_s": 1}):
        assert c.post(f"{API}/simulation/start", json=bad, headers=c.csrf).status_code == 400, bad
    assert c.post(f"{API}/simulation/event", json={"patient_id": 1, "event": "fall"}, headers=c.csrf).status_code == 409   # not running
    v2.start_sim()
    assert c.post(f"{API}/simulation/event", json={"patient_id": 1, "event": "explode"}, headers=c.csrf).status_code == 400
    assert c.post(f"{API}/simulation/event", json={"patient_id": 77, "event": "fall"}, headers=c.csrf).status_code == 404
    v2.run_sim(10)
    c.post(f"{API}/simulation/stop", json={}, headers=c.csrf)
    assert c.post(f"{API}/simulation/reset", json={"patient_count": 5}, headers=c.csrf).status_code == 200
    db = v2.svc.store.ns("simulation")
    assert db.scalar("SELECT COUNT(*) FROM measurements") == 0 and db.scalar("SELECT COUNT(*) FROM patients") == 5


def test_real_location_requires_consent_and_ages(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    assert hw.doc.get(f"{API}/patients/{pid}").json["patient"]["location"] is None        # no GPS assumed, nothing invented
    body = {"lat": 35.5047, "lon": 11.0622, "accuracy_m": 40}
    assert hw.doc.post(f"{API}/patients/{pid}/location", json=body, headers=hw.doc.csrf).status_code == 400   # consent missing
    assert hw.doc.post(f"{API}/patients/{pid}/location", json={**body, "lat": 123, "consent_given_by": "P"}, headers=hw.doc.csrf).status_code == 400
    assert hw.doc.post(f"{API}/patients/{pid}/location", json={**body, "consent_given_by": "The Patient"}, headers=hw.doc.csrf).status_code == 201
    loc = hw.doc.get(f"{API}/patients/{pid}").json["patient"]["location"]
    assert loc["source"] == "manual" and loc["is_current"] is True and loc["accuracy_m"] == 40
    hw.clock.advance(900)
    hw.doc = hw.login("doc")
    loc = hw.doc.get(f"{API}/patients/{pid}").json["patient"]["location"]
    assert loc["is_current"] is False and loc["age_s"] == 900                            # old position is labelled as old
    assert hw.doc.delete(f"{API}/patients/{pid}/location-consent", headers=hw.doc.csrf).json["revoked"] == 1
    assert hw.doc.get(f"{API}/patients/{pid}").json["patient"]["location"] is None       # consent revoked -> hidden


def test_research_results_are_served_and_labelled(v2, tmp_path):
    import shutil
    os.makedirs(v2.cfg.RESEARCH_DIR, exist_ok=True)
    src = os.path.join(ROOT, "simulation", "omnetpp", "imported_results")
    for f in os.listdir(src):
        shutil.copy(os.path.join(src, f), v2.cfg.RESEARCH_DIR)
    r = v2.login("doc").get(f"{API}/network/research").json
    assert r["kind"] == "omnetpp_flora_simulation" and "not connected to physical radios" in r["note"]
    run = r["runs"][0]
    assert (run["patients"], run["relays"], run["generated"], run["doctor_valid"]) == (20, 3, 80, 79)   # as in the research README
