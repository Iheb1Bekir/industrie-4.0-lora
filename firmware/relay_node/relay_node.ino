/*
 * RPM relay node - application-level raw-LoRa relay (NOT LoRaWAN), mirrors RPMRelayApp of the OMNeT++/FLoRa model.
 *
 * STATUS: HARDWARE PENDING (not compiled for / run on physical boards). The current physical setup has no relay
 * hardware: three ESP32 boards are patient nodes. Flash this to an additional ESP32 + LoRa module to extend range.
 *
 * For every received frame the relay: checks structure + CRC, checks the destination gateway id, drops duplicates
 * by (patientId, seqNo), enforces the hop limit, increments hopCount, recomputes the CRC and retransmits after a
 * random back-off. It holds NO device key: authenticity is verified end-to-end by the gateway (HMAC tag).
 * Copy config.h from firmware/patient_node_lora and set the same radio parameters.
 */
#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include "config.h"
#include "rpm_protocol_v2.h"

#if !defined(RPM_LORA_FREQUENCY_MHZ)
#error "Set RPM_LORA_FREQUENCY_MHZ in config.h."
#endif
#ifndef RPM_GATEWAY_ID
#define RPM_GATEWAY_ID 1
#endif

#if defined(RPM_RADIO_SX1276)
SX1276 radio = new Module(RPM_PIN_LORA_NSS, RPM_PIN_LORA_DIO0, RPM_PIN_LORA_RST, RADIOLIB_NC);
#elif defined(RPM_RADIO_SX1278)
SX1278 radio = new Module(RPM_PIN_LORA_NSS, RPM_PIN_LORA_DIO0, RPM_PIN_LORA_RST, RADIOLIB_NC);
#elif defined(RPM_RADIO_SX1262)
SX1262 radio = new Module(RPM_PIN_LORA_NSS, RPM_PIN_LORA_DIO0, RPM_PIN_LORA_RST, RPM_PIN_LORA_BUSY);
#else
#error "Define the radio chip in config.h."
#endif

static rpm2::DedupCache<128> seen;
static uint32_t received = 0, forwarded = 0, dropped = 0, duplicates = 0, lastStats = 0;
static volatile bool rxFlag = false;
#if defined(ESP32)
IRAM_ATTR
#endif
static void onRx() { rxFlag = true; }

void setup() {
  Serial.begin(115200);
  delay(300);
  randomSeed(esp_random());
  SPI.begin(RPM_PIN_LORA_SCK, RPM_PIN_LORA_MISO, RPM_PIN_LORA_MOSI, RPM_PIN_LORA_NSS);
  int16_t st = radio.begin(RPM_LORA_FREQUENCY_MHZ, RPM_LORA_BANDWIDTH_KHZ, RPM_LORA_SPREADING_FACTOR, RPM_LORA_CODING_RATE,
                           RPM_LORA_SYNC_WORD, RPM_LORA_TX_POWER_DBM, RPM_LORA_PREAMBLE);
  if (st == RADIOLIB_ERR_NONE) st = radio.setCRC(true);
  Serial.printf("RPM relay: radio %s (err %d)\n", st == RADIOLIB_ERR_NONE ? "ready" : "INIT FAILED", st);
  radio.setPacketReceivedAction(onRx);
  radio.startReceive();
}

void loop() {
  if (rxFlag) {
    rxFlag = false;
    uint8_t f[rpm2::FRAME_LEN];
    size_t n = radio.getPacketLength();
    int16_t st = n == rpm2::FRAME_LEN ? radio.readData(f, n) : RADIOLIB_ERR_PACKET_TOO_LONG;
    received++;
    if (st != RADIOLIB_ERR_NONE || !rpm2::checkFrame(f, n) || rpm2::destinationOf(f) != RPM_GATEWAY_ID) dropped++;
    else if (seen.seen(rpm2::patientIdOf(f), rpm2::seqNoOf(f))) { duplicates++; dropped++; }
    else if (!rpm2::relayForward(f, n, RPM_MAX_HOP_COUNT)) dropped++;                      // hop limit
    else {
      seen.add(rpm2::patientIdOf(f), rpm2::seqNoOf(f));
      delay(40 + random(0, 160));                                                          // collision avoidance
      if (radio.transmit(f, n) == RADIOLIB_ERR_NONE) forwarded++; else dropped++;
    }
    radio.startReceive();
  }
  if (millis() - lastStats > 30000) {
    lastStats = millis();
    Serial.printf("RELAY received=%lu forwarded=%lu dropped=%lu duplicates=%lu\n", (unsigned long)received, (unsigned long)forwarded,
                  (unsigned long)dropped, (unsigned long)duplicates);
  }
}
