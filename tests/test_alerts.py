import pytest
from gateway import alerts as A, telemetry as T
from gateway.config import Config

cfg = Config()


def kinds(**r):
    base = dict(hr=75, spo2=97, temp=36.7, fall=0, flags=0); base.update(r)
    return [k for k, _, _ in A.evaluate(base, cfg)]


def test_normal_has_no_alerts(): assert kinds() == []


@pytest.mark.parametrize("kw,kind", [(dict(spo2=91), "LOW_SPO2"), (dict(hr=121), "HIGH_HR"), (dict(hr=39), "LOW_HR"),
                                     (dict(temp=38.0), "HIGH_TEMP"), (dict(temp=34.9), "LOW_TEMP"), (dict(fall=1), "FALL"),
                                     (dict(hr=None, spo2=None, flags=T.F_HRSPO2_FAULT), "SENSOR_ERROR"),
                                     (dict(temp=None, flags=T.F_TEMP_FAULT), "SENSOR_ERROR"), (dict(flags=T.F_IMU_FAULT), "SENSOR_ERROR")])
def test_each_abnormal_scenario(kw, kind): assert kind in kinds(**kw)


def test_boundaries_do_not_alert():
    assert kinds(spo2=92, hr=120, temp=37.9) == []


def test_severities():
    s = {k: v for k, v, _ in A.evaluate(dict(hr=75, spo2=90, temp=36.7, fall=1, flags=0), cfg)}
    assert s["FALL"] == "critical" and s["LOW_SPO2"] == "high"


def test_sensor_error_does_not_raise_value_alerts_on_null():
    assert kinds(hr=None, spo2=None, temp=None, flags=T.F_HRSPO2_FAULT | T.F_TEMP_FAULT) == ["SENSOR_ERROR"]
