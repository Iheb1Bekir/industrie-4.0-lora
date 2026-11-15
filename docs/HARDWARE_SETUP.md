# Hardware setup

**Status of everything on this page: HARDWARE PENDING.** No physical ESP32, radio, sensor or Raspberry Pi was connected while this software was written. Pin tables come from the project's earlier wiring document; verify each line against your actual modules before powering anything.

## 1. What you have / what is still needed

| Item | Have | Needed for a 3-patient test |
|---|---|---|
| ESP32 boards | 3 (model to confirm; firmware defaults target ESP32-S3 DevKitC-1) | 3 |
| Raspberry Pi 5 | 1 | 1 |
| LoRa transceivers | **unknown** | 4 identical-band modules: one per node + one for the Pi (SX1276/RFM95W for 868/915 MHz, or SX1278/Ra-02 for 433 MHz), each with a matching antenna |
| DS18B20 + 4.7 kΩ pull-up | to confirm | 3 |
| MPU6050 | to confirm | 3 |
| MAX30102 | to confirm | 3 (optional: without it frames carry the HR/SpO2 fault flag) |
| LED + 220 Ω, buzzer | to confirm | 3 each (optional) |
| Relay nodes | none | optional: any extra ESP32 + LoRa module (`firmware/relay_node`) |
| GPS | none | not required; locations are registered manually with consent |
| Battery + measurement divider | none | optional (`RPM_PIN_BATTERY_ADC`) |

### Identify your radio before anything else
Read the marking on the metal can or chip: `SX1276`, `RFM95W` → SX1276 family (868/915 MHz); `SX1278`, `Ra-02`, `RFM98` → SX1278 (433 MHz); `SX1262`, `Ra-01SH`, `E22` → SX126x. Then:
* firmware: uncomment exactly one `RPM_RADIO_…` line and set `RPM_LORA_FREQUENCY_MHZ` in `firmware/patient_node_lora/config.h` (the build fails until you do);
* gateway: set `frequency_hz` in `hardware/gateway.toml` (the service refuses to start without it).
A 433 MHz module cannot work at 868 MHz and vice versa. **SX126x on the Pi is not supported** by the included driver (the node firmware supports it through RadioLib); use an SX127x module on the Pi or add an adapter.

Choose a frequency and power that are legal where you operate (licence-exempt short-range-device rules differ per country and band; check the national regulator, in Tunisia the ANF). Never transmit without an antenna attached — it can destroy the module.

## 2. Patient node wiring (ESP32-S3 DevKitC-1 defaults — all configurable in `config.h`)

| Module | Pin | ESP32-S3 GPIO | Note |
|---|---|---|---|
| LoRa SX127x | SCK / MISO / MOSI | 12 / 13 / 11 | SPI |
| | NSS (CS) | 10 | |
| | RESET | 14 | |
| | DIO0 | 15 | SX1262: connect DIO1 here and BUSY to the pin set in `RPM_PIN_LORA_BUSY` |
| | 3.3 V / GND | 3V3 / GND | **3.3 V only**; add a 100 µF capacitor near the module if resets occur on transmit |
| DS18B20 | DQ | 4 | 4.7 kΩ pull-up to 3V3 |
| MPU6050 | SDA / SCL | 8 / 9 | I2C 0x68 (or 0x69) |
| MAX30102 | SDA / SCL | 8 / 9 | same I2C bus, 0x57 |
| LED | anode via 220 Ω | 5 | |
| Buzzer | + | 6 | active buzzer (driven HIGH) |
| Battery divider (optional) | midpoint | set `RPM_PIN_BATTERY_ADC` | 1:2 divider, ADC-capable pin |

If your boards are classic ESP32 DevKit (WROOM-32) rather than S3: GPIO 6–11 are reserved for flash there — typical choice SCK 18 / MISO 19 / MOSI 23 / NSS 5 / RST 14 / DIO0 26, SDA 21 / SCL 22, and move LED/buzzer off GPIO 5/6. Change `config.h` accordingly.

## 3. Raspberry Pi 5 gateway wiring (BCM numbering — `hardware/gateway.toml`)

| SX127x pin | Pi 5 pin | BCM |
|---|---|---|
| MOSI | 19 | GPIO10 |
| MISO | 21 | GPIO9 |
| SCK | 23 | GPIO11 |
| NSS | 24 | GPIO8 (CE0) |
| RESET | 22 | GPIO25 (`reset_gpio`, optional) |
| 3.3 V | 17 (or 1) | – |
| GND | 20 (or any GND) | – |
| DIO0 | not required | the driver polls the IRQ register over SPI |

