"""Compiles the firmware's pure-C++ headers with g++ and checks byte-for-byte equality with the Python encoder.
Also syntax-checks patient_node.ino against minimal Arduino STUBS (a type check only - NOT a real Arduino build)."""
import shutil, subprocess
from pathlib import Path
import pytest
from gateway import telemetry as T

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not shutil.which("g++"), reason="g++ not installed")


def test_cpp_encoder_matches_python_and_fall_logic(tmp_path):
    exe = tmp_path / "vec"
    subprocess.run(["g++", "-std=c++17", "-Wall", f"-I{ROOT/'wokwi/patient_node'}", str(ROOT / "tests/firmware_host/vectors.cpp"), "-o", str(exe)], check=True)
    out = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.split()
    py = [T.encode(T.Telemetry("P001", 0, 72, 98, 36.70, T.F_SYNTH, 60)),
          T.encode(T.Telemetry("P999", 65535, 250, 100, 45.0, T.F_FALL | T.F_SYNTH, 2**32 - 1)),
          T.encode(T.Telemetry("P007", 12, None, None, 36.60, T.F_SYNTH | T.F_HRSPO2_FAULT, 120)),
          T.encode(T.Telemetry("P002", 1, 80, 97, None, T.F_SYNTH | T.F_TEMP_FAULT, 5))]
    assert out[:4] == [p.hex().upper() for p in py]
    assert out[4] == "FALL_OK=1"


def test_sketch_syntax_with_stubs():
    r = subprocess.run(["g++", "-std=c++17", "-fsyntax-only", "-Wall", f"-I{ROOT/'tests/firmware_host/stubs'}", f"-I{ROOT/'wokwi/patient_node'}",
                        "-include", "Arduino.h", "-x", "c++", str(ROOT / "wokwi/patient_node/patient_node.ino")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
