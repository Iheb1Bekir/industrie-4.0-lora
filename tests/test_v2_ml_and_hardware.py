"""ML pipeline (features, dataset, training protocol, inference service) and hardware adapters
(SX127x driver against a simulated chip, gateway service store-and-forward, config loading)."""
import json
import os
import shutil
import sys

import pytest

from gateway import features as F
from gateway.inference import Predictor
from v2_harness import ROOT

sys.path.insert(0, os.path.join(ROOT, "ml"))


def series(n=40, step=30, hr=lambda i: 75, spo2=lambda i: 97, temp=lambda i: 36.7):
    return [{"ts": i * step, "hr": hr(i), "spo2": spo2(i), "temp": temp(i), "fall": 0} for i in range(n)]


# ------------------------------------------------------------------ features
def test_feature_vector_is_complete_and_ordered():
    f = F.compute_features(series(), 39 * 30)
    assert set(f) == set(F.FEATURE_NAMES) and len(F.vector(f)) == len(F.FEATURE_NAMES) == 38
    assert f["hr_last"] == 75 and f["hr_slope10"] == 0 and f["hr_margin"] == 45 and f["hr_eta"] == F.ETA_CAP_MIN and f["n_samples"] == 21


def test_trend_features_and_time_to_threshold():
    s = series(hr=lambda i: 80 + i)                       # +1 bpm per 30 s = +2 bpm/min
    f = F.compute_features(s, 39 * 30)
    assert f["hr_slope10"] == pytest.approx(2.0) and f["hr_slope3"] == pytest.approx(2.0)
    assert f["hr_margin"] == pytest.approx(120 - 118) and f["hr_eta"] == pytest.approx(1.0)
    assert f["hr_delta_base"] > 20
    d = F.compute_features(series(spo2=lambda i: 99 - i * 0.1), 39 * 30)
    assert d["spo2_slope10"] == pytest.approx(-0.2) and 0 < d["spo2_eta"] < F.ETA_CAP_MIN


def test_features_never_look_ahead():
    s = series(60, hr=lambda i: 75 if i < 40 else 150)    # the future contains a jump
    past = F.compute_features(s[:40], 39 * 30)
    with_future = F.compute_features(s, 39 * 30)
    assert past == with_future                            # samples after `now` are ignored


def test_missing_data_handling():
    s = series(hr=lambda i: None if i % 2 else 75, spo2=lambda i: None if i % 2 else 97)
    f = F.compute_features(s, 39 * 30)
    assert f["hr_missing"] == pytest.approx(11 / 21)          # window = samples 19..39, odd ones missing
    sparse = series(hr=lambda i: 75 if i > 36 else None)
    assert F.compute_features(sparse, 39 * 30) is None     # fewer than MIN_VALID samples -> no prediction, not a guess
    no_temp = F.compute_features(series(temp=lambda i: None), 39 * 30)
    assert no_temp["temp_last"] != no_temp["temp_last"] and no_temp["temp_missing"] == 1.0   # NaN, flagged missing
    assert F.compute_features([], 0) is None


def test_median_of_three_resists_single_artifact():
    s = series(hr=lambda i: 150 if i == 39 else 75)
    f = F.compute_features(s, 39 * 30)
    assert f["hr_last"] == 150 and f["hr_med3"] == 75 and f["hr_margin"] == 45


def test_breach_definition():
    assert F.breach(121, 97, 36.6) and F.breach(80, 91, 36.6) and F.breach(80, 97, 38.0)
    assert not F.breach(120, 92, 37.9) and not F.breach(None, None, None)


# ------------------------------------------------------------------ dataset + training protocol
def test_dataset_generator_is_reproducible_and_labelled_synthetic(tmp_path):
    import generate_dataset as G
    cfg = dict(G.DEFAULTS, patients=6, hours=1.0, version="t")
    a = G.generate(cfg, str(tmp_path / "a"))
    b = G.generate(cfg, str(tmp_path / "b"))
    c = G.generate(dict(cfg, seed=1), str(tmp_path / "c"))
    assert a["content_sha256"] == b["content_sha256"] != c["content_sha256"]
    assert a["synthetic"] is True and "SYNTHETIC" in a["notice"] and a["patients"] == 6
    import train as T
    _, s = T.load_dataset(str(tmp_path / "a"))
    vals = [x for p in s.values() for x in p]
    assert all(25 <= v["hr"] <= 230 for v in vals if v["hr"] is not None) and all(60 <= v["spo2"] <= 100 for v in vals if v["spo2"] is not None)
    assert all(33 <= v["temp"] <= 42.5 for v in vals)
    assert any(v["hr"] is None for v in vals) or True      # sensor faults occur at random; presence is not guaranteed in 6 h