Enable SPI: `sudo raspi-config` → Interface Options → SPI. The service user must be in groups `spi` and `gpio`.

## 4. Radio parameters (must be identical on nodes, relays and gateway)

| Parameter | Value (FLoRa scenario) | Firmware (`config.h`) | Gateway (`gateway.toml`) |
|---|---|---|---|
| Frequency | **you choose** | `RPM_LORA_FREQUENCY_MHZ` | `frequency_hz` |
| Bandwidth | 125 kHz | `RPM_LORA_BANDWIDTH_KHZ` | `bandwidth_hz` |
| Spreading factor | 7 | `RPM_LORA_SPREADING_FACTOR` | `spreading_factor` |
| Coding rate | 4/5 | `RPM_LORA_CODING_RATE 5` | `coding_rate = 5` |
| Sync word | 0x12 | `RPM_LORA_SYNC_WORD` | `sync_word` |
| Preamble | 8 symbols | `RPM_LORA_PREAMBLE` | `preamble` |
| CRC | on | fixed | fixed |
| TX power | 14 dBm | `RPM_LORA_TX_POWER_DBM` | (receive only) |

## 5. Software dependencies

* Node: Arduino IDE or `arduino-cli`, ESP32 core, libraries RadioLib, OneWire, DallasTemperature (+ SparkFun MAX3010x when `RPM_USE_MAX30102 = 1`). → `ESP32_SETUP.md`
* Pi: Python 3.11+, `spidev`, `gpiozero`, `lgpio`. → `RASPBERRY_PI_SETUP.md`

## 6. Three-patient physical test procedure

Record the result of every step in `docs/legacy/validation_plan.md` style (target / procedure / result / evidence). Nothing below has been executed yet.

**Phase A — one node, one gateway**
1. Pi: platform + `hw_gateway` running, dashboard in **hardware mode** (`RASPBERRY_PI_SETUP.md`). Administration → System health shows "Hardware gateway: Enabled".
2. Dashboard: register patient 1, register device (note the provisioning command), pair.
3. Node 1: flash, open the serial monitor, send the `PROVISION …` line, then `STATUS` (expect `provisioned=1`, `radio=…(ok…)`).
4. Expect within 30 s: device **online**, a measurement on the patient profile, a `rx` line in LoRa network → events with RSSI/SNR. Pass criteria: `outcome = stored` in the gateway log.
5. Negative checks: unplug the node → device offline alert after 180 s. Send `PROVISION` with a wrong key → `auth_fail` events, no data stored, "Rejected radio frames" alert after 3 frames.
6. `FALLTEST` on the node → critical fall alert in < 5 s, two frames on air, one stored (duplicate counter +1).

**Phase B — three nodes**
7. Repeat 2–4 for nodes 2 and 3 (different device ids/keys). Check three markers of activity, per-device counters, no cross-talk (each frame lands on its own patient).
8. Packet loss: move one node away / remove its antenna briefly (receiver side only, never transmit without antenna) → `lost` events and a falling delivery ratio; "Network degraded" alert at ≥ 30 % loss.
9. Duplicates: trigger `FALLTEST` several times → duplicates counted, one alert.
10. Gateway restart: stop the platform for 2 minutes while nodes transmit → `hw_gateway` log shows frames spooled, then delivered in order after restart; no gap in the patient chart.
11. Prediction: warm the DS18B20 slowly with your fingers past 37.5 °C toward 38 °C (or use a MAX30102 on a volunteer during light exercise) → AI page shows live predictions with latency on the Pi; a predictive warning may precede the temperature alert. (Sensor accuracy is *not* validated by this test.)
12. Dashboard: all pages update without reload; export a patient PDF; check the audit trail lists registrations and alert actions.

**Phase C — optional relay**: flash `firmware/relay_node` on a fourth board placed between an out-of-range node (`RPM_ROUTING_MODE 1`) and the gateway; expect `hop_count = 1` and "relay-assisted" counters.

Measurements to record for the report: delivery ratio per node over 500 frames at three distances, RSSI/SNR, end-to-end delay (node `TX` log time vs dashboard), inference latency on the Pi, battery life if powered from a cell.
