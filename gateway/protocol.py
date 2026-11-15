"""RPM raw-LoRa application protocol, version 2 (34-byte frame, big-endian).

This is a CUSTOM raw-LoRa protocol with application-level relaying. It is NOT LoRaWAN.
It carries exactly the measurement structure of the OMNeT++/FLoRa model (RPMMeasurement.msg) plus
`payloadType`, a device identity and an authentication tag. Version 1 (16 bytes, gateway/telemetry.py)
is still decodable for backward compatibility (see `from_v1`). Full specification: docs/PROTOCOL_SPECIFICATION.md.

off len type field          notes
 0   1  u8   version        2
 1   1  u8   payloadType    1 MEASUREMENT, 2 HEARTBEAT, 3 ALERT (event-triggered measurement)
 2   2  u16  patientId      1..65535
 4   2  u16  sourceId       originating device id (1..65535)
 6   2  u16  destinationId  doctor gateway id
 8   4  u32  seqNo          strictly increasing per device, persisted across reboots (replay protection)
12   4  u32  timestamp      device clock: UTC epoch s if F_TIME_SYNCED else uptime s
16   1  u8   heartRate      bpm, 0 when F_HRSPO2_FAULT
17   1  u8   spO2           %,   0 when F_HRSPO2_FAULT
18   2  i16  temperature    0.01 degC, -32768 when F_TEMP_FAULT
20   1  u8   flags          b0 fallDetected, b1 synthetic, b2 HR/SpO2 fault, b3 temp fault, b4 IMU fault,
                            b5 critical, b6 time synced, b7 reserved (0)
21   1  u8   alertLevel (low nibble 0..3) | routingMode (high nibble: 0 direct, 1 relay-assisted)
22   1  u8   maxHopCount (low nibble) | hopCount (high nibble)      <- hopCount is the ONLY relay-mutable field
23   1  u8   battery        0..100 %, 255 = not supported by hardware
24   8  --   tag            HMAC-SHA256(deviceKey, bytes 0..23 with hopCount nibble = 0)[0:8]
32   2  u16  crc16          CRC-16/CCITT-FALSE over bytes 0..31 (recomputed by each relay)
"""
import hashlib
import hmac
import struct

from . import telemetry as V1

VERSION = 2
FRAME_LEN = 34
HDR_LEN = 24
TAG_LEN = 8
PT_MEASUREMENT, PT_HEARTBEAT, PT_ALERT = 1, 2, 3
PAYLOAD_TYPES = {PT_MEASUREMENT: "MEASUREMENT", PT_HEARTBEAT: "HEARTBEAT", PT_ALERT: "ALERT"}
F_FALL, F_SYNTH, F_HRSPO2_FAULT, F_TEMP_FAULT, F_IMU_FAULT, F_CRITICAL, F_TIME_SYNCED = 1, 2, 4, 8, 16, 32, 64
F_RESERVED = 0x80
TEMP_INVALID = -32768
BATTERY_UNSUPPORTED = 255
ROUTE_DIRECT, ROUTE_RELAY = 0, 1
_HDR = ">BBHHHIIBBhBBBB"
assert struct.calcsize(_HDR) == HDR_LEN

crc16 = V1.crc16


class FrameError(ValueError):
    code = "malformed"


class CrcError(FrameError):
    code = "crc_error"


class AuthError(FrameError):
    code = "auth_fail"


def _tag(key: bytes, hdr: bytes) -> bytes:
    immutable = hdr[:22] + bytes([hdr[22] & 0x0F]) + hdr[23:24]
    return hmac.new(key, immutable, hashlib.sha256).digest()[:TAG_LEN]


def encode(m: dict, key: bytes) -> bytes:
    """Build a frame from a measurement dict (camelCase field names of the data structure)."""
    flags = int(m.get("flags", 0)) & ~(F_FALL | F_CRITICAL)
    if m.get("fallDetected"): flags |= F_FALL
    if m.get("critical"): flags |= F_CRITICAL
    hr, spo2, temp = m.get("heartRate"), m.get("spO2"), m.get("temperature")
    if hr is None or spo2 is None: flags |= F_HRSPO2_FAULT
    if temp is None: flags |= F_TEMP_FAULT
    hr_b = 0 if flags & F_HRSPO2_FAULT else int(round(hr))
    sp_b = 0 if flags & F_HRSPO2_FAULT else int(round(spo2))
    t_b = TEMP_INVALID if flags & F_TEMP_FAULT else int(round(temp * 100))
    for name, v, lo, hi in (("patientId", m["patientId"], 1, 0xFFFF), ("sourceId", m["sourceId"], 1, 0xFFFF),
                            ("destinationId", m["destinationId"], 1, 0xFFFF), ("seqNo", m["seqNo"], 1, 0xFFFFFFFF),
                            ("timestamp", m["timestamp"], 0, 0xFFFFFFFF), ("heartRate", hr_b, 0, 255),
                            ("spO2", sp_b, 0, 255), ("temperature", t_b, -32768, 32767),
                            ("alertLevel", m.get("alertLevel", 0), 0, 3), ("routingMode", m.get("routingMode", 0), 0, 1),
                            ("hopCount", m.get("hopCount", 0), 0, 15), ("maxHopCount", m.get("maxHopCount", 4), 1, 15),
                            ("payloadType", m.get("payloadType", PT_MEASUREMENT), 1, 3)):
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise FrameError(f"{name} out of range")
    bat = m.get("battery")
    bat = BATTERY_UNSUPPORTED if bat is None else int(bat)
    hdr = struct.pack(_HDR, VERSION, m.get("payloadType", PT_MEASUREMENT), m["patientId"], m["sourceId"],
                      m["destinationId"], m["seqNo"], m["timestamp"], hr_b, sp_b, t_b, flags & 0x7F,
                      (m.get("alertLevel", 0) & 0x0F) | ((m.get("routingMode", 0) & 0x0F) << 4),
                      (m.get("maxHopCount", 4) & 0x0F) | ((m.get("hopCount", 0) & 0x0F) << 4), bat)
    body = hdr + _tag(key, hdr)
    return body + struct.pack(">H", crc16(body))


