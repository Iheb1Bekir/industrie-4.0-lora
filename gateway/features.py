"""Feature engineering shared by the training pipeline (ml/) and the live inference service.

ONE implementation is used for both, so there is no training/serving skew. Pure Python on purpose:
windows hold a few dozen samples, and the Raspberry Pi needs no extra dependency to compute features.

Input : chronologically ordered samples {"ts", "hr", "spo2", "temp", "fall"} (values may be None = missing /
        sensor fault) and the reference time `now` (timestamp of the newest sample).
Output: dict feature_name -> float (NaN when it cannot be computed), or None when history is insufficient.
Only data at or before `now` is used (no look-ahead, no leakage).
"""
import math

FEATURE_VERSION = "f2"
LOOKBACK_S = 900          # history needed by the model
WINDOW_S = 600            # main statistics window
SHORT_S = 180             # short-term trend window
BASELINE_S = (900, 600)   # per-patient short baseline: samples between 15 and 10 minutes ago
MIN_VALID = 6             # minimum valid HR and SpO2 samples inside WINDOW_S
# Label definition thresholds (engineering demonstration thresholds of the project, not medical rules)
THR_HR, THR_SPO2, THR_TEMP = 120.0, 92.0, 38.0
ETA_CAP_MIN = 60.0
SIGNALS = ("hr", "spo2", "temp")
NAN = float("nan")

FEATURE_NAMES = tuple(
    [f"{s}_{k}" for s in SIGNALS for k in ("last", "mean", "std", "min", "max", "slope10", "slope3", "delta_base", "missing")]
    + ["hr_med3", "spo2_med3", "hr_margin", "spo2_margin", "temp_margin", "hr_eta", "spo2_eta", "temp_eta",
       "n_samples", "gap_s", "fall_recent"])

DESCRIPTIONS = {
    "last": "latest value", "mean": "10-min average", "std": "10-min variability", "min": "10-min minimum",
    "max": "10-min maximum", "slope10": "10-min trend (per minute)", "slope3": "3-min trend (per minute)",
    "delta_base": "change versus the patient's own level 10-15 min ago", "missing": "share of missing samples",
    "med3": "median of the last 3 samples (artifact-robust level)",
    "margin": "distance to the alert threshold (artifact-robust level)", "eta": "minutes until the threshold at the current trend",
}
LABELS = {"hr": "heart rate", "spo2": "SpO2", "temp": "temperature"}


def describe(name):
    if name in ("n_samples", "gap_s", "fall_recent"):
        return {"n_samples": "number of samples in the window", "gap_s": "seconds since the previous sample",
                "fall_recent": "fall flag in the last 5 minutes"}[name]
    sig, _, kind = name.partition("_")
    return f"{LABELS.get(sig, sig)}: {DESCRIPTIONS.get(kind, kind)}"


def _slope_per_min(pts):
    """Ordinary least-squares slope of (t_seconds, value) pairs, in units per minute. NaN if < 3 points."""
    n = len(pts)
    if n < 3:
        return NAN
    mt = sum(p[0] for p in pts) / n
    mv = sum(p[1] for p in pts) / n
    den = sum((p[0] - mt) ** 2 for p in pts)
    if den <= 0:
        return NAN
    return 60.0 * sum((p[0] - mt) * (p[1] - mv) for p in pts) / den


def _eta(margin, slope_toward):
    """Minutes until the threshold is reached when moving toward it at `slope_toward` (>0) per minute."""
    if margin != margin or slope_toward != slope_toward:
        return NAN
    if margin <= 0:
        return 0.0
    if slope_toward <= 1e-6:
        return ETA_CAP_MIN
    return min(ETA_CAP_MIN, margin / slope_toward)


def compute_features(samples, now):
    win = [s for s in samples if now - WINDOW_S <= s["ts"] <= now]
    if not win:
        return None
    f = {}
    for sig in SIGNALS:
        pts = [(s["ts"], s[sig]) for s in win if s.get(sig) is not None]
        vals = [p[1] for p in pts]
        if sig in ("hr", "spo2") and len(vals) < MIN_VALID:
            return None
        if vals:
            mean = sum(vals) / len(vals)
            f[f"{sig}_last"], f[f"{sig}_mean"] = vals[-1], mean
            f[f"{sig}_std"] = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
            f[f"{sig}_min"], f[f"{sig}_max"] = min(vals), max(vals)
            s10 = _slope_per_min(pts)
            s3 = _slope_per_min([p for p in pts if p[0] >= now - SHORT_S])
            f[f"{sig}_slope10"] = 0.0 if s10 != s10 else s10
            f[f"{sig}_slope3"] = f[f"{sig}_slope10"] if s3 != s3 else s3
            base = sorted(s[sig] for s in samples
                          if now - BASELINE_S[0] <= s["ts"] < now - BASELINE_S[1] and s.get(sig) is not None)
            f[f"{sig}_delta_base"] = vals[-1] - base[len(base) // 2] if base else vals[-1] - mean
            f[f"{sig}_med3"] = sorted(vals[-3:])[len(vals[-3:]) // 2]
        else:
            f[f"{sig}_med3"] = NAN
            for k in ("last", "mean", "std", "min", "max", "slope10", "slope3", "delta_base"):
                f[f"{sig}_{k}"] = NAN
        f[f"{sig}_missing"] = 1.0 - len(vals) / len(win)
    f["hr_margin"] = THR_HR - f["hr_med3"]
    f["spo2_margin"] = f["spo2_med3"] - THR_SPO2
    f["temp_margin"] = THR_TEMP - f.pop("temp_med3") if f["temp_last"] == f["temp_last"] else (f.pop("temp_med3"), NAN)[1]
    f["hr_eta"] = _eta(f["hr_margin"], max(f["hr_slope10"], f["hr_slope3"]))
    f["spo2_eta"] = _eta(f["spo2_margin"], max(-f["spo2_slope10"], -f["spo2_slope3"]))
    f["temp_eta"] = _eta(f["temp_margin"], max(f["temp_slope10"], f["temp_slope3"])) if f["temp_margin"] == f["temp_margin"] else NAN
    f["n_samples"] = float(len(win))
    f["gap_s"] = float(win[-1]["ts"] - win[-2]["ts"]) if len(win) > 1 else float(WINDOW_S)
    f["fall_recent"] = 1.0 if any(s.get("fall") for s in win if s["ts"] >= now - 300) else 0.0
    return f


def vector(features):
    return [features[n] for n in FEATURE_NAMES]


def breach(hr, spo2, temp):
    """Immediate threshold condition of ONE sample (measured values, None = unknown). The prediction label uses a
    SUSTAINED condition: two consecutive delivered samples in breach (single-sample motion artifacts excluded)."""
    return bool((hr is not None and hr > THR_HR) or (spo2 is not None and spo2 < THR_SPO2)
                or (temp is not None and temp >= THR_TEMP))
