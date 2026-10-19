import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("g++") is None, reason="g++ not installed")


def test_patient_reading_output_profiles_and_sampling(tmp_path):
    executable = tmp_path / "patient_reading"
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-Wall",
            f"-I{ROOT / 'wokwi/patient_node'}",
            str(ROOT / "tests/firmware_host/patient_reading.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    output = subprocess.run(
        [str(executable)], capture_output=True, text=True, check=True
    ).stdout.splitlines()

    readings = [json.loads(line) for line in output[:4]]
    expected_keys = {
        "patient_id",
        "timestamp_ms",
        "heart_rate_bpm",
        "heart_rate_source",
        "spo2_percent",
        "spo2_source",
        "temperature_c",
        "temperature_source",
        "fall_detected",
        "fall_status",
        "fall_source",
    }
    for reading in readings:
        assert set(reading) == expected_keys
        assert type(reading["patient_id"]) is int
        assert type(reading["timestamp_ms"]) is int
        assert type(reading["heart_rate_bpm"]) is int
        assert type(reading["spo2_percent"]) in (int, float)
        assert type(reading["fall_detected"]) is bool
        assert reading["fall_status"] == ("YES" if reading["fall_detected"] else "NO")

    assert readings[0]["patient_id"] == 1
    assert readings[0]["timestamp_ms"] == 5000
    assert readings[0]["heart_rate_bpm"] == 78
    assert readings[0]["spo2_percent"] == 98
    assert readings[0]["temperature_c"] == 36.7
    assert readings[0]["heart_rate_source"] == "SIMULATED\nPROFILE"
    assert readings[0]["temperature_source"] == "DS18B20_SENSOR"
    assert readings[1]["heart_rate_bpm"] == 105
    assert readings[1]["spo2_percent"] == 94
    assert readings[1]["fall_detected"] is True
    assert readings[1]["fall_source"] == "SERIAL_COMMAND_SIMULATED"
    assert readings[2]["heart_rate_bpm"] == 135
    assert readings[2]["spo2_percent"] == 88
    assert readings[2]["temperature_c"] == 38.9
    assert readings[3]["temperature_c"] is None
    assert readings[3]["temperature_source"] == "UNAVAILABLE_SENSOR"
    assert readings[3]["fall_source"] == "UNAVAILABLE_ACCELEROMETER"

    profiles = [line.split() for line in output[4:]]
    assert profiles == [
        ["PROFILE", "0", "78", "98.0", "36.6"],
        ["PROFILE", "1", "105", "94.0", "37.5"],
        ["PROFILE", "2", "135", "88.0", "38.9"],
    ]
