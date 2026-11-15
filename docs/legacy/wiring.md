# Wiring

## A. Wokwi circuit (exactly as in `wokwi/patient_node/diagram.json`)
| Component | Pin | ESP32-S3 | Purpose |
|---|---|---|---|
| DS18B20 | DQ | GPIO4 (+4.7 kΩ pull-up DQ->3V3) | Temperature (1-Wire) |
| DS18B20 | VCC / GND | 3V3 / GND | Power |
| MPU6050 | SDA | GPIO8 | I2C data (motion, fall) |
| MPU6050 | SCL | GPIO9 | I2C clock |
| MPU6050 | VCC / GND | 3V3 / GND | Power |
| LED | anode via 220 Ω | GPIO5 | Status / alert |
| LED | cathode | GND | |
| Buzzer | pin 2 (signal) | GPIO6 | Local warning |
| Buzzer | pin 1 | GND | |

**Not verified:** I could not open Wokwi from this environment, so component type names (`board-esp32-s3-devkitc-1`, `wokwi-ds18b20`, `wokwi-mpu6050`, `wokwi-buzzer`) and pin names (`3V3.1`, `GND.1`, numeric GPIO names) come from my knowledge of Wokwi, not a live check. If Wokwi reports an unknown part/pin, fix the name in `diagram.json` (hover a pin in the editor to see its name). Only the JSON syntax was validated.

## B. Hardware-only (NOT in the Wokwi circuit)
| Component | Pin | ESP32-S3 GPIO | Purpose |
|---|---|---|---|
| MAX30102 | SDA / SCL | GPIO8 / GPIO9 (shared I2C bus, address 0x57) | HR + SpO2 (Wokwi has no MAX30102: replaced by `SyntheticHrSpo2`) |
| MAX30102 | VIN / GND | 3V3 / GND | (INT optional) |
| SX1276 module | SCK / MISO / MOSI | GPIO12 / GPIO13 / GPIO11 | SPI |
| SX1276 | NSS (CS) | GPIO10 | Chip select |
| SX1276 | RESET | GPIO14 | Reset |
| SX1276 | DIO0 | GPIO15 | TX/RX done interrupt |
| SX1276 | 3.3 V / GND | 3V3 / GND | **3.3 V only; attach antenna before transmitting** |

## C. Raspberry Pi 4 gateway radio (hardware mode, BCM numbering)
For a plain SX1276 breakout on SPI0: MOSI GPIO10, MISO GPIO9, SCK GPIO11, NSS GPIO8 (CE0), RESET GPIO25, DIO0 GPIO24, 3.3 V, GND. Enable SPI: `sudo raspi-config` -> Interface Options -> SPI.
The report also names a **RAK2245** HAT. That is an SX1301 *concentrator*, not a plain SX127x: it is normally used with Semtech's packet forwarder (UDP). Using it would need a different `Transport` that parses forwarder JSON - not implemented here (see `hardware_deployment.md`).
