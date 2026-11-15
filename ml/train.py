#!/usr/bin/env python3
"""Training + evaluation pipeline for the early-warning model.

Prediction target ("threshold_breach_10min"): at time t, given only measurements up to t, will a configured
threshold condition (HR > 120 bpm, SpO2 < 92 %, temperature >= 38.0 C) START within the next 10 minutes?
"Start" means a SUSTAINED condition (two consecutive delivered samples), so isolated motion artifacts are not
prediction targets. Rows where a threshold condition is present (or was within the previous 5 minutes) are
excluded: those are handled by immediate threshold alerts, not by prediction.

Protocol (identical for every model):
  * split BY PATIENT (60 % train / 20 % validation / 20 % test) - adjacent rows of one patient never straddle sets
  * decision threshold chosen on the validation set (max F2: recall weighted over precision), then frozen
  * every reported number is computed on the held-out test set by this script and written to metrics.json
  * model choice uses validation PR-AUC only (the test set is never used for selection)

Usage:  python ml/train.py                      # generate dataset if missing, train, evaluate, save, activate
        python ml/train.py --version ew-2 --no-activate
Outputs: ml/models/<version>/{model.joblib, metadata.json, metrics.json, curves.json}, docs/MODEL_EVALUATION.md
"""
import argparse
import bisect
import csv
import gzip
import hashlib
import json
import os
import platform
import sys
import time

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from gateway import features as F  # noqa: E402

HORIZON_S, RECENT_S, SPLIT_SEED = 600, 300, 12345
TARGET = ("A SUSTAINED threshold condition (HR > 120 bpm, SpO2 < 92 % or temperature >= 38.0 C on two consecutive samples) "
          "starts within the next 10 minutes, given the last 15 minutes of measurements; rows already in (or within 5 min "
          "after) a threshold condition are excluded.")


# ------------------------------------------------------------------------------------------------ data
def load_dataset(ddir):
    with open(os.path.join(ddir, "manifest.json")) as f:
        manifest = json.load(f)
    series = {}
    with gzip.open(os.path.join(ddir, "measurements.csv.gz"), "rt", newline="") as f:
        for r in csv.DictReader(f):
            series.setdefault(int(r["patient_id"]), []).append(
                {"ts": int(r["t"]), "hr": float(r["hr"]) if r["hr"] != "" else None,
                 "spo2": float(r["spo2"]) if r["spo2"] != "" else None,
                 "temp": float(r["temp"]) if r["temp"] != "" else None, "fall": int(r["fall"])})
    return manifest, series


def build_rows(samples):
    """Feature vectors + labels for one patient. Returns (X, y, t, breach_times)."""
    ts = [s["ts"] for s in samples]
    br = [F.breach(s["hr"], s["spo2"], s["temp"]) for s in samples]
    btimes = [t for t, b in zip(ts, br) if b]                                   # any single-sample breach (eligibility)
    stimes = [ts[i] for i in range(1, len(ts)) if br[i] and br[i - 1]]          # sustained breach (label)
    X, y, tt = [], [], []
    for i, s in enumerate(samples):
        t = s["ts"]
        j = bisect.bisect_right(btimes, t)               # breaches at or before t
        if j > 0 and btimes[j - 1] > t - RECENT_S:
            continue                                     # in / just after a threshold condition: not a prediction row
        lo = bisect.bisect_left(ts, t - F.LOOKBACK_S)
        feats = F.compute_features(samples[lo:i + 1], t)
        if feats is None:
            continue                                     # insufficient history (the live service reports this too)
        X.append(F.vector(feats)); tt.append(t)
        k = bisect.bisect_right(stimes, t)
        y.append(1 if k < len(stimes) and stimes[k] <= t + HORIZON_S else 0)
    onsets = [t for k, t in enumerate(stimes) if k == 0 or t - stimes[k - 1] > RECENT_S]
    return X, y, tt, onsets


def assemble(series, pids):
    X, y, groups, times, onsets = [], [], [], [], {}
    for pid in pids:
        xi, yi, ti, oi = build_rows(series[pid])
        X += xi; y += yi; times += ti; groups += [pid] * len(yi); onsets[pid] = oi
    return (np.array(X, dtype=float).reshape(-1, len(F.FEATURE_NAMES)), np.array(y, dtype=int), np.array(groups), np.array(times), onsets)


