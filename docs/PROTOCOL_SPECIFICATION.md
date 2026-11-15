# RPM raw-LoRa protocol specification

**This is a custom raw-LoRa protocol with application-level relaying. It is not LoRaWAN** (no network server, no join procedure, no LoRaWAN MAC; sync word `0x12`). Reference implementation: `gateway/protocol.py`; firmware: `firmware/*/rpm_protocol_v2.h` (byte-for-byte cross-checked by `tests/test_protocol_v2.py`).

## Versions

| Version | Size | Status | Where |
|---|---|---|---|
| 1 | 16 bytes | Legacy. Wokwi simulation firmware. No device id, no routing fields, no authentication. Still parseable (`protocol.from_v1`), accepted on the gateway only with `RPM_ALLOW_LEGACY_V1=1`. | `gateway/telemetry.py`, `wokwi/patient_node/telemetry.h` |
| **2** | **34 bytes** | Current. Carries the complete measurement structure of the cahier des charges / `RPMMeasurement.msg`, device identity, authentication tag. | this document |

### Why version 2 was introduced (change record)
v1 could not express relaying (`routingMode`, `hopCount`, `maxHopCount`, `sourceId`, `destinationId`), `alertLevel`, `payloadType` or `critical`, its sequence number restarted at every boot, and any transmitter knowing a patient number could inject data. v2 adds those fields, a 32-bit persisted sequence number and an HMAC tag. The version byte is first in both formats, so a receiver distinguishes them by length and version.

## Frame layout (big-endian)

| Off | Len | Type | Field | Notes |
|---|---|---|---|---|
| 0 | 1 | u8 | `version` | 2 |
| 1 | 1 | u8 | `payloadType` | 1 MEASUREMENT, 2 HEARTBEAT (liveness only, not stored as a measurement), 3 ALERT (event-triggered measurement) |
| 2 | 2 | u16 | `patientId` | 1..65535 |
| 4 | 2 | u16 | `sourceId` | originating device id, 1..65535 |
| 6 | 2 | u16 | `destinationId` | doctor gateway id (default 1) |
| 8 | 4 | u32 | `seqNo` | ≥ 1, strictly increasing per device, persisted across reboots |
| 12 | 4 | u32 | `timestamp` | UTC epoch seconds if flag `TIME_SYNCED`, else device uptime seconds |
| 16 | 1 | u8 | `heartRate` | bpm; 0 with `HRSPO2_FAULT` |
| 17 | 1 | u8 | `spO2` | %; 0 with `HRSPO2_FAULT` |
| 18 | 2 | i16 | `temperature` | 0.01 °C; −32768 with `TEMP_FAULT` |
| 20 | 1 | u8 | `flags` | b0 `fallDetected`, b1 synthetic, b2 HR/SpO2 fault, b3 temperature fault, b4 IMU fault, b5 `critical`, b6 time synced, b7 reserved = 0 |
| 21 | 1 | u8 | `alertLevel` (low nibble) · `routingMode` (high nibble) | alertLevel 0 normal / 1 warning / 2 critical / 3 fall; routingMode 0 direct / 1 relay-assisted |
| 22 | 1 | u8 | `maxHopCount` (low nibble) · `hopCount` (high nibble) | **`hopCount` is the only field a relay may change** |
| 23 | 1 | u8 | `battery` | 0..100 %, 255 = not supported by the hardware |
| 24 | 8 | – | `tag` | first 8 bytes of HMAC-SHA256(device key, bytes 0..23 with the `hopCount` nibble set to 0) |
| 32 | 2 | u16 | `crc16` | CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over bytes 0..31; recomputed by each relay |

The radio's own LoRa CRC is enabled in addition.

Time on air for 34 bytes at SF7 / 125 kHz / CR 4/5 with an 8-symbol preamble is about 80 ms; at one frame per 30 s that is ≈ 0.27 % duty cycle per node (regulatory limits depend on the band and country — verify locally).

## Node behaviour

