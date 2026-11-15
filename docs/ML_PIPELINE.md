# Machine-learning pipeline

Our own model, trained on our own (synthetic) dataset, evaluated by script, run locally on the gateway. No external AI service is called. Measured results: `MODEL_EVALUATION.md` (generated).

## 1. Prediction problem

**Type `threshold_breach_10min`** — binary early warning.

> At time *t*, using only measurements received up to *t* (last 15 minutes), will a **sustained** threshold condition — heart rate > 120 bpm, SpO2 < 92 % or temperature ≥ 38.0 °C on two consecutive delivered samples — **start within the next 10 minutes**?

* Rows where a threshold condition is present, or was present in the previous 5 minutes, are **excluded**: that situation is already covered by immediate threshold alerts.
* The label is defined by the project's own alert thresholds. It is an operational event, **not a diagnosis**. The model does not predict heart attack, stroke, death or any disease, and no clinical ground truth is invented.
* Immediate alerts (threshold, fall, sensor, device) are computed by rules and never depend on the model.

Why this target: it is fully defined by observable data, it has an unambiguous time horizon, it can be evaluated honestly, and it is exactly what scenario G must demonstrate (a warning before the threshold alert).

## 2. Dataset (`ml/generate_dataset.py`)

Everything is **synthetic**: a parametric simulator, seeded, reproducible (`content_sha256` in `manifest.json`). It must never be described as patient data.

Default `synth-v2`: 600 simulated patients × 8 h, sampling interval 15 / 30 / 60 s per patient, 627 099 delivered samples.

| Element | Model |
|---|---|
| Baselines per patient | resting HR 58–92 bpm, SpO2 94.5–98.8 %, temperature 36.2–37.1 °C |
| Normal variation | AR(1) noise per signal, slow sinusoidal HR drift, circadian temperature term |
| Episodes (0–3 per patient) | gradual HR rise, gradual SpO2 decline, fever (with HR coupling), combined deterioration, **abrupt** change (30–120 s onset), benign HR transient (activity-like), benign SpO2 dip, fall (flag + HR response); random onset, slope, depth, hold and recovery |
| Measurement layer | integer bpm / %, 0.01 °C; isolated motion-artifact spikes on HR (0.3 % of samples) |
| Missing data | 2 % random loss, communication outages of 1–10 min, HR/SpO2 sensor disconnections of 1–5 min |