# ------------------------------------------------------------------------------------------------ metrics
def ece(y, p, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    out, table = 0.0, []
    for b in range(bins):
        m = idx == b
        if m.any():
            conf, acc = float(p[m].mean()), float(y[m].mean())
            out += m.mean() * abs(conf - acc)
            table.append({"bin": b, "mean_predicted": round(conf, 4), "observed_rate": round(acc, 4), "n": int(m.sum())})
    return float(out), table


def metrics_at(y, s, thr):
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    pred = s >= thr
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    fn, tn = int((~pred & (y == 1)).sum()), int((~pred & (y == 0)).sum())
    div = lambda a, b: float(a / b) if b else 0.0  # noqa: E731
    prec, rec, spec = div(tp, tp + fp), div(tp, tp + fn), div(tn, tn + fp)
    return {"n": int(len(y)), "positives": int(y.sum()), "prevalence": round(float(y.mean()), 5), "threshold": float(thr),
            "accuracy": div(tp + tn, len(y)), "precision": prec, "recall": rec, "sensitivity": rec, "specificity": spec,
            "f1": div(2 * prec * rec, prec + rec), "f2": div(5 * prec * rec, 4 * prec + rec), "fpr": div(fp, fp + tn), "fnr": div(fn, fn + tp),
            "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
            "roc_auc": float(roc_auc_score(y, s)), "pr_auc": float(average_precision_score(y, s)),
            "brier_raw": float(brier_score_loss(y, np.clip(s, 0, 1))), "ece_raw": ece(y, np.clip(s, 0, 1))[0]}


def choose_threshold(y, s, beta=2.0):
    from sklearn.metrics import precision_recall_curve
    p, r, t = precision_recall_curve(y, s)
    f = (1 + beta ** 2) * p[:-1] * r[:-1] / np.maximum(beta ** 2 * p[:-1] + r[:-1], 1e-12)
    high = float(t[int(np.argmax(f))])
    ok = np.nonzero(r[:-1] >= 0.80)[0]
    med = float(t[ok[-1]]) if len(ok) else high / 2
    if med >= high:
        med = high / 2
    return high, med


def event_metrics(groups, times, scores, y, onsets, thr, total_seconds):
    """Episode-level view on the test set: was each threshold-crossing episode warned in advance, how early,
    and how many false alarm episodes per patient-day."""
    detected, leads, n_events, false_alarms = 0, [], 0, 0
    for pid in np.unique(groups):
        m = groups == pid
        t, s, yy = times[m], scores[m], y[m]
        alarm_t = t[s >= thr]
        for onset in onsets.get(int(pid), []):
            if not ((t >= onset - HORIZON_S) & (t < onset)).any():
                continue                                 # no eligible row before the episode (e.g. data gap): not assessable
            n_events += 1
            hits = alarm_t[(alarm_t >= onset - HORIZON_S) & (alarm_t < onset)]
            if len(hits):
                detected += 1; leads.append(float(onset - hits.min()))
        last = -1e18
        for ft in t[(s >= thr) & (yy == 0)]:
            if ft - last > HORIZON_S:
                false_alarms += 1
            last = ft
    days = total_seconds / 86400
    return {"events": n_events, "detected": detected, "event_recall": round(detected / n_events, 4) if n_events else None,
            "median_lead_s": round(float(np.median(leads)), 1) if leads else None,
            "p25_lead_s": round(float(np.percentile(leads, 25)), 1) if leads else None,
            "false_alarm_episodes": false_alarms, "false_alarms_per_patient_day": round(false_alarms / days, 3) if days else None}


# ------------------------------------------------------------------------------------------------ models
def candidates(seed):
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return {
        "logistic_regression": (make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                              LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000)),
                                {"C": 1.0, "class_weight": "balanced", "imputer": "median", "scaler": "standard"}),
        "random_forest": (make_pipeline(SimpleImputer(strategy="median"),
                                        RandomForestClassifier(n_estimators=200, max_depth=12, min_samples_leaf=5,
                                                               class_weight="balanced_subsample", n_jobs=-1, random_state=seed)),
                          {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 5, "class_weight": "balanced_subsample"}),
        "hist_gradient_boosting": (HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_depth=6, l2_regularization=1.0,
                                                                  class_weight="balanced", random_state=seed),
                                   {"max_iter": 300, "learning_rate": 0.06, "max_depth": 6, "l2_regularization": 1.0,
                                    "class_weight": "balanced", "native_missing_values": True}),
    }