def check_frame(raw: bytes):
    """Structural + CRC check (what a relay can do without any key). Returns the header tuple."""
    if len(raw) != FRAME_LEN:
        raise FrameError(f"length {len(raw)}, expected {FRAME_LEN}")
    if raw[0] != VERSION:
        raise FrameError(f"unsupported version {raw[0]}")
    if crc16(raw[:32]) != struct.unpack(">H", raw[32:])[0]:
        raise CrcError("CRC mismatch")
    h = struct.unpack(_HDR, raw[:HDR_LEN])
    if h[1] not in PAYLOAD_TYPES:
        raise FrameError(f"invalid payloadType {h[1]}")
    if h[10] & F_RESERVED:
        raise FrameError("reserved flag bit set")
    if not h[2] or not h[3] or not h[4] or not h[5]:
        raise FrameError("zero identity field")
    return h


def peek_source(raw: bytes) -> int:
    """sourceId of a structurally valid frame (used to look up the device key before authentication)."""
    return check_frame(raw)[3]


def decode(raw: bytes, key: bytes) -> dict:
    """Verify CRC + authentication tag and return the measurement dict. Raises FrameError subclasses."""
    h = check_frame(raw)
    if not hmac.compare_digest(_tag(key, raw[:HDR_LEN]), raw[HDR_LEN:HDR_LEN + TAG_LEN]):
        raise AuthError("authentication tag mismatch")
    (_, ptype, pid, src, dst, seq, ts, hr, spo2, temp, flags, al_rm, hops, bat) = h
    hop, max_hop = hops >> 4, hops & 0x0F
    alert_level, routing_mode = al_rm & 0x0F, al_rm >> 4
    if alert_level > 3 or routing_mode > 1 or max_hop < 1:
        raise FrameError("invalid alertLevel/routingMode/maxHopCount")
    return {
        "patientId": pid, "seqNo": seq, "timestamp": ts,
        "heartRate": None if flags & F_HRSPO2_FAULT else float(hr),
        "spO2": None if flags & F_HRSPO2_FAULT else float(spo2),
        "temperature": None if flags & F_TEMP_FAULT else temp / 100.0,
        "fallDetected": bool(flags & F_FALL), "alertLevel": alert_level, "routingMode": routing_mode,
        "sourceId": src, "destinationId": dst, "hopCount": hop, "maxHopCount": max_hop,
        "payloadType": ptype, "critical": bool(flags & F_CRITICAL),
        "flags": flags, "battery": None if bat == BATTERY_UNSUPPORTED else min(bat, 100),
        "timeSynced": bool(flags & F_TIME_SYNCED), "protocolVersion": VERSION,
    }


def relay_forward(raw: bytes, relay_max_hop: int = 15) -> bytes:
    """Application-level relay step: validate, enforce the hop limit, increment hopCount, mark relay-assisted
    delivery is NOT changed (routingMode is authenticated and set by the source), recompute the CRC.
    Raises FrameError when the frame must be dropped."""
    h = check_frame(raw)
    hop, max_hop = h[12] >> 4, h[12] & 0x0F
    if hop >= min(max_hop, relay_max_hop):
        raise FrameError("hop limit reached")
    body = raw[:22] + bytes([((hop + 1) << 4) | max_hop]) + raw[23:32]
    return body + struct.pack(">H", crc16(body))


def dedup_key(raw: bytes):
    """(patientId, seqNo) identity used by relays and the gateway for duplicate detection."""
    h = check_frame(raw)
    return h[2], h[5]


def from_v1(raw: bytes) -> dict:
    """Backward-compatible parsing of the 16-byte v1 packet (no device id, no authentication)."""
    t = V1.decode(raw)
    return {
        "patientId": int(t.pid[1:]), "seqNo": t.seq, "timestamp": t.uptime_s,
        "heartRate": None if t.hr is None else float(t.hr), "spO2": None if t.spo2 is None else float(t.spo2),
        "temperature": t.temp, "fallDetected": bool(t.fall), "alertLevel": 3 if t.fall else 0, "routingMode": 0,
        "sourceId": None, "destinationId": None, "hopCount": 0, "maxHopCount": 1, "payloadType": PT_MEASUREMENT,
        "critical": bool(t.fall), "flags": t.flags & 0x1F, "battery": None, "timeSynced": False, "protocolVersion": 1,
    }
