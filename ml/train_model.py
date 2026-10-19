#!/usr/bin/env python3
"""Train the TFLite LSTM described in the report (section 5.1). UNTESTED in this repository: it needs TensorFlow and a
REAL dataset, neither of which exists yet (report status: Pre-MVP, no measurements).

Input CSV columns: pid,ts,hr,spo2,temp[,synthetic]  (e.g. exported by gateway.maintenance).
Rows with synthetic=1 are refused unless --allow-synthetic (a model trained on synthetic data says nothing clinically).
Contract (see gateway/prediction.py): input [1,30,3] standardized, output [1,3,3] standardized (steps at +5/+10/+15 min).
Usage: python ml/train_model.py data.csv --out ml/artifacts/lstm.tflite
"""
import argparse, csv, json, os, sys
import numpy as np

W, STEPS, STEP_MIN = 30, 3, 5


def load(path, allow_synth):
    by = {}
    for r in csv.DictReader(open(path)):
        if str(r.get("synthetic", "0")) == "1" and not allow_synth:
            continue
        try: v = [float(r["hr"]), float(r["spo2"]), float(r["temp"])]
        except (ValueError, KeyError): continue
        by.setdefault(r["pid"], []).append((int(r["ts"]), v))
    return {k: sorted(v) for k, v in by.items()}


def windows(series):
    X, Y = [], []
    for s in series.values():
        ts = [t for t, _ in s]; vs = np.array([v for _, v in s], np.float32)
        for i in range(W, len(s)):
            tgt = []
            for k in range(1, STEPS + 1):
                j = int(np.argmin([abs(t - (ts[i - 1] + k * STEP_MIN * 60)) for t in ts[i:i + 30]] or [0])) + i if i < len(s) else None
                if j is None or j >= len(s) or abs(ts[j] - (ts[i - 1] + k * STEP_MIN * 60)) > 90: break
                tgt.append(vs[j])
            if len(tgt) == STEPS: X.append(vs[i - W:i]); Y.append(np.stack(tgt))
    return np.array(X), np.array(Y)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("csv"); ap.add_argument("--out", default="ml/artifacts/lstm.tflite")
    ap.add_argument("--min-windows", type=int, default=1000, help="report validation plan: 1000 samples"); ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--allow-synthetic", action="store_true"); a = ap.parse_args()
    try:
        import tensorflow as tf
    except ImportError:
        sys.exit("TensorFlow is not installed (pip install tensorflow on a training PC). Nothing trained.")
    X, Y = windows(load(a.csv, a.allow_synthetic))
    if len(X) < a.min_windows: sys.exit(f"only {len(X)} usable windows (< {a.min_windows}); refusing to train a meaningless model")
    split = int(len(X) * 0.8)                       # chronological 80/20 per report; no shuffling
    mean, std = X[:split].reshape(-1, 3).mean(0), X[:split].reshape(-1, 3).std(0) + 1e-6
    n = lambda z: (z - mean) / std
    m = tf.keras.Sequential([tf.keras.layers.Input((W, 3)), tf.keras.layers.LSTM(32), tf.keras.layers.Dense(STEPS * 3), tf.keras.layers.Reshape((STEPS, 3))])
    m.compile("adam", "mse"); m.fit(n(X[:split]), n(Y[:split]), epochs=a.epochs, validation_data=(n(X[split:]), n(Y[split:])), verbose=2)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "wb").write(tf.lite.TFLiteConverter.from_keras_model(m).convert())
    json.dump({"mean": mean.tolist(), "std": std.tolist()}, open(a.out + ".json", "w"))
    print("saved", a.out, "- now run ml/evaluate_model.py; do NOT call the model validated until targets are met on real data")


if __name__ == "__main__":
    main()
