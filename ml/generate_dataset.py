#!/usr/bin/env python3
"""Reproducible SYNTHETIC patient time-series generator (dataset for the early-warning model).

Everything produced here is synthetic. It is NOT patient data and must never be described as such.
Assumptions and the references behind the chosen ranges are documented in docs/ML_PIPELINE.md.

Usage:  python ml/generate_dataset.py                      # default config -> ml/data/synth-v2/
        python ml/generate_dataset.py --patients 300 --hours 8 --seed 7 --version synth-v3
Output: measurements.csv.gz (one row per DELIVERED sample), patients.csv, manifest.json (config + sha256).
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import sys
import time

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULTS = {
    "version": "synth-v2", "seed": 20261114, "patients": 600, "hours": 8.0, "intervals_s": [15, 30, 60],
    # resting ranges for the simulated adult profiles (see docs/ML_PIPELINE.md, "Assumptions")
    "base_hr": [58, 92], "base_spo2": [94.5, 98.8], "base_temp": [36.2, 37.1],
    "episode_count_p": [0.25, 0.35, 0.25, 0.15],
    "episode_weights": {"hr_rise": 0.20, "spo2_decline": 0.20, "fever": 0.12, "combined": 0.13, "abrupt": 0.05,
                        "benign_hr": 0.15, "benign_spo2": 0.10, "fall": 0.05},
    "p_missing": 0.02, "outage_per_hour": 0.25, "outage_s": [60, 600], "sensor_fault_per_patient": 0.3,
    "sensor_fault_s": [60, 300], "p_artifact": 0.003,
}


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def envelope(t, start, ramp, hold, recover):
    """0 -> 1 over `ramp`, stay for `hold`, back to 0 over `recover`."""
    up = smoothstep((t - start) / ramp)
    down = 1.0 - smoothstep((t - start - ramp - hold) / recover)
    return np.where(t < start, 0.0, up * down)


def ar1(rng, n, sd, rho):
    e = rng.normal(0, sd, n)
    out = np.empty(n)
    acc = 0.0
    for i in range(n):
        acc = rho * acc + e[i]
        out[i] = acc
    return out


def make_patient(pid, cfg, rng):
    u = rng.uniform
    interval = int(rng.choice(cfg["intervals_s"]))
    dur = cfg["hours"] * 3600
    t = np.arange(0, dur, interval, dtype=float)
    n = len(t)
    prof = {"patient_id": pid, "interval_s": interval, "base_hr": u(*cfg["base_hr"]), "base_spo2": u(*cfg["base_spo2"]),
            "base_temp": u(*cfg["base_temp"]), "hr_noise": u(1.0, 2.5), "spo2_noise": u(0.25, 0.5), "temp_noise": u(0.04, 0.07)}
    hr = prof["base_hr"] + ar1(rng, n, prof["hr_noise"], 0.6) + u(1.5, 4.0) * np.sin(2 * math.pi * t / u(1200, 3600) + u(0, 6.28))
    spo2 = prof["base_spo2"] + ar1(rng, n, prof["spo2_noise"], 0.5)
    temp = prof["base_temp"] + ar1(rng, n, prof["temp_noise"], 0.8) + 0.15 * np.sin(2 * math.pi * t / 86400 + u(0, 6.28))
    fall = np.zeros(n, dtype=int)
    episodes = []
    kinds, weights = list(cfg["episode_weights"]), np.array(list(cfg["episode_weights"].values()))
    for _ in range(int(rng.choice(len(cfg["episode_count_p"]), p=cfg["episode_count_p"]))):
        kind = str(rng.choice(kinds, p=weights / weights.sum()))
        start = u(1800, max(1900, dur - 3600))
        if kind == "hr_rise":
            env = envelope(t, start, u(480, 2400), u(300, 900), 600); hr += u(35, 75) * env
        elif kind == "spo2_decline":
            env = envelope(t, start, u(480, 2400), u(300, 900), 600); spo2 -= u(5, 12) * env; hr += u(5, 18) * env
        elif kind == "fever":
            env = envelope(t, start, u(1800, 5400), u(900, 1800), 1800); temp += u(1.2, 2.6) * env; hr += u(8, 22) * env
        elif kind == "combined":
            env = envelope(t, start, u(600, 2400), u(300, 900), 900)
            hr += u(30, 60) * env; spo2 -= u(4, 10) * env; temp += u(0.5, 1.8) * env
        elif kind == "abrupt":      # sudden change: by construction (almost) unpredictable from the trend
            env = envelope(t, start, u(30, 120), u(120, 600), 300)
            if rng.random() < 0.5: spo2 -= u(6, 12) * env
            else: hr += u(50, 70) * env
        elif kind == "benign_hr":   # activity-like transient, usually below the alert threshold (hard negative)
            env = envelope(t, start, u(120, 600), u(120, 600), u(300, 600)); hr += u(15, 35) * env
        elif kind == "benign_spo2":
            env = envelope(t, start, 300, 300, 300); spo2 -= u(1, 3) * env
        elif kind == "fall":
            i = int(np.searchsorted(t, start)); fall[min(i, n - 1)] = 1
            hr += u(15, 30) * envelope(t, start, 10, 60, 240)
        episodes.append({"kind": kind, "start_s": round(float(start))})
    # measurement layer: motion artifacts, quantization (the device sends integer bpm / %, 0.01 degC)
    art = rng.random(n) < cfg["p_artifact"]
    hr = hr + art * rng.choice([-1, 1], n) * rng.uniform(15, 40, n)
    hr_m = np.clip(np.rint(hr), 25, 230); spo2_m = np.clip(np.rint(spo2), 60, 100); temp_m = np.round(np.clip(temp, 33, 42.5), 2)
    delivered = rng.random(n) >= cfg["p_missing"]
    for _ in range(rng.poisson(cfg["outage_per_hour"] * cfg["hours"])):      # communication interruptions
        s = u(0, dur); delivered &= ~((t >= s) & (t < s + u(*cfg["outage_s"])))
    sensor_ok = np.ones(n, dtype=bool)
    for _ in range(rng.poisson(cfg["sensor_fault_per_patient"])):            # HR/SpO2 sensor disconnections
        s = u(0, dur); sensor_ok &= ~((t >= s) & (t < s + u(*cfg["sensor_fault_s"])))
    rows = []
    for i in np.nonzero(delivered)[0]:
        ok = sensor_ok[i]
        rows.append((pid, int(t[i]), int(hr_m[i]) if ok else "", int(spo2_m[i]) if ok else "", f"{temp_m[i]:.2f}", int(fall[i])))
    prof["episodes"] = json.dumps(episodes)
    prof["samples"] = len(rows)
    return prof, rows


def generate(cfg, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(cfg["seed"])
    mpath = os.path.join(out_dir, "measurements.csv.gz")
    profiles, total = [], 0
    with gzip.open(mpath, "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["patient_id", "t", "hr", "spo2", "temp", "fall"])
        for pid in range(1, cfg["patients"] + 1):
            prof, rows = make_patient(pid, cfg, np.random.default_rng([cfg["seed"], pid]))
            w.writerows(rows)
            profiles.append(prof); total += len(rows)
    with open(os.path.join(out_dir, "patients.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(profiles[0])); w.writeheader(); w.writerows(profiles)
    h = hashlib.sha256()
    with gzip.open(mpath, "rb") as f:            # hash of the uncompressed content (gzip headers contain a timestamp)
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    manifest = {"version": cfg["version"], "synthetic": True, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "config": cfg, "patients": cfg["patients"], "samples": total, "content_sha256": h.hexdigest(),
                "generator": "ml/generate_dataset.py", "numpy": np.__version__,
                "notice": "SYNTHETIC DATA - generated by a parametric simulator, not measured on any person."}
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default=DEFAULTS["version"]); ap.add_argument("--seed", type=int, default=DEFAULTS["seed"])
    ap.add_argument("--patients", type=int, default=DEFAULTS["patients"]); ap.add_argument("--hours", type=float, default=DEFAULTS["hours"])
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    cfg = dict(DEFAULTS, version=a.version, seed=a.seed, patients=a.patients, hours=a.hours)
    out = a.out or os.path.join(ROOT, "ml", "data", a.version)
    m = generate(cfg, out)
    print(f"dataset {m['version']}: {m['patients']} synthetic patients, {m['samples']} samples -> {out}")
    print("content sha256:", m["content_sha256"])


if __name__ == "__main__":
    sys.exit(main())