Assumptions and references (ranges are *plausible adult values*, deliberately broad; they are simulator parameters, not clinical findings):
* resting adult heart rate 60–100 bpm and normal SpO2 ≥ 95 % are standard textbook ranges (e.g. American Heart Association public guidance on resting heart rate; WHO *Pulse Oximetry Training Manual*, 2011);
* fever commonly defined from ≈ 38.0 °C core temperature; heart rate rises roughly 8–10 bpm per °C of fever (Liebermeister's rule, classical clinical teaching);
* early-warning practice of scoring HR, SpO2 and temperature bands follows the idea of NEWS2 (Royal College of Physicians, 2017) — only the *idea* of thresholds on these vitals is borrowed, not the score.
The alert thresholds themselves (120 bpm, 92 %, 38.0 °C) come from the project's cahier des charges and are engineering demonstration values.

## 3. Features (`gateway/features.py`, version `f2`, 38 features)

One implementation serves training and live inference (no train/serve skew). Per signal (HR, SpO2, temperature): latest value, 10-min mean / std / min / max, 10-min and 3-min least-squares slope (per minute), change versus the patient's own level 10–15 min ago (short patient-specific baseline), share of missing samples. Plus: median of the last 3 HR / SpO2 samples (artifact-robust level), margin to each threshold, minutes to each threshold at the current trend (capped at 60), number of samples, gap since the previous sample, fall flag in the last 5 min.

Leakage controls: features use only samples with `ts ≤ t` (unit-tested: appending future samples does not change the vector); the dataset is split **by patient** (60 / 20 / 20, fixed seed), never by row; the test patients are listed in `metadata.json`.
A prediction needs at least 6 valid HR and SpO2 samples in the last 10 minutes; otherwise the service answers `insufficient_data`.

## 4. Models compared (same data, same protocol)

Logistic regression (median imputation + standardisation), random forest (200 trees), histogram gradient boosting (native missing values) — and two non-deployable baselines for context: isolation forest (unsupervised anomaly score) and a no-learning trend rule (linear extrapolation to the threshold). A sequence neural network (LSTM, as sketched in the pre-MVP report) was **not** used: the tabular features already encode the trend, the dataset is synthetic, the gain would be unprovable, and it would add TensorFlow to the Pi. The untested legacy scripts `ml/train_model.py` / `ml/evaluate_model.py` are kept for reference only.

Protocol: fit on train → decision threshold = maximum F2 on validation (recall weighted over precision) → isotonic calibration fitted on validation → **all reported numbers computed on the held-out test set** → model chosen by validation PR-AUC (ties within 0.01 go to the faster model). The test set is never used for a decision.

Metrics written to `metrics.json`: accuracy, precision, recall/sensitivity, specificity, F1, F2, FPR, FNR, confusion matrix, ROC-AUC, PR-AUC, Brier score and expected calibration error (raw and calibrated), plus an **episode-level** view (share of threshold-crossing episodes warned in advance, lead time, false-alarm episodes per patient-day), fit time and single-inference latency.

## 5. Experiment log (real runs, nothing edited)

| Run | Change | Selected model | Test PR-AUC | Test recall | Test precision |
|---|---|---|---|---|---|
| 1 | first definition: any single-sample breach counts; 240 patients; 36 features | logistic regression | 0.458 | 0.542 | 0.380 |
| 2 (current) | label = *sustained* breach (2 consecutive samples); +2 robust median features; 600 patients | gradient boosting | see `MODEL_EVALUATION.md` | | |

Run 1 was poor for an identifiable reason: about 40 % of its positive rows preceded isolated motion-artifact spikes, which carry no precursor. Predicting artifacts is neither possible nor useful, so the target was redefined (and documented) rather than the result hidden. Remaining errors are dominated by abrupt events and by values hovering just under a limit.

## 6. Commands

```bash
# Windows:  .\.venv\Scripts\python.exe ...      Linux/WSL/Pi:  python ...
python ml/generate_dataset.py                      # -> ml/data/synth-v2/ (git-ignored, reproducible)
python ml/generate_dataset.py --patients 300 --seed 7 --version synth-v3
python ml/train.py                                 # features, 5 models, evaluation, save + activate, regenerate MODEL_EVALUATION.md
python ml/train.py --dataset ml/data/synth-v3 --version ew-exp1 --no-activate --no-report
```
Runtime on the development PC: ≈ 20 s generation, ≈ 75 s features, ≈ 2 min training/evaluation.

Artifacts per version in `ml/models/<version>/`: `model.joblib` (pipeline, calibrator, thresholds, training medians), `metadata.json` (target, features, parameters, dataset version/seed/hash, split, dependencies, artifact SHA-256), `metrics.json`, `curves.json`. `ml/models/active.json` names the active and previous version.

## 7. Live inference (`gateway/inference.py`)

For each stored measurement: last 15 min of the patient's history → features → `predict_proba` → risk category (`high` ≥ decision threshold, `medium` ≥ validation threshold with ≥ 80 % recall, else `low`) → stored with model version, score, calibrated estimate, explanation, supporting values, latency → live event → predictive alert when `high` and no threshold condition is currently present.

* **Explanation**: for every feature the score is recomputed with that feature replaced by its training median (one batched call); the five largest differences are reported with direction ("raises / lowers risk"). It is a local sensitivity explanation, model-agnostic.
* **Score vs probability**: the UI shows the risk category and the raw score; the isotonic-calibrated value is labelled "estimated probability" and is calibrated on synthetic data only.
* **Failure modes**: no model / checksum mismatch / feature mismatch → `model_unavailable`; exception → `inference_error`; in both cases ingestion and threshold alerts continue.
* **Human in the loop**: a predictive alert is a *warning* for staff to look at the patient; it triggers no automatic action and can be marked false positive (doctor).

## 8. Deployment to the Raspberry Pi, update, rollback

The Pi only runs inference. Train on the PC, then copy the version folder:

```bash
scp -r ml/models/ew-20261114 pi@<pi>:~/remote-patient-monitoring/ml/models/
```
Activate from the dashboard (AI intelligence → Versions → Activate, administrator) or with `POST /api/v1/ml/deploy {"version": "..."}`. The artifact checksum and feature definition are verified **before** switching; a failed activation leaves the current model in place. Rollback: "Roll back to previous version" (`{"rollback": true}`).

Compatibility: a joblib artifact must be loaded with the scikit-learn version that produced it (`metadata.json → dependencies`). Install the same version on the Pi (`pip install scikit-learn==<version>`); the AI page shows a warning when versions differ. If the Pi's Python cannot install that version, re-run `python ml/train.py` on the Pi (≈ 15–25 min expected on a Pi 5, not measured) or in a matching environment.

CPU, memory and inference latency are visible in Administration → System health and AI intelligence (p50 / p95 over the last 500 predictions).

## 9. Drift, retraining, limits

* No real data ⇒ no real drift measurement yet. The prediction history stores scores and categories; the share of `high` predictions and the false-positive reviews by doctors are the signals to watch.
* Retraining is manual and offline by design (a model change must be a reviewed, versioned event).
* Before any clinical use: collect real, consented, representative data; re-define and re-validate the target with clinicians; re-evaluate calibration and false-alarm burden prospectively.