def latency_ms(model, x_row, n=200):
    """Median time of one live inference: the service scores the row plus one occlusion row per feature."""
    batch = np.repeat(x_row.reshape(1, -1), len(F.FEATURE_NAMES) + 1, axis=0)
    model.predict_proba(batch)
    ts = []
    for _ in range(n):
        t0 = time.perf_counter(); model.predict_proba(batch); ts.append((time.perf_counter() - t0) * 1000)
    return round(float(np.median(ts)), 3)


def curve_points(x, y, n=200):
    idx = np.unique(np.linspace(0, len(x) - 1, min(n, len(x))).astype(int))
    return [[round(float(x[i]), 5), round(float(y[i]), 5)] for i in idx]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default=os.path.join(ROOT, "ml", "data", "synth-v2"))
    ap.add_argument("--version", default="ew-" + time.strftime("%Y%m%d", time.gmtime()))
    ap.add_argument("--models-dir", default=os.path.join(ROOT, "ml", "models"))
    ap.add_argument("--seed", type=int, default=7); ap.add_argument("--no-activate", action="store_true")
    ap.add_argument("--no-report", action="store_true", help="do not rewrite docs/MODEL_EVALUATION.md")
    a = ap.parse_args(argv)
    import joblib
    import sklearn
    from sklearn.ensemble import IsolationForest
    from sklearn.inspection import permutation_importance
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import brier_score_loss, precision_recall_curve, roc_curve

    if not os.path.isfile(os.path.join(a.dataset, "manifest.json")):
        import generate_dataset
        print("dataset not found - generating it with the default configuration ...")
        generate_dataset.generate(dict(generate_dataset.DEFAULTS, version=os.path.basename(a.dataset)), a.dataset)
    manifest, series = load_dataset(a.dataset)
    pids = sorted(series)
    rng = np.random.default_rng(SPLIT_SEED)
    perm = rng.permutation(pids)
    n_tr, n_va = int(0.6 * len(perm)), int(0.2 * len(perm))
    split = {"train": sorted(int(p) for p in perm[:n_tr]), "val": sorted(int(p) for p in perm[n_tr:n_tr + n_va]),
             "test": sorted(int(p) for p in perm[n_tr + n_va:])}
    assert not (set(split["train"]) & set(split["val"])) and not (set(split["train"]) & set(split["test"])) and not (set(split["val"]) & set(split["test"]))
    t0 = time.time()
    data = {k: assemble(series, v) for k, v in split.items()}
    print(f"features built in {time.time() - t0:.1f} s:", {k: (d[0].shape[0], int(d[1].sum())) for k, d in data.items()})
    (Xtr, ytr, _, _, _), (Xva, yva, _, _, _), (Xte, yte, gte, tte, onsets_te) = data["train"], data["val"], data["test"]
    test_seconds = sum(series[p][-1]["ts"] - series[p][0]["ts"] for p in split["test"])
    medians = np.nanmedian(Xtr, axis=0)
    results, fitted = {}, {}

    def evaluate(name, score_fn, params, deployable):
        s_va, s_te = score_fn(Xva), score_fn(Xte)
        high, med = choose_threshold(yva, s_va)
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(s_va, yva)
        p_te = iso.predict(s_te)
        test = metrics_at(yte, s_te, high)
        test["brier_calibrated"] = float(brier_score_loss(yte, p_te))
        test["ece_calibrated"], cal_table = ece(yte, p_te)
        test["events"] = event_metrics(gte, tte, s_te, yte, onsets_te, high, test_seconds)
        results[name] = {"params": params, "deployable": deployable, "thresholds": {"high": high, "medium": med},
                         "validation": metrics_at(yva, s_va, high), "test": test}
        return s_te, iso, cal_table, (high, med)

    aux = {}
    for name, (model, params) in candidates(a.seed).items():
        t1 = time.time()
        model.fit(Xtr, ytr)
        fitted[name] = model
        aux[name] = evaluate(name, lambda X, m=model: m.predict_proba(X)[:, 1], params, True)
        results[name]["fit_seconds"] = round(time.time() - t1, 2)
        results[name]["inference_latency_ms"] = latency_ms(model, Xte[0])
        print(f"{name:<24} val PR-AUC {results[name]['validation']['pr_auc']:.4f}  test PR-AUC {results[name]['test']['pr_auc']:.4f}  "
              f"recall {results[name]['test']['recall']:.3f}  precision {results[name]['test']['precision']:.3f}  "
              f"latency {results[name]['inference_latency_ms']} ms")
    # Reference baselines evaluated with the SAME protocol (not deployable)
    imp = lambda X: np.where(np.isnan(X), medians, X)  # noqa: E731
    iforest = IsolationForest(n_estimators=200, contamination="auto", random_state=a.seed).fit(imp(Xtr))
    lo, hi = np.percentile(-iforest.score_samples(imp(Xtr)), [0.5, 99.5])
    evaluate("isolation_forest", lambda X: np.clip((-iforest.score_samples(imp(X)) - lo) / (hi - lo), 0, 1),
             {"n_estimators": 200, "unsupervised": True, "note": "anomaly score, labels never used for fitting"}, False)
    eta_cols = [F.FEATURE_NAMES.index(n) for n in ("hr_eta", "spo2_eta", "temp_eta")]
    evaluate("trend_rule_baseline", lambda X: 1.0 - np.nanmin(np.where(np.isnan(X[:, eta_cols]), F.ETA_CAP_MIN, X[:, eta_cols]), axis=1) / F.ETA_CAP_MIN,
             {"rule": "linear extrapolation of the current trend to the threshold (no learning)"}, False)
    for n in ("isolation_forest", "trend_rule_baseline"):
        print(f"{n:<24} val PR-AUC {results[n]['validation']['pr_auc']:.4f}  test PR-AUC {results[n]['test']['pr_auc']:.4f}  "
              f"recall {results[n]['test']['recall']:.3f}  precision {results[n]['test']['precision']:.3f}")

    # ---- selection: validation PR-AUC; within 0.01 of the best prefer the faster model ------------------
    dep = [n for n in results if results[n]["deployable"]]
    best = max(results[n]["validation"]["pr_auc"] for n in dep)
    close = [n for n in dep if results[n]["validation"]["pr_auc"] >= best - 0.01]
    selected = min(close, key=lambda n: results[n]["inference_latency_ms"])
    s_te, iso, cal_table, (high, med) = aux[selected]
    model = fitted[selected]
    print("selected:", selected)

    out = os.path.join(a.models_dir, a.version)
    os.makedirs(out, exist_ok=True)
    apath = os.path.join(out, "model.joblib")
    joblib.dump({"model": model, "calibrator": iso, "thresholds": {"high": high, "medium": med},
                 "medians": [float(v) for v in medians], "features": list(F.FEATURE_NAMES)}, apath, compress=3)
    with open(apath, "rb") as fh:
        h = hashlib.sha256(fh.read()).hexdigest()
    sub = np.random.default_rng(1).choice(len(yte), min(6000, len(yte)), replace=False)
    pi = permutation_importance(model, Xte[sub], yte[sub], scoring="average_precision", n_repeats=5, random_state=1, n_jobs=-1)
    order = np.argsort(-pi.importances_mean)
    fpr, tpr, _ = roc_curve(yte, s_te)
    prec, rec, _ = precision_recall_curve(yte, s_te)
    hist_edges = np.linspace(0, 1, 21)
    curves = {"roc": curve_points(fpr, tpr), "pr": curve_points(rec[::-1], prec[::-1]), "calibration": cal_table,
              "score_histogram": {"edges": [round(float(e), 2) for e in hist_edges],
                                  "negative": np.histogram(s_te[yte == 0], hist_edges)[0].tolist(),
                                  "positive": np.histogram(s_te[yte == 1], hist_edges)[0].tolist()},
              "feature_importance": [{"feature": F.FEATURE_NAMES[j], "label": F.describe(F.FEATURE_NAMES[j]),
                                      "importance": round(float(pi.importances_mean[j]), 5), "std": round(float(pi.importances_std[j]), 5)}
                                     for j in order[:15]],
              "feature_importance_method": "permutation importance on the test set (drop in PR-AUC), 5 repeats"}
    trained_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    meta = {"version": a.version, "model_name": selected, "prediction_type": "threshold_breach_10min", "target": TARGET,
            "trained_at": trained_at, "feature_version": F.FEATURE_VERSION, "features": list(F.FEATURE_NAMES),
            "parameters": results[selected]["params"], "thresholds": {"high": high, "medium": med},
            "threshold_policy": "high = max F2 on validation; medium = validation threshold with recall >= 0.80",
            "calibration": "isotonic regression fitted on validation scores",
            "selection_rule": "highest validation PR-AUC among deployable models; within 0.01 the lowest inference latency wins",
            "dataset": {"version": manifest["version"], "synthetic": True, "seed": manifest["config"]["seed"],
                        "content_sha256": manifest["content_sha256"], "split_seed": SPLIT_SEED, "split": "by patient 60/20/20",
                        "patients": {k: len(v) for k, v in split.items()}, "test_patient_ids": split["test"],
                        "samples": {k: int(d[0].shape[0]) for k, d in data.items()},
                        "positives": {k: int(d[1].sum()) for k, d in data.items()}},
            "artifact": "model.joblib", "artifact_sha256": h,
            "dependencies": {"python": platform.python_version(), "scikit-learn": sklearn.__version__, "numpy": np.__version__,
                             "joblib": joblib.__version__},
            "training_host": platform.machine(), "random_seed": a.seed,
            "limitations": "Trained and evaluated on synthetic data only. Not clinically validated."}
    metrics = {"version": a.version, "selected": selected, "generated_at": trained_at, "horizon_s": HORIZON_S, "models": results}
    for name, obj in (("metadata.json", meta), ("metrics.json", metrics), ("curves.json", curves)):
        with open(os.path.join(out, name), "w") as f:
            json.dump(obj, f, indent=2)
    if not a.no_activate:
        active = os.path.join(a.models_dir, "active.json")
        prev = None
        if os.path.isfile(active):
            with open(active) as f:
                prev = json.load(f).get("version")
        with open(active, "w") as f:
            json.dump({"version": a.version, "previous": prev if prev != a.version else None, "activated_at": time.time()}, f)
    if not a.no_report:
        write_report(meta, metrics, curves, os.path.join(ROOT, "docs", "MODEL_EVALUATION.md"))
    print(f"saved {out} (sha256 {h[:16]}...){'' if a.no_activate else ' and activated'}")
    return 0