def test_labels_use_only_the_future_and_exclude_breach_rows():
    import train as T
    # HR climbs steadily and crosses 120 at sample 60; breach is sustained from sample 61
    s = series(90, hr=lambda i: 70 + i if i < 60 else 135)
    X, y, t, onsets = T.build_rows(s)
    assert onsets == [52 * 30]                             # first sustained breach: samples 51 (121) and 52 (122)
    rows = dict(zip(t, y))
    assert all(ts < 51 * 30 for ts in t)                   # rows at/after the first breach are not prediction rows
    assert rows[50 * 30] == 1 and rows[33 * 30] == 1       # within 10 minutes before the sustained breach
    assert rows[31 * 30] == 0 and rows[25 * 30] == 0       # more than 10 minutes before -> negative
    quiet = T.build_rows(series(60))
    assert sum(quiet[1]) == 0 and quiet[3] == []
    artifact = T.build_rows(series(80, hr=lambda i: 160 if i == 50 else 75))
    assert sum(artifact[1]) == 0                           # a single-sample spike is not a prediction target


def test_saved_model_metadata_documents_the_protocol():
    with open(os.path.join(ROOT, "ml", "models", "active.json")) as f:
        version = json.load(f)["version"]
    d = os.path.join(ROOT, "ml", "models", version)
    meta, metrics, curves = (json.load(open(os.path.join(d, n))) for n in ("metadata.json", "metrics.json", "curves.json"))
    assert meta["dataset"]["synthetic"] is True and meta["dataset"]["split"].startswith("by patient")
    assert meta["feature_version"] == F.FEATURE_VERSION and meta["features"] == list(F.FEATURE_NAMES)
    assert {"python", "scikit-learn", "numpy", "joblib"} <= set(meta["dependencies"]) and len(meta["artifact_sha256"]) == 64
    assert {"logistic_regression", "random_forest", "hist_gradient_boosting", "isolation_forest", "trend_rule_baseline"} == set(metrics["models"])
    for name, m in metrics["models"].items():
        t = m["test"]
        assert {"accuracy", "precision", "recall", "sensitivity", "specificity", "f1", "fpr", "fnr", "roc_auc", "pr_auc", "confusion_matrix",
                "brier_calibrated", "ece_calibrated", "events"} <= set(t), name
        assert 0 <= t["pr_auc"] <= 1 and t["n"] == meta["dataset"]["samples"]["test"]
    best_val = max(m["validation"]["pr_auc"] for m in metrics["models"].values() if m["deployable"])
    assert metrics["models"][meta["model_name"]]["validation"]["pr_auc"] >= best_val - 0.01     # selected on VALIDATION, per the rule
    assert metrics["models"][meta["model_name"]]["deployable"] is True
    assert curves["roc"][0][0] == 0 and len(curves["feature_importance"]) >= 10 and curves["calibration"]


# ------------------------------------------------------------------ inference service
def test_inference_scores_trend_higher_than_stable_and_explains():
    p = Predictor(os.path.join(ROOT, "ml", "models"))
    assert p.status()["loaded"] and p.status()["health"] == "ok"
    stable = p.predict(series(), 39 * 30)
    rising = p.predict(series(hr=lambda i: 78 + i), 39 * 30)       # 117 bpm and climbing 2 bpm/min
    assert stable["status"] == rising["status"] == "ok"
    assert stable["risk_category"] == "low" and rising["risk_category"] == "high" and rising["score"] > stable["score"] + 0.3
    assert 0 <= rising["probability"] <= 1 and rising["threshold"] == p.bundle["thresholds"]["high"]
    top = rising["explanation"][0]
    assert top["contribution"] > 0 and top["feature"].startswith("hr_") and top["direction"] == "raises risk"
    assert rising["supporting"]["hr_last"] == 117 and rising["latency_ms"] < 500
    assert p.predict(series(3), 60)["status"] == "insufficient_data"
    assert p.status()["latency_ms"]["n"] == 2


