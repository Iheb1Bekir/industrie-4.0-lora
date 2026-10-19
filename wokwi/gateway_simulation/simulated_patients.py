"""Deterministic synthetic telemetry generator. Uses the SAME packet encoder as the gateway and the same
scenario values as the Wokwi firmware (patient_node.ino). All output is flagged SYNTHETIC - not a measurement."""
import itertools
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from gateway import telemetry as T  # noqa: E402

SCENARIOS = ("NORMAL", "LOW_SPO2", "HIGH_HR", "HIGH_TEMP", "FALL", "SENSOR_ERROR")


def values(scenario, n):
    """(hr, spo2, temp, flags) for the n-th sample of a scenario."""
    j = (n * 7) % 5 - 2      # small deterministic wobble -2..2
    hr, spo2, temp, fl = 72 + j, 97 + (1 if j > 0 else 0), 36.6 + 0.1 * (j % 3), T.F_SYNTH
    if scenario == "LOW_SPO2": spo2, hr = 89 - (n % 2), 88
    elif scenario == "HIGH_HR": hr = 132 + j
    elif scenario == "HIGH_TEMP": temp = 38.9
    elif scenario == "FALL": fl |= T.F_FALL; hr = 95
    elif scenario == "SENSOR_ERROR": fl |= T.F_HRSPO2_FAULT | T.F_TEMP_FAULT
    elif scenario != "NORMAL": raise ValueError(f"unknown scenario {scenario}")
    return hr, spo2, round(temp, 2), fl


def packets(pid="P001", scenario="NORMAL", count=5, start_seq=0, interval_s=60, start_uptime=60):
    for i in range(count):
        hr, spo2, temp, fl = values(scenario, i)
        yield T.encode(T.Telemetry(pid, (start_seq + i) & 0xFFFF, hr, spo2, temp, fl, start_uptime + i * interval_s))


def lines(pid, scenario, count, **kw):
    """Serial-style lines identical in format to what the firmware prints."""
    for p in packets(pid, scenario, count, **kw):
        yield f"LORA_TX_SIM seq={int.from_bytes(p[3:5], 'big')} hex={p.hex().upper()}"
