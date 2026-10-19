# ML
* `evaluate_model.py readings.csv` — chronological 80/20 MAPE of the linear-regression fallback vs. report targets (HR ≤ 8 %, SpO2 ≤ 5 %). Runs without TensorFlow.
* `train_model.py readings.csv` — LSTM → TFLite (needs TensorFlow, ≥1000 windows, refuses synthetic rows by default). **Untested: no dataset/TensorFlow here.** Output `ml/artifacts/lstm.tflite` + `.json` (mean/std); then `POST /api/model/retrain {"action":"reload"}` or restart. The loader is also untested against a real artifact.
Only real patient data can validate the targets. Results on synthetic data are code checks only.