* One MEASUREMENT every `RPM_SAMPLE_INTERVAL_S` (default 30 s).
* A fall, or a rise of `alertLevel` to ≥ 2, triggers an immediate ALERT frame, transmitted `RPM_ALERT_REPEATS` times with the **same** `seqNo` (the gateway drops the copies).
* A sensor that is absent or failing is reported through its fault flag and a sentinel value. Values are never invented.
* Listen-before-talk (channel activity detection) with random back-off before each transmission.
* `seqNo` is reserved in non-volatile storage in blocks of 32, so a reboot can skip numbers but never reuse one.
* No acknowledgement is sent by the gateway in this version (uplink-only, like the OMNeT++ model). Reliability comes from repetition of event frames and from loss detection at the gateway. A downlink ACK is listed as future work.

## Relay behaviour (application level)

A relay holds no key. For each received frame it:
1. checks length, version, CRC, payload type, non-zero identity fields;
2. drops it unless `destinationId` is the gateway it serves;
3. drops duplicates by `(patientId, seqNo)` (ring of the last 128);
4. drops it if `hopCount ≥ min(maxHopCount, relay limit)`;
5. increments `hopCount`, recomputes the CRC, waits a random 40–200 ms, retransmits.

These are the rules of `RPMRelayApp` in the OMNeT++ model. Because the tag excludes only `hopCount`, a relay (or attacker) cannot alter any other field without the gateway detecting it.

## Gateway validation order

length/version → CRC → known device (`sourceId`) → device active and paired → tag → `destinationId` and `patientId` consistency → hop limit → replay/duplicate window → field plausibility. Every rejected frame is counted and logged as a network event with its reason (`malformed`, `crc_error`, `unknown_device`, `rejected`, `auth_fail`, `duplicate`, `replay`).

Replay window: per device the gateway stores the highest accepted `seqNo` and a 62-bit bitmap of the numbers below it. Higher → accepted (gap counted as loss); inside the window and not yet seen → accepted once (out-of-order); already seen → `duplicate`; older than the window → `replay`.

## Security properties and limits

| Property | Provided? |
|---|---|
| Origin authentication, integrity of all fields except `hopCount` | Yes — per-device 256-bit key, HMAC-SHA256 truncated to 64 bits |
| Replay protection | Yes — persisted 32-bit sequence + window |
| Unique credentials per device, rotation | Yes — key generated at registration, `rotate-key` restarts the sequence space |
| Confidentiality | **No.** Frames are not encrypted: anyone in radio range can read vital signs linked to a numeric patient id (no name is ever transmitted). AES-CCM/GCM payload encryption with the same key is the planned next step; it changes the frame size and therefore the version. |
| Forgery resistance | 64-bit tag: an online forgery needs on average 2⁶³ attempts; three failures per minute for a device raise an alert. |
| `hopCount` integrity | Not authenticated (must be mutable). A malicious relay could lower/raise it; the effect is limited to hop-limit handling and statistics. |
| Jamming / denial of service | Not preventable at this layer; detected as device offline / network degraded. |

Key provisioning: the key is shown once at registration and entered on the node over USB serial (`PROVISION <deviceId> <patientId> <gatewayId> <64 hex>`); it is stored in the ESP32 NVS. NVS is not encrypted unless flash encryption is enabled on the module — enable ESP32 flash encryption and secure boot for any real deployment.

## Test vector

Key = bytes `00 01 … 1F`; patientId 7, sourceId 107, destinationId 1, seqNo 4242, timestamp 1800000000, HR 88, SpO2 96, temperature 37.25, fall + critical + time-synced, alertLevel 3, routingMode 1, hopCount 0, maxHopCount 4, payloadType 3, battery 81. The exact bytes are asserted in `tests/test_protocol_v2.py` for both implementations; print them with:

```
python -c "from gateway import protocol as P; from tests.test_protocol_v2 import M, KEY; print(P.encode(M, KEY).hex())"
```