def write_report(meta, metrics, curves, path):
    """docs/MODEL_EVALUATION.md is GENERATED from metrics.json - never edit the numbers by hand."""
    ds, sel = meta["dataset"], metrics["models"][meta["model_name"]]
    L = ["# Model evaluation", "",
         "> **Generated file.** Written by `ml/train.py` from `ml/models/%s/metrics.json`. Do not edit numbers by hand; re-run the pipeline." % meta["version"],
         "> All data is **synthetic**. These figures describe how well the model recovers patterns of the generator, **not clinical performance**.", "",
         f"* Model version: `{meta['version']}` - selected model: **{meta['model_name']}** - trained {meta['trained_at']}",
         f"* Prediction target: {meta['target']}",
         f"* Dataset: `{ds['version']}` (seed {ds['seed']}, sha256 `{ds['content_sha256'][:16]}...`), split by patient {ds['split'].split()[-1]} (split seed {ds['split_seed']})",
         f"* Patients train / validation / test: {ds['patients']['train']} / {ds['patients']['val']} / {ds['patients']['test']}",
         f"* Samples (prediction rows) train / validation / test: {ds['samples']['train']} / {ds['samples']['val']} / {ds['samples']['test']}",
         f"* Positive rows train / validation / test: {ds['positives']['train']} / {ds['positives']['val']} / {ds['positives']['test']}",
         f"* Software: Python {meta['dependencies']['python']}, scikit-learn {meta['dependencies']['scikit-learn']}, numpy {meta['dependencies']['numpy']}",
         f"* Selection rule: {meta['selection_rule']}", f"* Threshold policy: {meta['threshold_policy']}", "",
         "## Held-out test set - all models, same protocol", "",
         "| Model | Deployable | Threshold | Accuracy | Precision | Recall (sensitivity) | Specificity | F1 | ROC-AUC | PR-AUC | FPR | FNR | Brier (cal.) | ECE (cal.) | Latency ms |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, m in metrics["models"].items():
        t = m["test"]
        L.append(f"| {'**' + n + '**' if n == meta['model_name'] else n} | {'yes' if m['deployable'] else 'baseline'} | {t['threshold']:.4f} | "
                 f"{t['accuracy']:.4f} | {t['precision']:.4f} | {t['recall']:.4f} | {t['specificity']:.4f} | {t['f1']:.4f} | {t['roc_auc']:.4f} | "
                 f"{t['pr_auc']:.4f} | {t['fpr']:.4f} | {t['fnr']:.4f} | {t['brier_calibrated']:.4f} | {t['ece_calibrated']:.4f} | {m.get('inference_latency_ms', '-')} |")
    cm, ev = sel["test"]["confusion_matrix"], sel["test"]["events"]
    L += ["", f"Test prevalence of the positive class: {sel['test']['prevalence']:.4f} ({sel['test']['positives']} of {sel['test']['n']} rows). "
          "Accuracy is dominated by the negative class; read precision / recall / PR-AUC.", "",
          f"## Selected model: {meta['model_name']}", "", "Confusion matrix (test, at the frozen validation threshold):", "",
          "| | predicted negative | predicted positive |", "|---|---|---|",
          f"| actual negative | TN = {cm['tn']} | FP = {cm['fp']} |", f"| actual positive | FN = {cm['fn']} | TP = {cm['tp']} |", "",
          "Episode-level view (test): "
          f"{ev['detected']} of {ev['events']} threshold-crossing episodes received at least one warning in the 10 minutes before onset "
          f"(episode recall {ev['event_recall']}); median lead time {ev['median_lead_s']} s (25th percentile {ev['p25_lead_s']} s); "
          f"{ev['false_alarm_episodes']} false-alarm episodes = {ev['false_alarms_per_patient_day']} per patient-day.", "",
          "Validation metrics of the selected model (used for threshold choice and model selection): "
          f"PR-AUC {sel['validation']['pr_auc']:.4f}, ROC-AUC {sel['validation']['roc_auc']:.4f}, recall {sel['validation']['recall']:.4f}, "
          f"precision {sel['validation']['precision']:.4f}.", "",
          "## Top features (permutation importance on the test set)", "", "| Feature | Meaning | Importance (drop in PR-AUC) |", "|---|---|---|"]
    L += [f"| `{f['feature']}` | {f['label']} | {f['importance']:.4f} ± {f['std']:.4f} |" for f in curves["feature_importance"][:10]]
    L += ["", "## Calibration (isotonic, test set)", "", "| Mean predicted | Observed rate | Rows |", "|---|---|---|"]
    L += [f"| {b['mean_predicted']:.3f} | {b['observed_rate']:.3f} | {b['n']} |" for b in curves["calibration"]]
    L += ["", "## Honest reading of these results", "",
          "* The label is produced by the same generator family as the inputs; real physiology is noisier and less regular. Expect lower performance on real data.",
          "* Abrupt events (sudden desaturation, artifacts crossing a threshold) carry no advance trend; they account for most false negatives and cannot be predicted by any trend model.",
          "* The score is shown in the dashboard as a risk category. The calibrated value is labelled an estimate, not a clinical probability.",
          "* Before any clinical use the model must be re-trained and validated on real, representative, ethically approved data.", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
