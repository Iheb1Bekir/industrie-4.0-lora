"""Regenerate every data file plotted in the report (report/figures/data/*.dat) from the repository's own artifacts.

Sources (all traceable, nothing typed by hand):
  * ml/models/ew-20261114/{metrics,curves,metadata}.json   - stored evaluation of the deployed model
  * ml/models/ew-20261114/model.joblib + gateway/inference  - risk trajectory of one SYNTHETIC test patient
  * ml/data/synth-v2/*                                      - SYNTHETIC dataset (regenerate: python ml/generate_dataset.py)
  * <omnet_vectors.txt>                                     - doctor.app vectors of the OMNeT++ run
        RPM_LoRa_Research/simulations/results/circular-deployment-validation-20261108-r6-default-coverage-aware
    (exported with report/tools/export_omnet_vectors.sh)
usage: python report/tools/make_figure_data.py <omnet_vectors.txt>
"""
import csv
import gzip
import json
import math
import os
import statistics
import sys
import time

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
from gateway import features as F  # noqa: E402
from gateway.inference import Predictor  # noqa: E402

OUT = os.path.join(REPO, "report", "figures", "data")
MODEL_DIR = os.path.join(REPO, "ml", "models")
VER = "ew-20261114"
os.makedirs(OUT, exist_ok=True)
NAN = float("nan")


def write(name, header, rows):
    with open(os.path.join(OUT, name), "w", encoding="ascii", newline="\n") as f:
        f.write(" ".join(header) + "\n")
        for r in rows:
            f.write(" ".join("nan" if (isinstance(v, float) and v != v) else (f"{v:.6g}" if isinstance(v, float) else str(v)) for v in r) + "\n")


def num(s):
    return NAN if s in ("", "nan", "NaN", None) else float(s)


def toa_ms(pl, sf=7, bw=125e3, cr=1, n_pre=8, crc=1, ih=0, de=0):
    """Semtech AN1200.13 time on air (explicit header, CRC on, LDRO off): v2 frame on real radios."""
    tsym = 2 ** sf / bw * 1000.0
    n = 8 + max(math.ceil((8 * pl - 4 * sf + 28 + 16 * crc - 20 * ih) / (4 * (sf - 2 * de))) * (cr + 4), 0)
    return (n_pre + 4.25 + n) * tsym


