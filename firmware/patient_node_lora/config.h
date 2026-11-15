// Central hardware configuration of the patient node. EVERYTHING here must match your real wiring and radio.
// Nothing in this file has been verified on physical hardware yet (status: HARDWARE PENDING).
#pragma once

// ---------------------------------------------------------------- LoRa radio (via RadioLib)
// Pick the chip that is physically on your module. Do NOT pick one "that seems close":
//   SX1276 / RFM95W  : 868 / 915 MHz band modules        -> #define RPM_RADIO_SX1276
//   SX1278 / Ra-02   : 433 MHz band modules              -> #define RPM_RADIO_SX1278
//   SX1262           : different driver family           -> #define RPM_RADIO_SX1262 (also needs BUSY pin)
// Exactly one must be defined. There is deliberately NO default.
// #define RPM_RADIO_SX1276
// #define RPM_RADIO_SX1278
// #define RPM_RADIO_SX1262

// Operating frequency in MHz. No default on purpose: it depends on the module's hardware band AND on what is
// legally usable where the device operates (check the national regulator's rules for short-range devices
// before transmitting). The same value must be configured on relays and on the gateway.
// #define RPM_LORA_FREQUENCY_MHZ 868.1

#define RPM_LORA_BANDWIDTH_KHZ 125.0     // FLoRa scenario: 125 kHz
#define RPM_LORA_SPREADING_FACTOR 7      // FLoRa scenario: SF7
#define RPM_LORA_CODING_RATE 5           // 4/5
#define RPM_LORA_SYNC_WORD 0x12          // private network (0x34 is LoRaWAN public - this is NOT LoRaWAN)
#define RPM_LORA_TX_POWER_DBM 14         // FLoRa scenario: 14 dBm; never exceed the local legal limit
#define RPM_LORA_PREAMBLE 8

// SPI + control pins (ESP32-S3 DevKitC-1 defaults from docs/wiring.md - change to your wiring)
#define RPM_PIN_LORA_SCK 12
#define RPM_PIN_LORA_MISO 13
#define RPM_PIN_LORA_MOSI 11
#define RPM_PIN_LORA_NSS 10
#define RPM_PIN_LORA_RST 14
#define RPM_PIN_LORA_DIO0 15             // SX127x: DIO0 (TxDone/RxDone). SX1262: DIO1
#define RPM_PIN_LORA_DIO1 -1             // optional on SX127x (RADIOLIB_NC)
#define RPM_PIN_LORA_BUSY -1             // SX1262 only

// ---------------------------------------------------------------- sensors (enable only what is wired)
#define RPM_USE_DS18B20 1                // temperature, 1-Wire
#define RPM_PIN_ONEWIRE 4
#define RPM_USE_MPU6050 1                // fall detection, I2C
#define RPM_USE_MAX30102 0               // HR / SpO2, I2C. 0 = not installed -> frames carry the HR/SpO2 FAULT flag
#define RPM_PIN_SDA 8
#define RPM_PIN_SCL 9
#define RPM_PIN_LED 5
#define RPM_PIN_BUZZER 6
// Battery measurement: -1 = no divider wired -> battery field is sent as "not supported" (255).
#define RPM_PIN_BATTERY_ADC -1

// ---------------------------------------------------------------- behaviour
#define RPM_SAMPLE_INTERVAL_S 30         // FLoRa scenario samplingInterval = 30 s
#define RPM_MAX_HOP_COUNT 4              // FLoRa scenario maxHopCount = 4
#define RPM_ROUTING_MODE 0               // 0 = direct to gateway, 1 = via relay (out of gateway range)
#define RPM_ALERT_REPEATS 2              // event frames (fall / critical) are sent this many times (same seqNo)
#define RPM_MIN_TX_GAP_MS 2000           // guard against flooding the channel
#define RPM_SEQ_PERSIST_BLOCK 32         // seqNo is reserved in NVS in blocks (limits flash wear)

// Engineering demonstration thresholds for the LOCAL LED/buzzer and alertLevel (not medical rules).
#define RPM_HR_HIGH 120
#define RPM_HR_WARN 100
#define RPM_SPO2_LOW 92
#define RPM_SPO2_WARN 95
#define RPM_TEMP_HIGH_C 38.0f
#define RPM_TEMP_WARN_C 37.5f
