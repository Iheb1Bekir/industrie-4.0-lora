import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("g++") is None, reason="g++ not installed")


def test_patient_reading_json_contract(tmp_path):
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
    readings = [json.loads(line) for line in output]

    assert len(readings) == 4
    expected_keys = {
        "patient_id",
        "timestamp",
        "heart_rate",
        "spo2",
        "temperature",
        "fall_detected",
    }
    for reading in readings:
        assert set(reading) == expected_keys
        assert isinstance(reading["patient_id"], str)
        assert isinstance(reading["timestamp"], str)
        assert type(reading["heart_rate"]) is int
        assert type(reading["spo2"]) in (int, float)
        assert type(reading["temperature"]) in (int, float)
        assert type(reading["fall_detected"]) is bool

    assert readings[0] == {
        "patient_id": "PATIENT_01",
        "timestamp": "2026-10-19T19:58:00Z",
        "heart_rate": 78,
        "spo2": 98,
        "temperature": 36.7,
        "fall_detected": False,
    }
    assert readings[1]["fall_detected"] is True
    assert readings[2]["patient_id"] == 'PATIENT_"\\\n\x01'
    assert readings[2]["timestamp"] == "UPTIME+\t3s"
    assert readings[2]["spo2"] == 97.5
    assert readings[3]["patient_id"] == "PATIENT_01"
    assert readings[3]["heart_rate"] == 80
    assert readings[3]["temperature"] == 36.8
