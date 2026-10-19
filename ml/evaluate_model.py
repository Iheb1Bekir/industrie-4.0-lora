#!/usr/bin/env python3
"""Evaluate the linear-regression fallback (the model actually available) with a chronological 80/20 split and
report MAPE for HR and SpO2 at the +15 min step against the report's targets (HR <= 8 %, SpO2 <= 5 %).
Refuses synthetic rows unless --allow-synthetic; a result on synthetic data is only a code check, NOT performance.
Usage: python ml/evaluate_model.py readings.csv
"""
import argparse, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from gateway.config import Config
from gateway.prediction import PredictionService
from train_model import load


def mape(y, yh): return 100.0 * sum(abs(a - b) / abs(a) for a, b in zip(y, yh)) / len(y) if y else float("nan")


def evaluate(series, cfg):
    svc, err = PredictionService(Config(MODEL_PATH="/nonexistent")), {"hr": ([], []), "spo2": ([], [])}
    for s in series.values():
        for i in range(max(cfg.WINDOW, int(len(s) * 0.8)), len(s)):
            win = [{"ts": t, "hr": v[0], "spo2": v[1], "temp": v[2]} for t, v in s[i - cfg.WINDOW:i]]
            tgt_ts = win[-1]["ts"] + 15 * 60
            j = min(range(i, len(s)), key=lambda k: abs(s[k][0] - tgt_ts)); 
            if abs(s[j][0] - tgt_ts) > 90: continue
            p = svc.predict("x", win, 15, 0)
            if not p["pred"]: continue
            for k, idx in (("hr", 0), ("spo2", 1)):
                if k in p["pred"]: err[k][0].append(s[j][1][idx]); err[k][1].append(p["pred"][k][-1])
    return {k: (mape(*v), len(v[0])) for k, v in err.items()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("csv"); ap.add_argument("--allow-synthetic", action="store_true"); a = ap.parse_args()
    res = evaluate(load(a.csv, a.allow_synthetic), Config())
    for k, tgt in (("hr", 8), ("spo2", 5)):
        m, n = res[k]; print(f"{k}: MAPE {m:.2f}% over {n} windows (target <= {tgt}%) -> {'meets' if n >= 100 and m <= tgt else 'NOT shown to meet'} target")
    print("Note: valid only on real, representative patient data; this is not clinical validation.")
