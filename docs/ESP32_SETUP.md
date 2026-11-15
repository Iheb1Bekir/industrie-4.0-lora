# ESP32 setup

Two firmwares exist:

| Firmware | Folder | Purpose | Status |
|---|---|---|---|
| Wokwi simulation node | `wokwi/patient_node` | sensors + local alerts in the Wokwi simulator, protocol v1 printed on serial | unchanged; builds with the existing script (`scripts/build_esp32_wokwi.ps1`) |
| **Real-hardware patient node** | `firmware/patient_node_lora` | real LoRa radio (RadioLib), protocol v2, device key, persisted sequence | **HARDWARE PENDING — not yet compiled with the ESP32 toolchain, never run on a board** |
| Relay node (optional) | `firmware/relay_node` | application-level relay | **HARDWARE PENDING — not compiled** |

What *is* verified for the real firmware: the protocol header `rpm_protocol_v2.h` is compiled with g++ (`-Wall -Werror`) and produces byte-identical frames to the Python reference; the fall detector is the same file as the tested Wokwi one. What is *not*: RadioLib calls, pin mapping, MAX30102 driver, timing on the target.

## 1. Toolchain (Windows)

Arduino IDE 2 is installed on this PC; its bundled CLI can be put on the PATH:

```powershell
$env:Path = "$env:LOCALAPPDATA\Programs\Arduino IDE\resources\app\lib\backend\resources;$env:Path"
arduino-cli core update-index
arduino-cli core install esp32:esp32
arduino-cli lib install RadioLib OneWire DallasTemperature
# only if a MAX30102 is wired:
arduino-cli lib install "SparkFun MAX3010x Pulse and Proximity Sensor Library"
```
(A folder `Documents\Arduino\platform-quarantine\esp32-3.3.5.broken` exists on this PC: an earlier ESP32 core install was set aside. If `core install` reports problems, remove the broken core in the IDE's Boards Manager and reinstall.)

Linux / WSL: install `arduino-cli` from arduino.cc, same commands.

## 2. Configure

Edit `firmware/patient_node_lora/config.h`:
1. uncomment exactly one radio: `RPM_RADIO_SX1276`, `RPM_RADIO_SX1278` or `RPM_RADIO_SX1262` — the chip that is physically on your module;
2. set `RPM_LORA_FREQUENCY_MHZ` (must match the module band, the gateway and local regulations);
3. check every pin against your wiring (`HARDWARE_SETUP.md`);
4. set `RPM_USE_MAX30102 1` only if the sensor is connected; `RPM_USE_DS18B20` / `RPM_USE_MPU6050` to 0 if absent.

The same `config.h` is used by the relay (keep the copy in `firmware/relay_node` identical; a test checks this).

## 3. Build and flash

```powershell
arduino-cli board list                                   # find the port, e.g. COM5
arduino-cli compile --fqbn esp32:esp32:esp32s3 firmware/patient_node_lora
arduino-cli upload  --fqbn esp32:esp32:esp32s3 --port COM5 firmware/patient_node_lora
arduino-cli monitor --port COM5 --config baudrate=115200
```
Classic ESP32 DevKit: `--fqbn esp32:esp32:esp32`. Because this firmware has not been compiled yet, expect to fix small compile errors on first build (RadioLib API names differ slightly between major versions; the code targets RadioLib 6/7: `scanChannel()`, `setPacketReceivedAction()`).

## 4. Provision the device identity (once per board)

1. Dashboard (hardware mode) → Devices → **Register device** → optionally pair with the patient. A dialog shows, **once**, the device id, the 256-bit key and a ready-made command.
2. In the serial monitor paste:
   `PROVISION <deviceId> <patientId> <gatewayId> <64-hex-key>`
   → `OK provisioned`. The identity and key are stored in the ESP32 NVS; the sequence counter restarts at 1.
3. `STATUS` shows identity, radio state, counters and which sensors are active.

Other commands: `SEND` (transmit now), `FALLTEST` (sends a fall event frame — a software test, not a physical fall), `FACTORYRESET` (erase identity and key).

If a board is lost or replaced: Devices → **Retire** the old device (its key stops working immediately), register a new device, pair it with the same patient. To renew a key on the same board: **New key**, then `PROVISION` again.

## 5. Behaviour summary

* Every `RPM_SAMPLE_INTERVAL_S` (30 s): read sensors → build frame → listen-before-talk → transmit.
* Fall or new critical level: immediate ALERT frame, sent twice with the same sequence number.
* Missing/failed sensor: fault flag in the frame (dashboard shows a sensor alert; values are never invented). DS18B20 hot-plug is re-probed every 10 s; a failed radio is re-initialised before the next transmission.
* Local LED/buzzer: off = normal, slow blink = warning, fast blink + buzzer = critical/fall.
* No RTC and no network time: the frame carries uptime and the gateway timestamps on reception (documented limitation; end-to-end latency is therefore not measurable from timestamps on real hardware).
* Battery: reported only if `RPM_PIN_BATTERY_ADC` is wired, otherwise "not supported".

## 6. Sensor notes

* **MAX30102**: the adapter uses the SparkFun reference algorithm on a rolling 100-sample window; readings are flagged invalid without finger contact. Accuracy is unvalidated (see `docs/legacy/validation_plan.md` targets). Motion strongly disturbs optical HR/SpO2.
* **DS18B20**: measures the probe, i.e. skin/ambient temperature unless used as a proper contact probe — not core temperature. No calibration offset is applied.
* **MPU6050 fall heuristic**: free-fall followed by impact within 1 s (thresholds 0.5 g / 2.5 g). Prototype thresholds; false positives/negatives are expected until tuned on real recordings.

## 7. Production hardening (not done)

Enable ESP32 flash encryption and secure boot so the device key cannot be read from flash; disable the serial `PROVISION` command after enrolment or protect it with a jumper.
