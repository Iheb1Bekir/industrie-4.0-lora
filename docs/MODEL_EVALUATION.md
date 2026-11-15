# Model evaluation

> **Generated file.** Written by `ml/train.py` from `ml/models/ew-20261114/metrics.json`. Do not edit numbers by hand; re-run the pipeline.
> All data is **synthetic**. These figures describe how well the model recovers patterns of the generator, **not clinical performance**.

* Model version: `ew-20261114` - selected model: **hist_gradient_boosting** - trained 2026-11-14T15:21:13Z
* Prediction target: A SUSTAINED threshold condition (HR > 120 bpm, SpO2 < 92 % or temperature >= 38.0 C on two consecutive samples) starts within the next 10 minutes, given the last 15 minutes of measurements; rows already in (or within 5 min after) a threshold condition are excluded.
* Dataset: `synth-v2` (seed 20261114, sha256 `f24252fd9d4c6ba7...`), split by patient 60/20/20 (split seed 12345)
* Patients train / validation / test: 360 / 120 / 120
* Samples (prediction rows) train / validation / test: 349341 / 120212 / 116861
* Positive rows train / validation / test: 5649 / 2133 / 1816
* Software: Python 3.13.5, scikit-learn 1.9.1, numpy 2.5.4
* Selection rule: highest validation PR-AUC among deployable models; within 0.01 the lowest inference latency wins
* Threshold policy: high = max F2 on validation; medium = validation threshold with recall >= 0.80

## Held-out test set - all models, same protocol

| Model | Deployable | Threshold | Accuracy | Precision | Recall (sensitivity) | Specificity | F1 | ROC-AUC | PR-AUC | FPR | FNR | Brier (cal.) | ECE (cal.) | Latency ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| logistic_regression | yes | 0.7985 | 0.9727 | 0.3070 | 0.6035 | 0.9785 | 0.4070 | 0.8921 | 0.4128 | 0.0215 | 0.3965 | 0.0114 | 0.0006 | 6.379 |
| random_forest | yes | 0.4388 | 0.9804 | 0.4200 | 0.6894 | 0.9850 | 0.5220 | 0.8974 | 0.5432 | 0.0150 | 0.3106 | 0.0097 | 0.0013 | 47.239 |
| **hist_gradient_boosting** | yes | 0.6448 | 0.9813 | 0.4334 | 0.6663 | 0.9862 | 0.5252 | 0.8861 | 0.5432 | 0.0138 | 0.3337 | 0.0095 | 0.0008 | 4.761 |
| isolation_forest | baseline | 0.6616 | 0.9695 | 0.2770 | 0.5986 | 0.9753 | 0.3787 | 0.8583 | 0.2586 | 0.0247 | 0.4014 | 0.0126 | 0.0020 | - |
| trend_rule_baseline | baseline | 0.8834 | 0.9647 | 0.2414 | 0.5947 | 0.9705 | 0.3435 | 0.8771 | 0.3717 | 0.0295 | 0.4053 | 0.0116 | 0.0021 | - |

Test prevalence of the positive class: 0.0155 (1816 of 116861 rows). Accuracy is dominated by the negative class; read precision / recall / PR-AUC.

## Selected model: hist_gradient_boosting

Confusion matrix (test, at the frozen validation threshold):

| | predicted negative | predicted positive |
|---|---|---|
| actual negative | TN = 113463 | FP = 1582 |
| actual positive | FN = 606 | TP = 1210 |

Episode-level view (test): 92 of 97 threshold-crossing episodes received at least one warning in the 10 minutes before onset (episode recall 0.9485); median lead time 510.0 s (25th percentile 360.0 s); 282 false-alarm episodes = 7.06 per patient-day.

Validation metrics of the selected model (used for threshold choice and model selection): PR-AUC 0.5765, ROC-AUC 0.9061, recall 0.7145, precision 0.4638.

## Top features (permutation importance on the test set)

| Feature | Meaning | Importance (drop in PR-AUC) |
|---|---|---|
| `hr_med3` | heart rate: median of the last 3 samples (artifact-robust level) | 0.0850 ± 0.0095 |
| `temp_delta_base` | temperature: change versus the patient's own level 10-15 min ago | 0.0820 ± 0.0036 |
| `hr_eta` | heart rate: minutes until the threshold at the current trend | 0.0566 ± 0.0020 |
| `spo2_slope10` | SpO2: 10-min trend (per minute) | 0.0527 ± 0.0034 |
| `hr_std` | heart rate: 10-min variability | 0.0521 ± 0.0123 |
| `hr_slope3` | heart rate: 3-min trend (per minute) | 0.0408 ± 0.0101 |
| `temp_max` | temperature: 10-min maximum | 0.0377 ± 0.0081 |
| `spo2_delta_base` | SpO2: change versus the patient's own level 10-15 min ago | 0.0374 ± 0.0099 |
| `temp_last` | temperature: latest value | 0.0355 ± 0.0021 |
| `hr_last` | heart rate: latest value | 0.0244 ± 0.0038 |

## Calibration (isotonic, test set)

| Mean predicted | Observed rate | Rows |
|---|---|---|
| 0.005 | 0.005 | 113869 |
| 0.139 | 0.117 | 711 |
| 0.264 | 0.228 | 530 |
| 0.366 | 0.320 | 181 |
| 0.432 | 0.432 | 720 |
| 0.530 | 0.627 | 118 |
| 0.656 | 0.689 | 132 |
| 0.741 | 0.780 | 519 |
| 0.825 | 0.960 | 25 |
| 0.964 | 1.000 | 56 |

## Honest reading of these results

* The label is produced by the same generator family as the inputs; real physiology is noisier and less regular. Expect lower performance on real data.
* Abrupt events (sudden desaturation, artifacts crossing a threshold) carry no advance trend; they account for most false negatives and cannot be predicted by any trend model.
* The score is shown in the dashboard as a risk category. The calibrated value is labelled an estimate, not a clinical probability.
* Before any clinical use the model must be re-trained and validated on real, representative, ethically approved data.
