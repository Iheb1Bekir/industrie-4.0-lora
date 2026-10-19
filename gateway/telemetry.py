"""Compact 16-byte radio payload (version 1). Big-endian.

off len type  field        unit / scaling / valid range
 0   1  u8    version      must be 1
 1   2  u16   pid_num      1..999 -> patient id "P%03d"
 3   2  u16   seq          wraps at 65536
 5   1  u8    hr           bpm, valid 20..250 (0 only with HR_SPO2_FAULT)
 6   1  u8    spo2         %,   valid 50..100 (0 only with HR_SPO2_FAULT)
 7   2  i16   temp_x100    0.01 degC, valid 2000..4500 (-32768 only with TEMP_FAULT)
 9   1  u8    flags        b0 FALL, b1 SYNTHETIC, b2 HR_SPO2_FAULT, b3 TEMP_FAULT, b4 IMU_FAULT, b5-7 reserved (0)
10   4  u32   uptime_s     node uptime seconds (node has no RTC)
14   2  u16   crc16        CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over bytes 0..13
"""
import re
import struct
from dataclasses import dataclass
from typing import Optional

VERSION = 1
PACKET_LEN = 16
F_FALL, F_SYNTH, F_HRSPO2_FAULT, F_TEMP_FAULT, F_IMU_FAULT = 1, 2, 4, 8, 16
RESERVED_MASK = 0xE0
TEMP_INVALID = -32768
_FMT = ">BHHBBhBI"  # 14 bytes, then CRC16
PID_RE = re.compile(r"^P\d{3}$")


class PacketError(ValueError):
    code = "E_PACKET"


class TruncatedPacket(PacketError):
    code = "E_TRUNCATED"


class CrcError(PacketError):
    code = "E_CRC"


class UnsupportedVersion(PacketError):
    code = "E_VERSION"


class FieldRange(PacketError):
    code = "E_RANGE"


@dataclass
class Telemetry:
    pid: str
    seq: int
    hr: Optional[int]
    spo2: Optional[int]
    temp: Optional[float]
    flags: int
    uptime_s: int

    @property
    def fall(self): return int(bool(self.flags & F_FALL))

    @property
    def synthetic(self): return bool(self.flags & F_SYNTH)


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def pid_to_num(pid) -> int:
    if not isinstance(pid, str) or not PID_RE.match(pid) or int(pid[1:]) == 0:
        raise FieldRange(f"invalid patient id {pid!r} (expected P001..P999)")
    return int(pid[1:])


def encode(t: Telemetry) -> bytes:
    pnum = pid_to_num(t.pid)
    if not 0 <= t.seq <= 0xFFFF: raise FieldRange("seq out of range")
    if not 0 <= t.uptime_s <= 0xFFFFFFFF: raise FieldRange("uptime out of range")
    if not 0 <= t.flags <= 255 or t.flags & RESERVED_MASK: raise FieldRange("reserved flag bits set")
    if t.flags & F_HRSPO2_FAULT:
        hr = spo2 = 0
    else:
        if t.hr is None or not 20 <= t.hr <= 250: raise FieldRange("hr out of range 20..250")
        if t.spo2 is None or not 50 <= t.spo2 <= 100: raise FieldRange("spo2 out of range 50..100")
        hr, spo2 = int(t.hr), int(t.spo2)
    if t.flags & F_TEMP_FAULT:
        temp = TEMP_INVALID
    else:
        if t.temp is None or not 20.0 <= t.temp <= 45.0: raise FieldRange("temp out of range 20..45")
        temp = int(round(t.temp * 100))
    body = struct.pack(_FMT, VERSION, pnum, t.seq, hr, spo2, temp, t.flags, t.uptime_s)
    return body + struct.pack(">H", crc16(body))


def decode(raw: bytes) -> Telemetry:
    if len(raw) < PACKET_LEN: raise TruncatedPacket(f"{len(raw)} bytes, need {PACKET_LEN}")
    if len(raw) > PACKET_LEN: raise PacketError(f"{len(raw)} bytes, expected {PACKET_LEN}")
    if crc16(raw[:14]) != struct.unpack(">H", raw[14:])[0]: raise CrcError("CRC mismatch")
    ver, pnum, seq, hr, spo2, temp, flags, up = struct.unpack(_FMT, raw[:14])
    if ver != VERSION: raise UnsupportedVersion(f"version {ver}")
    if not 1 <= pnum <= 999: raise FieldRange("patient number out of range")
    if flags & RESERVED_MASK: raise FieldRange("reserved flag bits set")
    if flags & F_HRSPO2_FAULT:
        if hr or spo2: raise FieldRange("hr/spo2 must be 0 when faulted")
        hr_v = spo2_v = None
    else:
        if not 20 <= hr <= 250: raise FieldRange("hr out of range")
        if not 50 <= spo2 <= 100: raise FieldRange("spo2 out of range")
        hr_v, spo2_v = hr, spo2
    if flags & F_TEMP_FAULT:
        if temp != TEMP_INVALID: raise FieldRange("temp must be sentinel when faulted")
        temp_v = None
    else:
        if not 2000 <= temp <= 4500: raise FieldRange("temp out of range")
        temp_v = temp / 100.0
    return Telemetry(f"P{pnum:03d}", seq, hr_v, spo2_v, temp_v, flags, up)


def to_api_payload(t: Telemetry, ts: int, source: str) -> dict:
    return {"pid": t.pid, "hr": t.hr, "spo2": t.spo2, "temp": t.temp, "fall": t.fall, "ts": ts,
            "seq": t.seq, "uptime": t.uptime_s, "flags": t.flags, "synthetic": t.synthetic, "source": source}
