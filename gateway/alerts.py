"""Central rule-based alert engine. Thresholds are PROTOTYPE defaults, not clinically validated."""
from . import telemetry as T

SEV = {"LOW_SPO2": "high", "HIGH_HR": "high", "LOW_HR": "high", "HIGH_TEMP": "medium", "LOW_TEMP": "medium",
       "FALL": "critical", "SENSOR_ERROR": "medium", "STALE_DATA": "medium"}


def evaluate(r: dict, cfg) -> list:
    """r: reading dict (hr/spo2/temp may be None). Returns [(kind, severity, message)]."""
    out = []
    hr, spo2, temp = r.get("hr"), r.get("spo2"), r.get("temp")
    if spo2 is not None and spo2 < cfg.SPO2_LOW:
        out.append(("LOW_SPO2", f"SpO2 {spo2}% < {cfg.SPO2_LOW:g}%"))
    if hr is not None and hr > cfg.HR_HIGH:
        out.append(("HIGH_HR", f"Heart rate {hr} bpm > {cfg.HR_HIGH:g}"))
    if hr is not None and hr < cfg.HR_LOW:
        out.append(("LOW_HR", f"Heart rate {hr} bpm < {cfg.HR_LOW:g}"))
    if temp is not None and temp >= cfg.TEMP_HIGH:
        out.append(("HIGH_TEMP", f"Temperature {temp:.1f} C >= {cfg.TEMP_HIGH:g}"))
    if temp is not None and temp < cfg.TEMP_LOW:
        out.append(("LOW_TEMP", f"Temperature {temp:.1f} C < {cfg.TEMP_LOW:g}"))
    if r.get("fall"):
        out.append(("FALL", "Possible fall detected"))
    fl = int(r.get("flags") or 0)
    faults = [n for b, n in ((T.F_HRSPO2_FAULT, "HR/SpO2"), (T.F_TEMP_FAULT, "temperature"), (T.F_IMU_FAULT, "IMU")) if fl & b]
    if faults:
        out.append(("SENSOR_ERROR", "Sensor fault: " + ", ".join(faults)))
    return [(k, SEV[k], m) for k, m in out]
