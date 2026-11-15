"""Ingestion pipeline, alert engine, device liveness, hardware ingestion endpoint (hardware namespace, fake clock)."""
import json

from gateway import protocol as P

API = "/api/v1"


def test_valid_frame_is_stored_with_all_structure_fields(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    res = hw.ingest(hw.frame(pid, did, key, 1, heartRate=81, spO2=96, temperature=36.9, routingMode=1, hopCount=0), rssi=-97.5, snr=8.25)
    assert res["outcome"] == "stored"
    m = hw.svc.store.ns("hardware").one("SELECT * FROM measurements WHERE id=?", (res["measurement_id"],))
    assert (m["patient_id"], m["device_id"], m["seq_no"], m["heart_rate"], m["spo2"], m["temperature"]) == (pid, did, 1, 81, 96, 36.9)
    assert (m["source_id"], m["destination_id"], m["routing_mode"], m["max_hop_count"], m["payload_type"]) == (did, 1, 1, 4, 1)
    assert m["data_source"] == "hardware" and m["sim_session_id"] is None and m["rssi"] == -97.5 and m["quality"] == "ok"
    assert m["ts"] == hw.clock()                     # time-synced device clock within tolerance is used


def test_rejections_unknown_unpaired_disabled_wrong_key_wrong_routing(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    assert hw.ingest(hw.frame(pid, 999, key, 1))["outcome"] == "unknown_device"
    assert hw.ingest(hw.frame(pid, did, bytes(32), 1))["outcome"] == "auth_fail"          # patient/device id alone is not enough
    assert hw.ingest(hw.frame(pid + 1, did, key, 1))["outcome"] == "rejected"             # patientId does not match the pairing
    assert hw.ingest(hw.frame(pid, did, key, 1, destinationId=7))["outcome"] == "rejected"
    assert hw.ingest(b"\x02" + b"\x00" * 10)["outcome"] == "malformed"
    bad = bytearray(hw.frame(pid, did, key, 1)); bad[3] ^= 0xFF
    assert hw.ingest(bytes(bad))["outcome"] == "crc_error"
    r = hw.doc.post(f"{API}/devices", json={"serial": "SPARE-1"}, headers=hw.doc.csrf).json
    spare_key = bytes.fromhex(r["provisioning"]["device_key_hex"])
    assert hw.ingest(hw.frame(pid, r["device"]["id"], spare_key, 1))["outcome"] == "rejected"   # registered but not paired
    hw.doc.post(f"{API}/devices/{did}/disable", json={}, headers=hw.doc.csrf)
    assert hw.ingest(hw.frame(pid, did, key, 1))["outcome"] == "rejected"
    db = hw.svc.store.ns("hardware")
    assert db.scalar("SELECT COUNT(*) FROM measurements") == 0
    c = {r["name"]: r["value"] for r in db.q("SELECT * FROM network_counters")}
    assert c["auth_failures"] == 1 and c["unknown_device"] == 1 and c["crc_errors"] == 1 and c["malformed"] == 1 and c["rejected"] == 4
    assert db.one("SELECT online FROM devices WHERE id=?", (did,))["online"] == 0       # never "connected" without valid frames


def test_repeated_auth_failures_raise_a_network_alert(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    for seq in (1, 2, 3):
        hw.ingest(hw.frame(pid, did, bytes(32), seq))
    assert "AUTH_FAILURES" in hw.open_alerts("hardware")


def test_duplicates_replays_out_of_order_and_loss_estimate(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    f = {s: hw.frame(pid, did, key, s) for s in (1, 2, 3, 5, 6, 200)}
    assert [hw.ingest(f[s])["outcome"] for s in (1, 2)] == ["stored", "stored"]
    assert hw.ingest(f[2])["outcome"] == "duplicate"
    assert hw.ingest(P.relay_forward(f[2]))["outcome"] == "duplicate"        # same (device, seqNo) arriving via a relay
    assert hw.ingest(f[5])["outcome"] == "stored"                            # 3 and 4 missing -> 2 lost
    dev = lambda: hw.svc.store.ns("hardware").one("SELECT * FROM devices WHERE id=?", (did,))  # noqa: E731
    assert dev()["lost_estimate"] == 2
    assert hw.ingest(f[3])["outcome"] == "stored"                            # late, out of order -> accepted once
    assert dev()["lost_estimate"] == 1 and dev()["out_of_order_count"] == 1
    assert hw.ingest(f[3])["outcome"] == "duplicate"
    assert hw.ingest(f[200])["outcome"] == "stored"
    assert hw.ingest(f[6])["outcome"] == "replay"                            # far older than the window: replayed capture
    assert hw.svc.store.ns("hardware").scalar("SELECT COUNT(*) FROM measurements") == 5
    assert dev()["dup_count"] == 3 and dev()["replay_count"] == 1


def test_key_rotation_restarts_sequence_and_invalidates_old_key(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    assert hw.ingest(hw.frame(pid, did, key, 50))["outcome"] == "stored"
    new = bytes.fromhex(hw.doc.post(f"{API}/devices/{did}/rotate-key", json={}, headers=hw.doc.csrf).json["provisioning"]["device_key_hex"])
    assert hw.ingest(hw.frame(pid, did, key, 51))["outcome"] == "auth_fail"
    assert hw.ingest(hw.frame(pid, did, new, 1))["outcome"] == "stored"


def test_hop_limit_and_relay_assisted_delivery(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    raw = hw.frame(pid, did, key, 1, routingMode=1)
    for _ in range(3):
        raw = P.relay_forward(raw)
    assert hw.ingest(raw)["outcome"] == "stored"
    assert hw.svc.store.ns("hardware").one("SELECT hop_count FROM measurements")["hop_count"] == 3
    over = hw.frame(pid, did, key, 2, hopCount=6, maxHopCount=8)
    assert hw.ingest(over)["outcome"] == "rejected"                          # gateway limit MAX_HOP_COUNT = 4


def test_missing_values_are_never_treated_as_normal(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    res = hw.ingest(hw.frame(pid, did, key, 1, heartRate=None, spO2=None, temperature=None))
    assert res["outcome"] == "stored" and res["alerts"] == ["SENSOR_FAULT"]
    m = hw.svc.store.ns("hardware").one("SELECT * FROM measurements")
    assert m["heart_rate"] is None and m["spo2"] is None and m["temperature"] is None and m["quality"] == "sensor_fault"
    s = hw.doc.get(f"{API}/patients/{pid}").json["patient"]
    assert s["latest"]["abnormal"] is False and s["latest"]["heart_rate"] is None
    assert res["prediction"]["status"] == "insufficient_data"               # the model refuses to guess


def test_implausible_value_is_a_data_quality_issue_not_physiology(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    res = hw.ingest(hw.frame(pid, did, key, 1, heartRate=254, spO2=20))
    assert res["alerts"] == ["IMPLAUSIBLE_VALUE"]                            # no HIGH_HR / LOW_SPO2 alert
    m = hw.svc.store.ns("hardware").one("SELECT * FROM measurements")
    assert m["heart_rate"] is None and m["spo2"] is None and m["quality"] == "implausible"


def test_unsynchronised_or_wrong_device_clock_uses_gateway_time(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    hw.ingest(hw.frame(pid, did, key, 1, flags=0, timestamp=1234))           # uptime, not synced
    hw.ingest(hw.frame(pid, did, key, 2, timestamp=int(hw.clock()) + 86400)) # "synced" but a day in the future
    rows = hw.svc.store.ns("hardware").q("SELECT ts, device_ts FROM measurements ORDER BY seq_no")
    assert rows[0]["ts"] == hw.clock() and rows[0]["device_ts"] == 1234 and rows[1]["ts"] == hw.clock()


def test_threshold_alerts_dedupe_lifecycle_and_patient_specific_limits(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    assert hw.ingest(hw.frame(pid, did, key, 1, heartRate=121))["alerts"] == ["HIGH_HR"]      # > 120 bpm (default limit)
    assert hw.ingest(hw.frame(pid, did, key, 2, heartRate=125))["alerts"] == []               # same open alert, no duplicate
    a = hw.doc.get(f"{API}/alerts").json["alerts"]
    assert len(a) == 1 and a[0]["trigger_count"] == 2 and a[0]["status"] == "new" and a[0]["category"] == "threshold"
    aid = a[0]["id"]
    act = lambda action, **kw: hw.doc.post(f"{API}/alerts/{aid}/action", json={"action": action, **kw}, headers=hw.doc.csrf)  # noqa: E731
    assert act("acknowledge").json["alert"]["status"] == "acknowledged"
    assert act("acknowledge").status_code == 409                              # invalid transition
    assert act("assign", assignee=hw.ids["asst"]).json["alert"]["assigned_to"] == hw.ids["asst"]
    assert act("resolve", note="Patient was exercising").json["alert"]["status"] == "resolved"
    assert act("escalate").status_code == 409
    detail = hw.doc.get(f"{API}/alerts/{aid}").json["alert"]
    assert [e["action"] for e in detail["events"]] == ["created", "acknowledge", "assign", "resolve"]
    assert detail["measurement"]["heart_rate"] == 121 and detail["acknowledged_at"] and detail["resolved_at"]
    assert hw.ingest(hw.frame(pid, did, key, 3, heartRate=124))["alerts"] == ["HIGH_HR"]      # new episode after resolution
    # patient-specific limit configured by the clinician
    assert hw.doc.put(f"{API}/patients/{pid}/thresholds", json={"spo2_low": 88}, headers=hw.doc.csrf).status_code == 200
    assert hw.ingest(hw.frame(pid, did, key, 4, spO2=90))["alerts"] == []                     # 90 < 92 default, but >= 88 for this patient
    assert hw.ingest(hw.frame(pid, did, key, 5, spO2=87))["alerts"] == ["LOW_SPO2"]
    assert hw.doc.put(f"{API}/patients/{pid}/thresholds", json={"spo2_low": 5}, headers=hw.doc.csrf).status_code == 400


def test_fall_is_a_critical_alert_and_can_be_marked_false_positive(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    assert hw.ingest(hw.frame(pid, did, key, 1, fallDetected=True, payloadType=3, alertLevel=3, critical=True))["alerts"] == ["FALL"]
    a = hw.doc.get(f"{API}/alerts").json["alerts"][0]
    assert a["severity"] == "critical" and a["category"] == "fall"
    r = hw.doc.post(f"{API}/alerts/{a['id']}/action", json={"action": "false_positive", "note": "device dropped"}, headers=hw.doc.csrf)
    assert r.json["alert"]["status"] == "false_positive"


def test_unacknowledged_critical_alert_escalates_automatically(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    hw.ingest(hw.frame(pid, did, key, 1, fallDetected=True))
    hw.clock.advance(hw.cfg.ESCALATE_AFTER_S - 5); hw.svc.monitor.tick()
    assert hw.doc.get(f"{API}/alerts").json["alerts"][0]["status"] == "new"
    hw.clock.advance(10); hw.svc.monitor.tick()
    a = [x for x in hw.doc.get(f"{API}/alerts").json["alerts"] if x["type"] == "FALL"][0]
    assert a["status"] == "escalated" and a["escalation_level"] == 1
    titles = [n["title"] for n in hw.doc.get(f"{API}/notifications").json["notifications"]]
    assert "Unacknowledged alert escalated" in titles and "New alert" in titles


def test_device_goes_offline_only_by_timeout_and_recovers(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    dev = lambda: next(d for d in hw.doc.get(f"{API}/devices").json["devices"] if d["id"] == did)  # noqa: E731
    assert dev()["online"] == 0 and dev()["status"] == "active"              # registered + paired but silent: NOT online
    hw.ingest(hw.frame(pid, did, key, 1))
    assert dev()["online"] == 1
    hw.clock.advance(hw.cfg.DEVICE_OFFLINE_AFTER_S - 10); hw.svc.monitor.tick()
    assert dev()["online"] == 1
    hw.clock.advance(20); hw.svc.monitor.tick()
    assert dev()["online"] == 0 and "DEVICE_OFFLINE" in hw.open_alerts("hardware", pid)
    assert hw.doc.get(f"{API}/patients/{pid}").json["patient"]["state"] == "critical"
    assert hw.doc.get(f"{API}/patients/{pid}").json["patient"]["latest"]["stale"] is True
    hw.ingest(hw.frame(pid, did, key, 2))
    assert dev()["online"] == 1 and "DEVICE_OFFLINE" not in hw.open_alerts("hardware", pid)   # auto-resolved


def test_notification_storm_protection(hw):
    hw.cfg.NOTIFY_MAX_PER_MIN = 3
    for i in range(6):
        pid, did, key = hw.hw_patient(hw.doc, name=f"Patient {i}")
        hw.ingest(hw.frame(pid, did, key, 1, fallDetected=True))
    rows = hw.svc.store.ns("hardware").q("SELECT status FROM notifications WHERE user_id=? AND channel='in_app'", (hw.ids["doc"],))
    assert [r["status"] for r in rows].count("sent") == 3 and [r["status"] for r in rows].count("suppressed") == 3


def test_device_replacement_keeps_patient_history(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    hw.ingest(hw.frame(pid, did, key, 1))
    r = hw.doc.post(f"{API}/devices", json={"serial": "NEW-NODE", "patient_id": pid}, headers=hw.doc.csrf)
    assert r.status_code == 409                                              # one active device per patient
    assert hw.doc.post(f"{API}/devices/{did}/replace", json={}, headers=hw.doc.csrf).status_code == 200
    r = hw.doc.post(f"{API}/devices", json={"serial": "NEW-NODE", "patient_id": pid}, headers=hw.doc.csrf)
    new_id, new_key = r.json["device"]["id"], bytes.fromhex(r.json["provisioning"]["device_key_hex"])
    assert hw.ingest(hw.frame(pid, did, key, 2))["outcome"] == "rejected"    # retired device can no longer inject data
    assert hw.ingest(hw.frame(pid, new_id, new_key, 1))["outcome"] == "stored"
    assert hw.doc.get(f"{API}/patients/{pid}/measurements?range=1h").json["count"] == 2
    assert len(hw.doc.get(f"{API}/patients/{pid}").json["patient"]["devices"]) == 2


def test_hardware_ingest_endpoint_requires_gateway_token_and_ignores_ui_mode(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    hw.svc.store.set_setting("operating_mode", "simulation")                 # UI in simulation mode ...
    anon, raw = hw.app.test_client(), hw.frame(pid, did, key, 1).hex()
    assert anon.post(f"{API}/ingest/frame", json={"frame_hex": raw}).status_code == 401
    assert anon.post(f"{API}/ingest/frame", json={"frame_hex": raw}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert hw.doc.post(f"{API}/ingest/frame", json={"frame_hex": raw}, headers=hw.doc.csrf).status_code == 401   # a doctor session is not a gateway
    H = {"Authorization": "Bearer gw-test-token"}
    r = anon.post(f"{API}/ingest/frame", json={"frame_hex": raw, "rssi": -101, "snr": 7.5}, headers=H)
    assert r.status_code == 200 and r.json["outcome"] == "stored"
    assert anon.post(f"{API}/ingest/frame", json={"frame_hex": "zz"}, headers=H).status_code == 400
    assert hw.svc.store.ns("hardware").scalar("SELECT COUNT(*) FROM measurements") == 1     # ... data still lands in hardware
    assert hw.svc.store.ns("simulation").scalar("SELECT COUNT(*) FROM measurements") == 0
    hw.cfg.GATEWAY_INGEST_TOKEN = ""
    assert anon.post(f"{API}/ingest/frame", json={"frame_hex": raw}, headers=H).status_code == 503


def test_legacy_v1_packets_only_when_enabled(hw):
    from gateway import telemetry as V1
    pid, did, key = hw.hw_patient(hw.doc)
    raw = V1.encode(V1.Telemetry(f"P{pid:03d}", 3, 79, 98, 36.7, V1.F_SYNTH, 120))
    assert hw.svc.pipeline.handle_v1(raw)["outcome"] == "rejected"
    hw.cfg.ALLOW_LEGACY_V1 = True
    assert hw.svc.pipeline.handle_v1(raw)["outcome"] == "stored"
    assert hw.svc.pipeline.handle_v1(raw)["outcome"] == "duplicate"
    assert hw.svc.store.ns("hardware").one("SELECT data_source FROM measurements")["data_source"] == "legacy_v1"


def test_virtual_devices_cannot_exist_in_hardware_namespace(hw):
    import pytest
    from gateway.services import DomainError
    with pytest.raises(DomainError):
        hw.svc.register_device("hardware", {"serial": "SIM-X"}, None, virtual=True)
    with pytest.raises(DomainError):
        hw.svc.register_device("simulation", {"serial": "REAL-X"}, None, virtual=False)


def test_sse_view_filters_by_role_and_scope(hw):
    from gateway.api_v1 import _make_view
    from gateway.security import permissions_of
    pid, did, key = hw.hw_patient(hw.doc)
    users = {k: hw.svc.auth.user(v) for k, v in hw.ids.items()}
    hw.doc.post(f"{API}/patients/{pid}/caregivers", json={"user_id": hw.ids["fam"], "consent_given_by": "The Patient"}, headers=hw.doc.csrf)
    views = {k: _make_view(hw.svc, u, permissions_of(u)) for k, u in users.items()}
    meas = {"type": "measurement", "ns": "hardware", "patient_id": pid, "data": {"patient_id": pid, "ts": 1, "heart_rate": 80, "spo2": 97,
            "temperature": 36.6, "fall_detected": 0, "rssi": -90, "seq_no": 4, "device_id": did}}
    pred = {"type": "prediction", "ns": "hardware", "patient_id": pid, "data": {"score": 0.9}}
    assert views["doc"](meas) == meas and views["doc"](pred) == pred
    assert views["doc2"](meas) is None and views["asst"](meas) is None          # not assigned to this patient
    cg = views["fam"](meas)
    assert set(cg["data"]) == {"patient_id", "ts", "heart_rate", "spo2", "temperature", "fall_detected"}   # reduced copy
    assert views["fam"](pred) is None and views["fam2"](meas) is None
    assert views["doc"]({**meas, "ns": "simulation"}) is None                    # other namespace never leaks into this mode
    note = {"type": "notification", "ns": "hardware", "user_id": hw.ids["asst"], "patient_id": pid, "data": {}}
    assert views["asst"](note) == note and views["doc"](note) is None


def test_reports_csv_and_pdf(hw):
    pid, did, key = hw.hw_patient(hw.doc, name="Report Patient")
    for s in range(1, 6):
        hw.ingest(hw.frame(pid, did, key, s, heartRate=70 + s)); hw.clock.advance(30)
    csv = hw.doc.get(f"{API}/reports/patient/{pid}.csv?range=1h")
    text = csv.get_data(as_text=True)
    assert csv.mimetype == "text/csv" and "attachment" in csv.headers["Content-Disposition"]
    assert "Data source: hardware" in text and "Period (UTC)" in text and "Generated (UTC)" in text and "not a medical device" in text
    assert text.count("\n") == 5 + 1 + 5                                       # 5 header lines + column row + 5 measurements
    pdf = hw.doc.get(f"{API}/reports/patient/{pid}.pdf?range=1h")
    assert pdf.mimetype == "application/pdf" and pdf.data.startswith(b"%PDF-1.4") and pdf.data.rstrip().endswith(b"%%EOF")
    assert b"Report Patient" in pdf.data and b"Hardware measurements" in pdf.data and b"Disclaimer" in pdf.data
    assert hw.doc.get(f"{API}/reports/alerts.csv?range=24h").status_code == 200
    assert b"measured by the gateway" in hw.doc.get(f"{API}/reports/network.csv").data
    assert hw.doc.get(f"{API}/reports/model.pdf").data.startswith(b"%PDF")
    assert hw.doc.get(f"{API}/reports/patient/{pid}.xml?range=1h").status_code == 404


def test_measurement_time_filters_and_aggregation(hw):
    pid, did, key = hw.hw_patient(hw.doc)
    for s in range(1, 1001):
        hw.ingest(hw.frame(pid, did, key, s)); hw.clock.advance(30)            # ~8.3 h of data
    hw.doc = hw.login("doc")                                                   # the 8 h of silence expired the session
    q = lambda qs: hw.doc.get(f"{API}/patients/{pid}/measurements?{qs}")       # noqa: E731
    assert q("range=15m").json["count"] == 30 and q("range=15m").json["aggregated"] is False
    d = q("range=24h").json
    assert d["count"] == 1000 and d["aggregated"] is True and len(d["points"]) <= 720 and sum(p["n"] for p in d["points"]) == 1000
    t = hw.clock()
    assert q(f"from={t - 600}&to={t}").json["count"] == 20
    for bad in ("range=5y", "from=abc", f"from={t}&to={t - 5}"):
        assert q(bad).status_code == 400
    assert json.loads(q("range=7d").data)["count"] == 1000


def test_retention_removes_only_old_rows(hw):
    from gateway.ingest import retention
    pid, did, key = hw.hw_patient(hw.doc)
    hw.ingest(hw.frame(pid, did, key, 1))
    hw.clock.advance(31 * 86400)
    hw.ingest(hw.frame(pid, did, key, 2))
    assert retention(hw.svc, "hardware", hw.clock()) >= 1
    assert [r["seq_no"] for r in hw.svc.store.ns("hardware").q("SELECT seq_no FROM measurements")] == [2]
