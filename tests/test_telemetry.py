import struct
import pytest
from gateway import telemetry as T
from gateway.bridge import Gateway
from gateway.radio import SimulationTransport


def mk(**kw):
    d = dict(pid="P001", seq=0, hr=72, spo2=98, temp=36.70, flags=T.F_SYNTH, uptime_s=60)
    d.update(kw); return T.Telemetry(**d)


def test_packet_is_16_bytes_and_known_vector():
    raw = T.encode(mk())
    assert len(raw) == 16 and raw.hex().upper() == "010001000048620E56020000003CD9E7"


def test_roundtrip_normal_min_max():
    for t in (mk(), mk(pid="P999", seq=65535, hr=250, spo2=100, temp=45.0, flags=T.F_FALL | T.F_SYNTH, uptime_s=2**32 - 1),
              mk(hr=20, spo2=50, temp=20.0)):
        assert T.decode(T.encode(t)) == t


def test_fault_flags_use_null_values():
    t = T.decode(T.encode(mk(hr=None, spo2=None, temp=None, flags=T.F_HRSPO2_FAULT | T.F_TEMP_FAULT)))
    assert (t.hr, t.spo2, t.temp) == (None, None, None)


@pytest.mark.parametrize("kw", [dict(hr=19), dict(hr=251), dict(spo2=49), dict(spo2=101), dict(temp=19.9), dict(temp=45.1),
                                dict(pid="X001"), dict(pid="P000"), dict(pid="P1"), dict(seq=70000), dict(flags=0x40), dict(hr=None)])
def test_encode_rejects_invalid_fields(kw):
    with pytest.raises(T.PacketError): T.encode(mk(**kw))


def test_truncated_and_oversized():
    raw = T.encode(mk())
    for n in (0, 1, 15):
        with pytest.raises(T.TruncatedPacket): T.decode(raw[:n])
    with pytest.raises(T.PacketError): T.decode(raw + b"\x00")


def test_corrupted_crc_detected():
    raw = bytearray(T.encode(mk())); raw[5] ^= 0x01
    with pytest.raises(T.CrcError): T.decode(bytes(raw))


def _with_crc(body):
    return body + struct.pack(">H", T.crc16(body))


def test_unsupported_version():
    raw = bytearray(T.encode(mk())); raw[0] = 2
    with pytest.raises(T.UnsupportedVersion): T.decode(_with_crc(bytes(raw[:14])))


def test_valid_crc_but_invalid_field_rejected():
    body = bytearray(T.encode(mk())[:14]); body[5] = 5  # hr=5 without fault flag
    with pytest.raises(T.FieldRange): T.decode(_with_crc(bytes(body)))


def test_gateway_duplicates_loss_and_errors():
    posted = []
    gw = Gateway(SimulationTransport([]), lambda p: (posted.append(p) or (201, {"stored": True})), clock=lambda: 1000)
    for seq in (0, 1, 1, 4):   # seq 1 duplicated, 2-3 lost
        assert gw.handle(T.encode(mk(seq=seq, uptime_s=60 + seq))) in ("forwarded", "duplicate")
    bad = bytearray(T.encode(mk(seq=9))); bad[6] ^= 1
    assert gw.handle(bytes(bad)) == "crc_error" and gw.handle(b"\x01\x02") == "malformed"
    s = gw.stats
    assert (s.forwarded, s.duplicates, s.lost_estimate, s.crc_errors, s.malformed) == (3, 1, 2, 1, 1)
    assert len(posted) == 3 and posted[0]["ts"] == 1000 and posted[0]["synthetic"] is True


def test_gateway_seq_wraparound_not_counted_as_loss():
    gw = Gateway(SimulationTransport([]), lambda p: (201, {}), clock=lambda: 1)
    gw.handle(T.encode(mk(seq=65535, uptime_s=1))); gw.handle(T.encode(mk(seq=0, uptime_s=2)))
    assert gw.stats.lost_estimate == 0
