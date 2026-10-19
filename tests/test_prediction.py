import json
import pytest
from gateway.config import Config
from gateway.prediction import PredictionService, risk_rule, TFLiteLSTM, ModelUnavailable
from conftest import T0

cfg = Config(MODEL_PATH="/nonexistent/model.tflite")


def rows(n=30, hr=lambda i: 75, spo2=lambda i: 97, temp=lambda i: 36.7, synth=False):
    return [dict(ts=T0 + i * 60, hr=hr(i), spo2=spo2(i), temp=temp(i), synthetic=synth) for i in range(n)]


def test_risk_high_precedence_over_medium():
    assert risk_rule({"spo2": [94], "hr": [130]}, cfg)[0] == "high"     # medium SpO2 + high HR -> high
    assert risk_rule({"spo2": [91], "hr": [105]}, cfg)[0] == "high"


def test_risk_medium_and_low_and_boundaries():
    assert risk_rule({"spo2": [94], "hr": [80]}, cfg)[0] == "medium"
    assert risk_rule({"spo2": [98], "hr": [101]}, cfg)[0] == "medium"
    assert risk_rule({"spo2": [92], "hr": [120]}, cfg)[0] == "medium"   # 92 / 120 are not strictly beyond the high limits
    assert risk_rule({"spo2": [95], "hr": [100]}, cfg)[0] == "low"
    assert risk_rule({"spo2": [97], "hr": [75]}, cfg)[0] == "low"
    assert risk_rule({}, cfg)[0] == "unknown"


def test_any_step_counts():
    assert risk_rule({"spo2": [96, 95, 91], "hr": [80, 80, 80]}, cfg)[0] == "high"


def test_missing_model_uses_labelled_fallback():
    svc = PredictionService(cfg)
    st = svc.status()
    assert st["model"] == "linear_regression_fallback" and not st["trained_artifact_loaded"] and st["validated"] is False
    out = svc.predict("P001", rows(), 15, T0)
    assert out["status"] == "regression_fallback" and out["model"] == "linear_regression_fallback"
    assert len(out["pred"]["hr"]) == 3 and out["risk"] == "low" and "Not clinically validated" in out["disclaimer"]


def test_falling_spo2_trend_gives_elevated_risk():
    out = PredictionService(cfg).predict("P001", rows(spo2=lambda i: 99 - i * 0.2), 15, T0)   # 99 -> 93.2, trending down
    assert out["risk"] in ("medium", "high") and out["pred"]["spo2"][-1] < out["pred"]["spo2"][0]


def test_rising_hr_high_risk():
    out = PredictionService(cfg).predict("P001", rows(hr=lambda i: 90 + i), 15, T0)   # 119 now, rising 1 bpm/min
    assert out["risk"] == "high" and "HR" in out["reason"]


def test_insufficient_history():
    svc = PredictionService(cfg)
    for n in (0, 3, 9):
        out = svc.predict("P001", rows(n), 15, T0)
        assert out["status"] == "insufficient_data" and out["pred"] is None and out["risk"] == "unknown"


def test_null_values_skipped_per_signal():
    r = rows(); [x.update(hr=None, spo2=None) for x in r]
    out = PredictionService(cfg).predict("P001", r, 15, T0)
    assert set(out["pred"]) == {"temp"}


def test_synthetic_input_is_flagged():
    assert PredictionService(cfg).predict("P001", rows(synth=True), 15, T0)["synthetic_input"] is True


def test_predictions_are_clipped_to_physiological_bounds():
    out = PredictionService(cfg).predict("P001", rows(spo2=lambda i: 99.5 + i * 0.5), 15, T0)
    assert max(out["pred"]["spo2"]) <= 100


def test_tflite_loader_missing_artifact_and_runtime(tmp_path):
    with pytest.raises(ModelUnavailable): TFLiteLSTM(str(tmp_path / "none.tflite"), 30)
    bad = tmp_path / "bad.tflite"; bad.write_bytes(b"not a model")
    with pytest.raises(ModelUnavailable): TFLiteLSTM(str(bad), 30)
