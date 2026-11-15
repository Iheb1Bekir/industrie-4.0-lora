"""Protocol v2: Python reference, C++ firmware header equivalence, relay behaviour, v1 backward compatibility."""
import hashlib
import hmac
import shutil
import subprocess
from pathlib import Path

import pytest

from gateway import protocol as P, telemetry as V1

ROOT = Path(__file__).resolve().parent.parent
KEY = bytes(range(32))
M = {"patientId": 7, "sourceId": 107, "destinationId": 1, "seqNo": 4242, "timestamp": 1_800_000_000, "heartRate": 88, "spO2": 96,
     "temperature": 37.25, "fallDetected": True, "alertLevel": 3, "routingMode": 1, "hopCount": 0, "maxHopCount": 4, "payloadType": 3,
     "critical": True, "flags": P.F_TIME_SYNCED, "battery": 81}


def test_roundtrip_preserves_every_field_of_the_data_structure():
    raw = P.encode(M, KEY)
    assert len(raw) == 34
    d = P.decode(raw, KEY)
    for k in ("patientId", "seqNo", "timestamp", "heartRate", "spO2", "temperature", "fallDetected", "alertLevel", "routingMode",
              "sourceId", "destinationId", "hopCount", "maxHopCount", "payloadType", "critical", "battery"):
        assert d[k] == M[k], k
    assert d["timeSynced"] is True


def test_sensor_faults_are_none_not_zero():
    d = P.decode(P.encode(dict(M, heartRate=None, spO2=None, temperature=None, battery=None), KEY), KEY)
    assert d["heartRate"] is None and d["spO2"] is None and d["temperature"] is None and d["battery"] is None
    assert d["flags"] & P.F_HRSPO2_FAULT and d["flags"] & P.F_TEMP_FAULT


def test_wrong_key_and_tampering_are_rejected():
    raw = P.encode(M, KEY)
    with pytest.raises(P.AuthError):
        P.decode(raw, bytes(32))
    bad = bytearray(raw)
    bad[16] ^= 0x10                                            # change heartRate, then fix the CRC like an attacker would
    bad[32:] = P.crc16(bytes(bad[:32])).to_bytes(2, "big")
    with pytest.raises(P.AuthError):
        P.decode(bytes(bad), KEY)
    flip = bytearray(raw)
    flip[5] ^= 1
    with pytest.raises(P.CrcError):
        P.decode(bytes(flip), KEY)
    with pytest.raises(P.FrameError):
        P.decode(raw[:-1], KEY)
    v9 = bytearray(raw)
    v9[0] = 9
    with pytest.raises(P.FrameError):
        P.decode(bytes(v9), KEY)


@pytest.mark.parametrize("field,value", [("patientId", 0), ("seqNo", 0), ("alertLevel", 4), ("hopCount", 16), ("payloadType", 9), ("sourceId", 70000)])
def test_encode_rejects_out_of_range(field, value):
    with pytest.raises(P.FrameError):
        P.encode(dict(M, **{field: value}), KEY)


def test_relay_increments_hop_keeps_tag_valid_and_enforces_limit():
    raw = P.encode(M, KEY)
    r1 = P.relay_forward(raw)
    assert P.decode(r1, KEY)["hopCount"] == 1 and r1[24:32] == raw[24:32]      # tag untouched, still authentic
    r = raw
    for _ in range(4):
        r = P.relay_forward(r)
    assert P.decode(r, KEY)["hopCount"] == 4
    with pytest.raises(P.FrameError):
        P.relay_forward(r)                                                     # hop limit (maxHopCount = 4)
    with pytest.raises(P.FrameError):
        P.relay_forward(raw, relay_max_hop=0)
    assert P.dedup_key(r) == (7, 4242) == P.dedup_key(raw)                     # (patientId, seqNo) identity survives relaying
    corrupted = bytearray(raw)
    corrupted[10] ^= 0xFF
    with pytest.raises(P.CrcError):
        P.relay_forward(bytes(corrupted))


def test_relay_cannot_change_routing_mode():
    raw = bytearray(P.relay_forward(P.encode(M, KEY)))
    raw[21] &= 0x0F                                                            # a relay tries to rewrite routingMode
    raw[32:] = P.crc16(bytes(raw[:32])).to_bytes(2, "big")
    with pytest.raises(P.AuthError):
        P.decode(bytes(raw), KEY)


def test_v1_packets_still_parse():
    raw = V1.encode(V1.Telemetry("P012", 5, 80, 97, 36.6, V1.F_FALL | V1.F_SYNTH, 300))
    d = P.from_v1(raw)
    assert d["patientId"] == 12 and d["seqNo"] == 5 and d["fallDetected"] and d["heartRate"] == 80
    assert d["protocolVersion"] == 1 and d["sourceId"] is None


def test_firmware_header_copies_are_identical():
    a = (ROOT / "firmware/patient_node_lora/rpm_protocol_v2.h").read_bytes()
    assert a == (ROOT / "firmware/relay_node/rpm_protocol_v2.h").read_bytes()
    assert (ROOT / "firmware/patient_node_lora/config.h").read_bytes() == (ROOT / "firmware/relay_node/config.h").read_bytes()
    assert (ROOT / "firmware/patient_node_lora/fall_detector.h").read_bytes() == (ROOT / "wokwi/patient_node/fall_detector.h").read_bytes()


def test_firmware_config_has_no_default_frequency_or_radio():
    active = [ln for ln in (ROOT / "firmware/patient_node_lora/config.h").read_text().splitlines() if ln.strip().startswith("#define")]
    assert not any("RPM_LORA_FREQUENCY_MHZ" in ln or "RPM_RADIO_SX" in ln for ln in active)


@pytest.mark.skipif(not shutil.which("g++"), reason="g++ not installed")
def test_cpp_firmware_encoder_matches_python(tmp_path):
    raw = P.encode(M, KEY)
    hdr = raw[:24]
    immutable = hdr[:22] + bytes([hdr[22] & 0x0F]) + hdr[23:24]
    tag = hmac.new(KEY, immutable, hashlib.sha256).digest()
    exe = tmp_path / "t"
    subprocess.run(["g++", "-std=c++11", "-Wall", "-Werror", f"-I{ROOT / 'firmware/patient_node_lora'}",
                    str(ROOT / "tests/firmware_host/protocol_v2.cpp"), "-o", str(exe)], check=True)
    out = subprocess.run([str(exe), tag.hex()], capture_output=True, text=True, check=True).stdout.split("\n")
    assert out[0] == immutable.hex().upper()                 # firmware authenticates exactly the bytes Python verifies
    assert out[1] == raw.hex().upper()                       # byte-identical frame
    assert out[2] == "1"
    assert out[3] == P.relay_forward(raw).hex().upper()      # relay step identical
    assert out[4] == "1 0" and out[5] == "1 0" and out[6] == "0"
    assert out[7] == f"{P.F_HRSPO2_FAULT | P.F_TEMP_FAULT} 0 -32768"