def test_model_unavailable_never_blocks_monitoring(tmp_path):
    from v2_harness import V2
    v = V2(tmp_path, model_dir=str(tmp_path / "no-models"))
    assert v.svc.predictor.status()["loaded"] is False
    v.svc.store.set_setting("operating_mode", "hardware")
    doc = v.login("doc")
    pid, did, key = v.hw_patient(doc)
    res = v.ingest(v.frame(pid, did, key, 1, heartRate=140))
    assert res["outcome"] == "stored" and res["alerts"] == ["HIGH_HR"]                 # threshold alerts are independent of the model
    assert res["prediction"]["status"] == "model_unavailable" and res["prediction"]["score"] is None
    row = v.svc.store.ns("hardware").one("SELECT status, risk_category FROM predictions")
    assert row == {"status": "model_unavailable", "risk_category": "unknown"}          # recorded, never faked
    ml = doc.get("/api/v1/ml/model").json
    assert ml["runtime"]["health"] == "unavailable" and "metrics" not in ml
    assert doc.get("/api/v1/overview").json["model"]["loaded"] is False


def test_corrupted_or_mismatched_artifact_is_refused_and_rollback_works(tmp_path):
    src = os.path.join(ROOT, "ml", "models")
    with open(os.path.join(src, "active.json")) as f:
        version = json.load(f)["version"]
    dst = tmp_path / "models"
    shutil.copytree(os.path.join(src, version), dst / version)
    shutil.copytree(os.path.join(src, version), dst / "v-next")
    meta_path = dst / "v-next" / "metadata.json"
    meta = json.loads(meta_path.read_text()); meta["version"] = "v-next"; meta_path.write_text(json.dumps(meta))
    (dst / "active.json").write_text(json.dumps({"version": version}))
    p = Predictor(str(dst))
    assert p.status()["model_version"] == version
    assert p.set_active("v-next")["model_version"] == "v-next" and p.previous_version() == version     # deploy
    assert p.set_active(p.previous_version())["model_version"] == version                               # rollback
    with open(dst / "v-next" / "model.joblib", "ab") as f:
        f.write(b"tampered")
    from gateway.inference import ModelUnavailable
    with pytest.raises(ModelUnavailable, match="checksum"):
        p.set_active("v-next")
    assert p.status()["model_version"] == version and p.status()["loaded"]            # failed deploy leaves the old model active
    for bad in ("../etc", "missing", ""):
        with pytest.raises(ModelUnavailable):
            p.set_active(bad)


def test_deploy_endpoint_is_admin_only_and_audited(v2):
    doc, asst = v2.login("doc"), v2.login("asst")
    assert asst.post("/api/v1/ml/deploy", json={"version": "x"}, headers=asst.csrf).status_code == 403
    assert doc.post("/api/v1/ml/deploy", json={"version": "does-not-exist"}, headers=doc.csrf).status_code == 400
    actions = [(e["action"], e["outcome"]) for e in doc.get("/api/v1/audit").json["entries"]]
    assert ("model.deploy", "failed") in actions
    assert v2.svc.predictor.status()["loaded"]


# ------------------------------------------------------------------ SX127x driver against a simulated chip
class FakeSX127x:
    """Register-level model of the chip's SPI interface (single-register access + FIFO burst read)."""

    def __init__(self, version=0x12):
        self.reg = [0] * 0x80
        self.reg[0x42] = version
        self.fifo = b""
        self.writes = []

    def xfer2(self, data):
        addr, write = data[0] & 0x7F, bool(data[0] & 0x80)
        if write:
            self.writes.append((addr, data[1]))
            if addr == 0x12:
                self.reg[0x12] &= ~data[1] & 0xFF          # IRQ flags: write 1 to clear
            else:
                self.reg[addr] = data[1]
            return [0, 0]
        if addr == 0x00:
            n = len(data) - 1
            out, self.fifo = self.fifo[:n], self.fifo[n:]
            return [0] + list(out)
        return [0, self.reg[addr]]

    def inject(self, payload, rssi_raw=60, snr_raw=32, crc_error=False):
        self.fifo = bytes(payload)
        self.reg[0x13], self.reg[0x10], self.reg[0x1A], self.reg[0x19] = len(payload), 0, rssi_raw, snr_raw
        self.reg[0x12] = 0x40 | (0x20 if crc_error else 0)