def flora_toa_ms(payload_bytes, sf=7, bw=125e3, code_redundance=4):
    """FLoRa 1.3.2 LoRaTransmitter: fixed payloadBytes (20 node / 15 gateway radio), integer division."""
    tsym = 2 ** sf / bw * 1000.0
    n = 8 + ((8 * payload_bytes - 4 * sf + 28 + 16) // (4 * sf)) * (code_redundance + 4)
    return (8 + 4.25) * tsym + (8 + n) * tsym


# ------------------------------------------------------------------ 1. stored model evaluation
mdir = os.path.join(MODEL_DIR, VER)
metrics = json.load(open(os.path.join(mdir, "metrics.json"), encoding="utf-8"))
curves = json.load(open(os.path.join(mdir, "curves.json"), encoding="utf-8"))
meta = json.load(open(os.path.join(mdir, "metadata.json"), encoding="utf-8"))
write("roc.dat", ["fpr", "tpr"], curves["roc"])
write("pr.dat", ["recall", "precision"], curves["pr"])
write("calib.dat", ["pred", "obs", "n"], [(b["mean_predicted"], b["observed_rate"], b["n"]) for b in curves["calibration"]])
t = metrics["models"][metrics["selected"]]["test"]
print("selected", metrics["selected"], "test", {k: t[k] for k in ("precision", "recall", "specificity", "f1", "roc_auc", "pr_auc", "fpr")})
print("prevalence", t["prevalence"])

# ------------------------------------------------------------------ 2. synthetic dataset statistics
ds = os.path.join(REPO, "ml", "data", "synth-v2")
patients = {int(r["patient_id"]): r for r in csv.DictReader(open(os.path.join(ds, "patients.csv"), encoding="utf-8"))}
series = {}
with gzip.open(os.path.join(ds, "measurements.csv.gz"), "rt", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        series.setdefault(int(r["patient_id"]), []).append((int(r["t"]), num(r["hr"]), num(r["spo2"]), num(r["temp"]), int(r["fall"] or 0)))
hr = np.array([x[1] for s in series.values() for x in s])
sp = np.array([x[2] for s in series.values() for x in s])
tp = np.array([x[3] for s in series.values() for x in s])
n = len(hr)
print("samples", n, "patients", len(series))
for name, a in (("hr", hr), ("spo2", sp), ("temp", tp)):
    print(f"missing {name}: {np.isnan(a).sum()} ({np.isnan(a).mean() * 100:.2f} %)")
beyond = {"hr": np.nansum(hr > F.THR_HR), "spo2": np.nansum(sp < F.THR_SPO2), "temp": np.nansum(tp >= F.THR_TEMP)}
print("beyond threshold:", {k: f"{int(v)} ({v / n * 100:.2f} %)" for k, v in beyond.items()}, "thresholds", F.THR_HR, F.THR_SPO2, F.THR_TEMP)
kinds = {}
for p in patients.values():
    for e in json.loads(p["episodes"]):
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
print("episodes", kinds, "intervals", {k: sum(1 for p in patients.values() if p["interval_s"] == k) for k in ("15", "30", "60")})


def hist(a, lo, hi, step, out_if):
    edges = np.arange(lo, hi + step / 2, step)
    cnt, _ = np.histogram(a[~np.isnan(a)], bins=edges)
    rows = []
    for e, c in zip(edges[:-1], cnt):
        mid = e + step / 2
        rows.append((float(e), int(c) if not out_if(mid) else 0, int(c) if out_if(mid) else 0))
    rows.append((float(edges[-1]), 0, 0))
    return rows


write("hist_hr.dat", ["x", "normal", "beyond"], hist(hr, 40, 200, 4, lambda v: v > F.THR_HR))
write("hist_spo2.dat", ["x", "normal", "beyond"], hist(sp, 70, 101, 1, lambda v: v < F.THR_SPO2))
write("hist_temp.dat", ["x", "normal", "beyond"], hist(tp, 35.0, 41.0, 0.1, lambda v: v >= F.THR_TEMP))

# ------------------------------------------------------------------ 3. risk trajectory of one synthetic TEST patient
# Selection rule (fixed before looking at any score): lowest-id test patient with exactly one episode, of kind
# "spo2_decline", starting after the first hour.
test_ids = sorted(meta["dataset"]["test_patient_ids"])
pick = None
for pid in test_ids:
    eps = json.loads(patients[pid]["episodes"])
    if len(eps) == 1 and eps[0]["kind"] == "spo2_decline" and eps[0]["start_s"] >= 3600:
        pick, start = pid, eps[0]["start_s"]
        break
print("example patient", pick, "interval", patients[pick]["interval_s"], "episode start", start)
pred = Predictor(MODEL_DIR)
thr = pred.bundle["thresholds"]
s = [{"ts": float(x[0]), "hr": None if x[1] != x[1] else x[1], "spo2": None if x[2] != x[2] else x[2],
      "temp": None if x[3] != x[3] else x[3], "fall": x[4]} for x in series[pick]]
breach_t = None
for a, b in zip(s, s[1:]):
    if all(v is not None for v in (a["hr"], a["spo2"], b["hr"], b["spo2"])) and \
            F.breach(a["hr"], a["spo2"], a["temp"] if a["temp"] is not None else 0) and \
            F.breach(b["hr"], b["spo2"], b["temp"] if b["temp"] is not None else 0):
        if b["ts"] >= start:
            breach_t = b["ts"]
            break
t0, t1 = start - 3600, (breach_t or start) + 1800
rows, lat, first_med, first_high = [], [], None, None
for i, x in enumerate(s):
    if not t0 <= x["ts"] <= t1:
        continue
    r = pred.predict(s[: i + 1], x["ts"])
    if r.get("latency_ms"):
        lat.append(r["latency_ms"])
    sc = r["score"] if r["score"] is not None else NAN
    if breach_t and x["ts"] < breach_t and sc == sc:
        if first_med is None and sc >= thr["medium"]:
            first_med = x["ts"]
        if first_high is None and sc >= thr["high"]:
            first_high = x["ts"]
    rows.append(((x["ts"] - start) / 60.0, x["hr"] if x["hr"] is not None else NAN,
                 x["spo2"] if x["spo2"] is not None else NAN, x["temp"] if x["temp"] is not None else NAN, sc))
write("example_patient.dat", ["tmin", "hr", "spo2", "temp", "score"], rows)
info = {"patient": pick, "interval_s": int(patients[pick]["interval_s"]), "episode_start_s": start, "breach_s": breach_t,
        "breach_min_rel": None if breach_t is None else (breach_t - start) / 60,
        "first_medium_min_rel": None if first_med is None else (first_med - start) / 60,
        "first_high_min_rel": None if first_high is None else (first_high - start) / 60,
        "thr_medium": thr["medium"], "thr_high": thr["high"]}
print("example", info)

# ------------------------------------------------------------------ 4. inference latency on THIS machine (not the Pi)
x = s[-40:]
for _ in range(20):
    pred.predict(x, x[-1]["ts"])
pred.latencies.clear() if hasattr(pred.latencies, "clear") else None
lat = []
for _ in range(300):
    t_ = time.perf_counter()
    pred.predict(x, x[-1]["ts"])
    lat.append((time.perf_counter() - t_) * 1000)
lat.sort()
print(f"latency ms (this PC, incl. 38 occlusion rows): median {statistics.median(lat):.2f} p95 {lat[int(0.95 * len(lat))]:.2f}")
print("model.joblib bytes", os.path.getsize(os.path.join(mdir, "model.joblib")))
json.dump(info, open(os.path.join(OUT, "example_patient.json"), "w"), indent=1)

# ------------------------------------------------------------------ 5. OMNeT++ doctor vectors (end-to-end delay, hops)
if len(sys.argv) > 1:
    vec, cur = {}, None
    for line in open(sys.argv[1], encoding="utf-8"):
        line = line.strip()
        if line.startswith("#"):
            cur = line[1:]
            vec[cur] = []
        elif line and cur:
            a, b = line.split()
            vec[cur].append((float(a), float(b)))
    d, h, pid = vec["endToEndDelay"], vec["hopCount"], vec["patientId"]
    assert len(d) == len(h) == len(pid)
    rows = [(round(t_, 6), round(v * 1000, 3), int(hc), int(p)) for (t_, v), (_, hc), (_, p) in zip(d, h, pid)]
    write("sim_delay.dat", ["t", "delay_ms", "hop", "patient"], rows)
    summ = []
    for hop in sorted({r[2] for r in rows}):
        ds_ = [r[1] for r in rows if r[2] == hop]
        print(f"OMNeT hop {hop}: n={len(ds_)} delay ms min {min(ds_):.2f} mean {statistics.mean(ds_):.2f} max {max(ds_):.2f}")
        summ.append((hop, len(ds_), round(statistics.mean(ds_), 2), round((hop + 1) * toa_ms(34), 2)))
    write("sim_delay_summary.dat", ["hop", "n", "sim_ms", "analytic34_ms"], summ)
    print("OMNeT packets", len(rows), "patients", sorted({r[3] for r in rows})[:3], "...")


print(f"ToA v2 34 B SF7/125k/CR4/5: {toa_ms(34):.3f} ms; duty cycle @30 s {toa_ms(34) / 300:.3f} %")
print(f"FLoRa model ToA: node(20 B) {flora_toa_ms(20):.3f} ms, gateway-type radio(15 B) {flora_toa_ms(15):.3f} ms")
G = 20 * toa_ms(34) / 1000 / 30
print(f"pure-ALOHA estimate N=20, T=30 s: G={G:.4f}, P(success)=exp(-2G)={math.exp(-2 * G):.4f}")

# ------------------------------------------------------------------ 6. binary v2 frame vs. a JSON rendering of the same fields
# Field values = the protocol test vector of docs/PROTOCOL_SPECIFICATION.md (15 fields of the measurement structure).
example = {"patientId": 7, "seqNo": 4242, "timestamp": 1800000000, "heartRate": 88, "spO2": 96, "temperature": 37.25,
           "fallDetected": True, "alertLevel": 3, "routingMode": 1, "sourceId": 107, "destinationId": 1, "hopCount": 0,
           "maxHopCount": 4, "payloadType": 3, "critical": True}
L = len(json.dumps(example, separators=(",", ":")))
print(f"compact JSON of the same 15 fields: {L} B (no tag, no CRC) -> ToA {toa_ms(L):.1f} ms vs v2 34 B {toa_ms(34):.1f} ms")
