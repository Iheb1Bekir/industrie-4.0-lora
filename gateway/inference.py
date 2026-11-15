"""Local inference service (runs on the Raspberry Pi, no network access needed).

Loads the ACTIVE model version from MODEL_DIR (ml/models/active.json -> ml/models/<version>/).
If no model can be loaded the platform keeps collecting data and threshold alerts keep working; predictions
are then stored with status "model_unavailable" (never silently skipped, never faked).

Prediction type: "threshold_breach_10min" = estimated risk that a configured threshold condition
(HR > 120 bpm, SpO2 < 92 %, temperature >= 38.0 C) starts within the next 10 minutes, given the last
15 minutes of measurements. It is an engineering early-warning indicator trained on SYNTHETIC data,
not a diagnosis and not clinically validated.
"""
import hashlib
import json
import os
import threading
import time
from collections import deque

from . import features as F

PREDICTION_TYPE = "threshold_breach_10min"
DISCLAIMER = ("Decision-support estimate from a model trained on synthetic data. Not clinically validated; "
              "it assists and never replaces clinical judgement.")


class ModelUnavailable(Exception):
    pass


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


class Predictor:
    def __init__(self, model_dir):
        self.model_dir = model_dir
        self._lock = threading.Lock()
        self.bundle, self.meta, self.error = None, None, "not loaded"
        self.loaded_at = None
        self.latencies = deque(maxlen=500)
        self.n_predictions = self.n_errors = 0
        self.reload()

    # ---- model registry on disk --------------------------------------------------------------------
    def active_version(self):
        try:
            with open(os.path.join(self.model_dir, "active.json")) as f:
                return json.load(f).get("version")
        except (OSError, ValueError):
            return None

    def versions(self):
        out = []
        if os.path.isdir(self.model_dir):
            for v in sorted(os.listdir(self.model_dir)):
                mp = os.path.join(self.model_dir, v, "metadata.json")
                if os.path.isfile(mp):
                    with open(mp) as f:
                        m = json.load(f)
                    out.append({"version": v, "model_name": m.get("model_name"), "trained_at": m.get("trained_at"),
                                "dataset_version": m.get("dataset", {}).get("version"), "active": v == self.active_version()})
        return out

    def set_active(self, version):
        """Atomically switch the active version (deploy or rollback) and reload. Raises ModelUnavailable."""
        self._load(version)  # validate before switching
        tmp = os.path.join(self.model_dir, "active.json.tmp")
        prev = self.active_version()
        with open(tmp, "w") as f:
            json.dump({"version": version, "previous": prev, "activated_at": time.time()}, f)
        os.replace(tmp, os.path.join(self.model_dir, "active.json"))
        return self.reload()

    def previous_version(self):
        try:
            with open(os.path.join(self.model_dir, "active.json")) as f:
                return json.load(f).get("previous")
        except (OSError, ValueError):
            return None

    def _load(self, version):
        if not version or os.sep in version or "/" in version or version.startswith("."):
            raise ModelUnavailable("no active model version configured")
        d = os.path.join(self.model_dir, version)
        mpath, apath = os.path.join(d, "metadata.json"), os.path.join(d, "model.joblib")
        if not (os.path.isfile(mpath) and os.path.isfile(apath)):
            raise ModelUnavailable(f"model version {version!r} not found in {self.model_dir}")
        with open(mpath) as f:
            meta = json.load(f)
        if meta.get("artifact_sha256") != _sha256(apath):
            raise ModelUnavailable("model artifact checksum does not match metadata.json (corrupted or modified)")
        if meta.get("feature_version") != F.FEATURE_VERSION or list(meta.get("features", [])) != list(F.FEATURE_NAMES):
            raise ModelUnavailable("model was trained with a different feature definition")
        try:
            import joblib
            import sklearn
            bundle = joblib.load(apath)
        except Exception as e:  # noqa: BLE001 - any load failure must degrade gracefully
            raise ModelUnavailable(f"cannot load model artifact: {e}") from e
        meta["runtime_sklearn"] = sklearn.__version__
        meta["sklearn_version_match"] = sklearn.__version__ == meta.get("dependencies", {}).get("scikit-learn")
        return bundle, meta

    def reload(self):
        try:
            bundle, meta = self._load(self.active_version())
            with self._lock:
                self.bundle, self.meta, self.error, self.loaded_at = bundle, meta, None, time.time()
        except ModelUnavailable as e:
            with self._lock:
                self.bundle, self.meta, self.error = None, None, str(e)
        return self.status()

    # ---- status ------------------------------------------------------------------------------------
    def status(self):
        lat = sorted(self.latencies)
        pct = lambda p: round(lat[min(len(lat) - 1, int(p * len(lat)))], 3) if lat else None  # noqa: E731
        return {
            "loaded": self.bundle is not None, "error": self.error,
            "model_name": self.meta.get("model_name") if self.meta else None,
            "model_version": self.meta.get("version") if self.meta else None,
            "loaded_at": self.loaded_at, "prediction_type": PREDICTION_TYPE,
            "sklearn_version_match": self.meta.get("sklearn_version_match") if self.meta else None,
            "predictions": self.n_predictions, "errors": self.n_errors,
            "latency_ms": {"n": len(lat), "p50": pct(0.5), "p95": pct(0.95), "max": round(lat[-1], 3) if lat else None},
            "health": "ok" if self.bundle is not None and self.n_errors == 0 else
                      ("degraded" if self.bundle is not None else "unavailable"),
        }

    # ---- inference ---------------------------------------------------------------------------------
    def predict(self, samples, now):
        """samples: chronological dicts {ts, hr, spo2, temp, fall}. Never raises."""
        t0 = time.perf_counter()
        base = {"prediction_type": PREDICTION_TYPE, "score": None, "probability": None, "threshold": None,
                "risk_category": "unknown", "explanation": [], "supporting": {}, "model_name": None, "model_version": None}
        with self._lock:
            bundle, meta = self.bundle, self.meta
        if bundle is None:
            return {**base, "status": "model_unavailable", "latency_ms": 0.0, "detail": self.error}
        base.update(model_name=meta["model_name"], model_version=meta["version"])
        feats = F.compute_features(samples, now)
        if feats is None:
            return {**base, "status": "insufficient_data", "latency_ms": (time.perf_counter() - t0) * 1000,
                    "detail": f"need at least {F.MIN_VALID} valid HR and SpO2 samples in the last {F.WINDOW_S // 60} minutes"}
        try:
            import numpy as np
            x = np.array([F.vector(feats)], dtype=float)
            model, medians = bundle["model"], np.array(bundle["medians"], dtype=float)
            # one batched call: row 0 = actual features, row j+1 = feature j replaced by its training median
            batch = np.repeat(x, len(F.FEATURE_NAMES) + 1, axis=0)
            for j in range(len(F.FEATURE_NAMES)):
                batch[j + 1, j] = medians[j]
            scores = model.predict_proba(batch)[:, 1]
            score = float(scores[0])
            contrib = score - scores[1:]
            cal = bundle.get("calibrator")
            prob = float(cal.predict([score])[0]) if cal is not None else None
            thr = bundle["thresholds"]
            risk = "high" if score >= thr["high"] else "medium" if score >= thr["medium"] else "low"
            order = sorted(range(len(contrib)), key=lambda j: -abs(contrib[j]))[:5]
            explanation = [{"feature": F.FEATURE_NAMES[j], "label": F.describe(F.FEATURE_NAMES[j]),
                            "value": None if feats[F.FEATURE_NAMES[j]] != feats[F.FEATURE_NAMES[j]] else round(feats[F.FEATURE_NAMES[j]], 3),
                            "contribution": round(float(contrib[j]), 4),
                            "direction": "raises risk" if contrib[j] > 0 else "lowers risk"}
                           for j in order if abs(contrib[j]) >= 1e-4]
            supporting = {k: (None if feats[k] != feats[k] else round(feats[k], 3)) for k in
                          ("hr_last", "spo2_last", "temp_last", "hr_slope10", "spo2_slope10", "temp_slope10",
                           "hr_eta", "spo2_eta", "temp_eta", "n_samples")}
            ms = (time.perf_counter() - t0) * 1000
            self.latencies.append(ms)
            self.n_predictions += 1
            return {**base, "status": "ok", "score": round(score, 5), "probability": None if prob is None else round(prob, 4),
                    "threshold": thr["high"], "risk_category": risk, "explanation": explanation,
                    "supporting": supporting, "latency_ms": ms}
        except Exception as e:  # noqa: BLE001 - inference failure must not stop ingestion
            self.n_errors += 1
            return {**base, "status": "inference_error", "latency_ms": (time.perf_counter() - t0) * 1000, "detail": str(e)[:200]}