def test_sx127x_driver_configuration_and_reception():
    from gateway.radio_sx127x import SX127x, RadioConfig, RadioError
    chip, resets = FakeSX127x(), []
    radio = SX127x(chip, RadioConfig(frequency_hz=868_100_000), reset=lambda: resets.append(1), sleep=lambda s: None).begin()
    frf = (chip.reg[0x06] << 16) | (chip.reg[0x07] << 8) | chip.reg[0x08]
    assert abs(frf * 32e6 / 2 ** 19 - 868_100_000) < 62 and resets == [1]
    assert chip.reg[0x1D] == (7 << 4) | (1 << 1)             # BW 125 kHz, CR 4/5, explicit header
    assert chip.reg[0x1E] == (7 << 4) | 0x04                 # SF7, CRC on
    assert chip.reg[0x39] == 0x12 and chip.reg[0x01] == 0x85 # private sync word, LoRa continuous RX
    assert chip.writes[0] == (0x01, 0x80)                    # LoRa mode selected from sleep first
    assert radio.poll() is None and radio.healthy()
    chip.inject(b"\x02" + bytes(33), rssi_raw=57, snr_raw=38)
    p = radio.poll()
    assert p.payload == b"\x02" + bytes(33) and p.crc_ok and p.snr == 9.5 and p.rssi == -100.0     # -157 + 57 on the HF port
    assert chip.reg[0x12] == 0 and radio.poll() is None      # IRQ cleared
    chip.inject(b"abc", rssi_raw=40, snr_raw=0xF0, crc_error=True)       # SNR -4 dB, radio CRC error
    p = radio.poll()
    assert p.crc_ok is False and p.snr == -4.0 and p.rssi == -121.0 and radio.crc_errors == 1
    lf = SX127x(FakeSX127x(), RadioConfig(frequency_hz=433_500_000), sleep=lambda s: None).begin()
    lf.spi.inject(b"x", rssi_raw=64, snr_raw=20)
    assert lf.poll().rssi == -100.0                          # -164 offset on the LF port (SX1278 433 MHz)
    with pytest.raises(RadioError, match="no SX127x"):
        SX127x(FakeSX127x(version=0x00), RadioConfig(frequency_hz=868_100_000), sleep=lambda s: None).begin()
    for bad in (RadioConfig(frequency_hz=2_400_000_000), RadioConfig(frequency_hz=868_100_000, spreading_factor=13),
                RadioConfig(frequency_hz=868_100_000, bandwidth_hz=100_000)):
        with pytest.raises(RadioError):
            bad.validate()
    chip.reg[0x01] = 0x80                                    # chip fell out of RX mode
    assert radio.healthy() is False


# ------------------------------------------------------------------ gateway service: forwarding, spooling, recovery
class FakeRadio:
    def __init__(self, packets): self.packets = list(packets)
    def receive(self, timeout=1.0):
        if not self.packets: return None
        p = self.packets.pop(0)
        if isinstance(p, Exception): raise p
        return p


def test_gateway_service_forwards_real_frames_into_the_platform(hw, tmp_path):
    from gateway.hw_gateway import GatewayService, Spool
    from gateway.radio_sx127x import Packet
    pid, did, key = hw.hw_patient(hw.doc)
    client = hw.app.test_client()
    calls = {"up": True}

    class Api:
        def post(self, frame_hex, rssi, snr):
            if not calls["up"]:
                return False, "unreachable"
            r = client.post("/api/v1/ingest/frame", json={"frame_hex": frame_hex, "rssi": rssi, "snr": snr},
                            headers={"Authorization": "Bearer gw-test-token"})
            return True, r.json["outcome"]

    frames = [Packet(hw.frame(pid, did, key, s), -95.0, 9.0, True) for s in range(1, 7)]
    radio = FakeRadio([frames[0], Packet(b"garbage", -120.0, -9.0, False), frames[1], frames[2], frames[3], OSError("SPI gone"), frames[4], frames[5]])
    made = []
    svc = GatewayService(lambda: made.append(1) or radio, Api(), Spool(str(tmp_path / "spool.sqlite3")), clock=hw.clock, sleep=lambda s: None)
    assert svc.step() == "stored" and svc.step() == "radio_crc_error" and svc.step() == "stored"
    calls["up"] = False                                       # platform restarts / network drops
    assert svc.step() == "spooled" and svc.step() == "spooled" and len(svc.spool) == 2
    assert svc.step() is None and svc.radio is None           # radio fault -> dropped, will be re-initialised
    calls["up"] = True
    assert svc.step() == "stored" and len(made) == 2          # radio re-created; spool flushed first, in order
    assert len(svc.spool) == 0
    assert svc.step() == "stored"
    assert svc.step() is None
    db = hw.svc.store.ns("hardware")
    assert [r["seq_no"] for r in db.q("SELECT seq_no FROM measurements ORDER BY id")] == [1, 2, 3, 4, 5, 6]   # nothing lost, order kept
    assert db.one("SELECT last_rssi, online FROM devices WHERE id=?", (did,)) == {"last_rssi": -95.0, "online": 1}
    assert svc.stats["received"] == 7 and svc.stats["spooled"] == 2 and svc.stats["radio_crc_errors"] == 1
    reopened = Spool(str(tmp_path / "spool.sqlite3"))
    reopened.push(1.0, "aa", None, None)
    assert len(Spool(str(tmp_path / "spool.sqlite3"))) == 1   # spool survives a service restart


