"""Prediction service.

* TFLiteLSTM  : loads ml/artifacts/lstm.tflite if (and only if) an artifact + runtime exist. No trained model ships
                with this project; the loader is UNTESTED against a real artifact.
* LR fallback : scikit-learn LinearRegression on the last WINDOW samples, extrapolated in STEP_MINUTES steps.
                This is a trend-extrapolation baseline, NOT a validated clinical forecast.
Status values: "model" | "regression_fallback" | "insufficient_data".
"""
import json
import os
import numpy as np
from sklearn.linear_model import LinearRegression

SIGNALS = ("hr", "spo2", "temp")
BOUNDS = {"hr": (20, 250), "spo2": (50, 100), "temp": (25, 45)}
DISCLAIMER = "Prototype estimate. Not clinically validated; not for treatment decisions."


class ModelUnavailable(Exception):
    """Raised when no usable model artifact or runtime is available."""


def risk_rule(pred: dict, cfg):
    """Report eq.(1): High if SpO2<92 or HR>120; Medium if SpO2<95 or HR>100; else Low. High has precedence.
    Evaluated over every predicted step. Returns (risk, reason)."""
    spo2 = [v for v in (pred.get("spo2") or [])]
    hr = [v for v in (pred.get("hr") or [])]
    if not spo2 and not hr:
        return "unknown", "no predictable signal"
    if any(v < cfg.RISK_HIGH_SPO2 for v in spo2): return "high", f"predicted SpO2 < {cfg.RISK_HIGH_SPO2:g}"
    if any(v > cfg.RISK_HIGH_HR for v in hr): return "high", f"predicted HR > {cfg.RISK_HIGH_HR:g}"
    if any(v < cfg.RISK_MED_SPO2 for v in spo2): return "medium", f"predicted SpO2 < {cfg.RISK_MED_SPO2:g}"
    if any(v > cfg.RISK_MED_HR for v in hr): return "medium", f"predicted HR > {cfg.RISK_MED_HR:g}"
    return "low", "predicted values within normal prototype ranges"


class TFLiteLSTM:
    """Contract: input float32 [1, WINDOW, 3] (hr,spo2,temp), standardized with mean/std from '<model>.json';
    output float32 [1, steps, 3] in standardized units."""

    def __init__(self, path, window):
        self.window = window
        if not os.path.isfile(path):
            raise ModelUnavailable(f"no model artifact at {path}")
        try:
            try:
                from tflite_runtime.interpreter import Interpreter
            except ImportError:
                from tensorflow.lite.python.interpreter import Interpreter
        except ImportError as e:
            raise ModelUnavailable("no TFLite runtime installed") from e
        try:
            with open(path + ".json") as f: meta = json.load(f)
            self.mean, self.std = np.array(meta["mean"], np.float32), np.array(meta["std"], np.float32)
            self.it = Interpreter(model_path=path); self.it.allocate_tensors()
            self.inp, self.out = self.it.get_input_details()[0], self.it.get_output_details()[0]
            if tuple(self.inp["shape"]) != (1, window, 3): raise ValueError(f"unexpected input shape {self.inp['shape']}")
        except Exception as e:
            raise ModelUnavailable(f"invalid model artifact: {e}") from e

    def predict(self, rows, steps):
        x = np.array([[r[s] for s in SIGNALS] for r in rows[-self.window:]], np.float32)
        if len(x) < self.window or np.isnan(x).any(): raise ModelUnavailable("window incomplete")
        self.it.set_tensor(self.inp["index"], ((x - self.mean) / self.std)[None])
        self.it.invoke()
        y = self.it.get_tensor(self.out["index"])[0] * self.std + self.mean
        return {s: [float(v) for v in y[:steps, i]] for i, s in enumerate(SIGNALS)}


class PredictionService:
    def __init__(self, cfg):
        self.cfg, self.lstm, self.note = cfg, None, ""
        self.reload()

    def reload(self):
        try:
            self.lstm, self.note = TFLiteLSTM(self.cfg.MODEL_PATH, self.cfg.WINDOW), "TFLite LSTM loaded"
        except ModelUnavailable as e:
            self.lstm, self.note = None, f"LSTM unavailable ({e}); using linear-regression fallback"
        return self.status()

    def status(self):
        return {"model": "tflite_lstm" if self.lstm else "linear_regression_fallback",
                "trained_artifact_loaded": bool(self.lstm), "note": self.note, "validated": False}

    def _lr(self, rows, steps):
        """Per-signal LR over time in minutes; returns (pred, slopes_per_min, n_used)."""
        pred, slopes, n_used = {}, {}, 0
        for s in SIGNALS:
            pts = [(r["ts"] / 60.0, r[s]) for r in rows if r.get(s) is not None]
            if len(pts) < self.cfg.MIN_SAMPLES: continue
            t = np.array([p[0] for p in pts]); y = np.array([p[1] for p in pts], float)
            if t.max() == t.min(): continue
            m = LinearRegression().fit((t - t[-1]).reshape(-1, 1), y)
            fut = np.arange(1, steps + 1) * self.cfg.STEP_MINUTES
            lo, hi = BOUNDS[s]
            vals = np.clip(m.predict(fut.reshape(-1, 1)), lo, hi)
            pred[s] = [round(float(v), 1 if s == "temp" else 0) for v in vals]
            slopes[s] = float(m.coef_[0]); n_used = max(n_used, len(pts))
        return pred, slopes, n_used

    def predict(self, pid, rows, horizon, now):
        steps = max(1, horizon // self.cfg.STEP_MINUTES)
        base = {"pid": pid, "horizon_min": horizon, "step_minutes": self.cfg.STEP_MINUTES, "generated_ts": int(now),
                "disclaimer": DISCLAIMER, "synthetic_input": any(r.get("synthetic") for r in rows)}
        pred, status, slopes, n = None, "regression_fallback", {}, 0
        if self.lstm:
            try:
                pred, status, n = self.lstm.predict(rows, steps), "model", len(rows)
            except ModelUnavailable:
                pred = None
        if pred is None:
            status = "regression_fallback"
            pred, slopes, n = self._lr(rows, steps)
        if not pred:
            return {**base, "status": "insufficient_data", "model": self.status()["model"], "pred": None, "risk": "unknown",
                    "reason": f"need at least {self.cfg.MIN_SAMPLES} valid samples with distinct timestamps", "samples_used": len(rows)}
        risk, reason = risk_rule(pred, self.cfg)
        if risk == "low" and slopes:
            tr = [f"{s} trending {'up' if v > 0 else 'down'}" for s, v in slopes.items()
                  if abs(v) * horizon >= {"hr": 5, "spo2": 1, "temp": 0.3}[s]]
            reason = "; ".join(tr) if tr else "no significant trend"
        return {**base, "status": status, "model": "tflite_lstm" if status == "model" else "linear_regression_fallback",
                "pred": pred, "risk": risk, "reason": reason, "samples_used": n}