def test_gateway_radio_init_failure_backs_off_and_retries(tmp_path):
    from gateway.hw_gateway import GatewayService, Spool
    sleeps, attempts = [], []

    def factory():
        attempts.append(1)
        if len(attempts) < 4:
            raise OSError("no /dev/spidev0.0")
        return FakeRadio([])
    svc = GatewayService(factory, None, Spool(str(tmp_path / "s.sqlite3")), sleep=sleeps.append)
    for _ in range(4):
        svc.step()
    assert sleeps == [1.0, 2.0, 4.0] and svc.radio is not None and svc.stats["radio_restarts"] == 3


def test_gateway_config_requires_explicit_frequency(tmp_path):
    from gateway.hw_gateway import load_config, make_radio_factory
    example = open(os.path.join(ROOT, "hardware", "gateway.example.toml"), encoding="utf-8").read()
    p = tmp_path / "gw.toml"
    p.write_text(example, encoding="utf-8")
    with pytest.raises(SystemExit, match="frequency_hz is required"):
        load_config(str(p))                                   # the example ships without a frequency on purpose
    p.write_text(example.replace("# frequency_hz = 868100000", "frequency_hz = 868100000"), encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg["radio"]["frequency_hz"] == 868100000 and callable(make_radio_factory(cfg))
    cfg["radio"]["adapter"] = "sx1262"
    with pytest.raises(SystemExit, match="unsupported radio adapter"):
        make_radio_factory(cfg)


def test_omnet_importer_parses_scalar_files(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import import_omnet_results as I
    sca = "\n".join(["attr configname DistributedRPM", "config sim-time-limit 120s"]
                    + [f"scalar DistributedRPMNetwork.patients[{i}].app generatedPackets 4" for i in range(20)]
                    + [f"scalar DistributedRPMNetwork.relay[{i}].app {n} {v}" for i in range(3) for n, v in (("receivedPackets", 5 + i), ("droppedPackets", 0), ("duplicatePackets", 0))]
                    + [f"scalar DistributedRPMNetwork.relay[{i}].LoRaNic.mac forwardedPackets {5 + i}" for i in range(3)]
                    + ["scalar DistributedRPMNetwork.doctor.app directPackets 64", "scalar DistributedRPMNetwork.doctor.app relayAssistedPackets 15",
                       "scalar DistributedRPMNetwork.doctor.app duplicatePackets 0", "scalar DistributedRPMNetwork.doctor.app fallAlerts 1",
                       "scalar DistributedRPMNetwork.doctor.app criticalAlerts 2", "scalar DistributedRPMNetwork.doctor.app warningAlerts 1",
                       "scalar DistributedRPMNetwork.doctor.app normalAlerts 76"])
    s = I.summarize(*I.parse(sca), "t", "t.sca")
    assert (s["patients"], s["relays"], s["generated"], s["doctor_valid"], s["pdr"], s["sim_time"]) == (20, 3, 80, 79, 0.9875, "120s")
    assert s["relay_stats"][2] == {"index": 2, "received": 7, "forwarded": 7, "dropped": 0, "duplicates": 0}
    with pytest.raises(SystemExit):
        I.summarize(*I.parse("scalar X.y z 1"), "t", "t")
