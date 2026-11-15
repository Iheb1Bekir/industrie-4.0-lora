/*
 * RPM patient node - REAL HARDWARE firmware (ESP32 + SX127x/SX126x LoRa radio, raw LoRa, protocol v2).
 *
 * STATUS: HARDWARE PENDING. Written against the documented wiring (docs/HARDWARE_SETUP.md) and the RadioLib API;
 * it has NOT been compiled for or run on the physical boards yet. The Wokwi simulation firmware
 * (wokwi/patient_node) is unchanged and remains the verified simulation target.
 *
 * Libraries (Arduino Library Manager): RadioLib, OneWire, DallasTemperature,
 *                                      SparkFun MAX3010x (only if RPM_USE_MAX30102 = 1).
 * Provisioning (USB serial, 115200):   PROVISION <deviceId> <patientId> <gatewayId> <64-hex-key>
 * Other commands:                      STATUS | SEND | FALLTEST | FACTORYRESET | HELP
 */
#include <Arduino.h>
#include <Preferences.h>
#include <SPI.h>
#include <Wire.h>
#include <RadioLib.h>
#include <mbedtls/md.h>
#include "config.h"
#include "rpm_protocol_v2.h"
#include "fall_detector.h"

#if !defined(RPM_LORA_FREQUENCY_MHZ)
#error "Set RPM_LORA_FREQUENCY_MHZ in config.h (must match your module's band and local radio regulations)."
#endif
#if (defined(RPM_RADIO_SX1276) + defined(RPM_RADIO_SX1278) + defined(RPM_RADIO_SX1262)) != 1
#error "Define exactly one of RPM_RADIO_SX1276 / RPM_RADIO_SX1278 / RPM_RADIO_SX1262 in config.h (the chip on YOUR module)."
#endif

// ------------------------------------------------------------------ radio adapter
#if defined(RPM_RADIO_SX1276)
SX1276 radio = new Module(RPM_PIN_LORA_NSS, RPM_PIN_LORA_DIO0, RPM_PIN_LORA_RST, RPM_PIN_LORA_DIO1 < 0 ? RADIOLIB_NC : RPM_PIN_LORA_DIO1);
static const char* RADIO_NAME = "SX1276";
#elif defined(RPM_RADIO_SX1278)
SX1278 radio = new Module(RPM_PIN_LORA_NSS, RPM_PIN_LORA_DIO0, RPM_PIN_LORA_RST, RPM_PIN_LORA_DIO1 < 0 ? RADIOLIB_NC : RPM_PIN_LORA_DIO1);
static const char* RADIO_NAME = "SX1278";
#else
SX1262 radio = new Module(RPM_PIN_LORA_NSS, RPM_PIN_LORA_DIO0, RPM_PIN_LORA_RST, RPM_PIN_LORA_BUSY);
static const char* RADIO_NAME = "SX1262";
#endif

class LoRaAdapter {
 public:
  bool begin() {
    SPI.begin(RPM_PIN_LORA_SCK, RPM_PIN_LORA_MISO, RPM_PIN_LORA_MOSI, RPM_PIN_LORA_NSS);
    int16_t st = radio.begin(RPM_LORA_FREQUENCY_MHZ, RPM_LORA_BANDWIDTH_KHZ, RPM_LORA_SPREADING_FACTOR, RPM_LORA_CODING_RATE,
                             RPM_LORA_SYNC_WORD, RPM_LORA_TX_POWER_DBM, RPM_LORA_PREAMBLE);
    if (st == RADIOLIB_ERR_NONE) st = radio.setCRC(true);
    ok_ = (st == RADIOLIB_ERR_NONE);
    lastError_ = st;
    return ok_;
  }
  // Listen-before-talk with random back-off, then blocking transmit. Returns true when the radio reports success.
  bool send(const uint8_t* frame, size_t n) {
    if (!ok_ && !begin()) { failures_++; return false; }     // re-initialise after a radio fault
    for (int attempt = 0; attempt < 4; attempt++) {
      int16_t cad = radio.scanChannel();
      if (cad == RADIOLIB_CHANNEL_FREE) break;
      delay(60 + random(0, 240));
    }
    int16_t st = radio.transmit(const_cast<uint8_t*>(frame), n);
    lastError_ = st;
    if (st != RADIOLIB_ERR_NONE) { failures_++; ok_ = false; return false; }
    sent_++;
    return true;
  }
  bool ok() const { return ok_; }
  int16_t lastError() const { return lastError_; }
  uint32_t sent() const { return sent_; }
  uint32_t failures() const { return failures_; }
 private:
  bool ok_ = false; int16_t lastError_ = 0; uint32_t sent_ = 0, failures_ = 0;
};

// ------------------------------------------------------------------ sensor adapters (one class per sensor)
struct Vitals { bool hrSpo2Valid = false; uint8_t hr = 0, spo2 = 0; bool tempValid = false; float tempC = 0; };

#if RPM_USE_DS18B20
#include <OneWire.h>
#include <DallasTemperature.h>
class TemperatureSensor {
 public:
  TemperatureSensor() : ow_(RPM_PIN_ONEWIRE), dt_(&ow_) {}
  void begin() { dt_.begin(); dt_.setWaitForConversion(false); present_ = dt_.getDeviceCount() > 0; }
  void update(uint32_t now) {
    if (!present_) { if (now - lastProbe_ > 10000) { lastProbe_ = now; begin(); } return; }   // hot re-plug detection
    if (!pending_) { dt_.requestTemperatures(); t0_ = now; pending_ = true; }
    else if (now - t0_ >= 800) { float c = dt_.getTempCByIndex(0); pending_ = false; valid_ = c > -100.0f && c < 125.0f; last_ = c; if (!valid_) present_ = false; }
  }
  bool read(float& c) const { c = last_; return present_ && valid_; }
 private:
  OneWire ow_; DallasTemperature dt_; bool present_ = false, valid_ = false, pending_ = false; uint32_t t0_ = 0, lastProbe_ = 0; float last_ = 0;
};
#else
class TemperatureSensor { public: void begin() {} void update(uint32_t) {} bool read(float&) const { return false; } };
#endif

#if RPM_USE_MAX30102
#include <MAX30105.h>
#include <spo2_algorithm.h>
// UNVERIFIED on hardware. Uses the SparkFun reference algorithm on a rolling 100-sample window (25 Hz).
class HrSpo2Sensor {
 public:
  bool begin() {
    ok_ = dev_.begin(Wire, I2C_SPEED_FAST);
    if (ok_) dev_.setup(60, 4, 2, 100, 411, 4096);   // LED power, averaging, red+IR, 100 Hz /4 = 25 Hz
    return ok_;
  }
  void update() {
    if (!ok_) return;
    dev_.check();
    while (dev_.available()) {
      memmove(red_, red_ + 1, sizeof(uint32_t) * 99); memmove(ir_, ir_ + 1, sizeof(uint32_t) * 99);
      red_[99] = dev_.getRed(); ir_[99] = dev_.getIR(); dev_.nextSample();
      if (filled_ < 100) filled_++;
      if (++fresh_ >= 25 && filled_ == 100) {
        fresh_ = 0;
        int32_t spo2, hr; int8_t vs, vh;
        maxim_heart_rate_and_oxygen_saturation(ir_, 100, red_, &spo2, &vs, &hr, &vh);
        fingerOn_ = ir_[99] > 50000;
        valid_ = fingerOn_ && vs && vh && hr >= 20 && hr <= 250 && spo2 >= 50 && spo2 <= 100;
        if (valid_) { hr_ = (uint8_t)hr; spo2_ = (uint8_t)spo2; }
      }
    }
  }
  bool read(uint8_t& hr, uint8_t& spo2) const { hr = hr_; spo2 = spo2_; return ok_ && valid_; }
 private:
  MAX30105 dev_; bool ok_ = false, valid_ = false, fingerOn_ = false; uint32_t red_[100] = {0}, ir_[100] = {0};
  uint8_t filled_ = 0, fresh_ = 0, hr_ = 0, spo2_ = 0;
};
#else
// No HR/SpO2 sensor installed: read() fails, the frame carries F_HRSPO2_FAULT. Values are never fabricated.
class HrSpo2Sensor { public: bool begin() { return false; } void update() {} bool read(uint8_t&, uint8_t&) const { return false; } };
#endif

class MotionSensor {   // MPU6050, raw I2C (same register sequence as the verified Wokwi firmware)
 public:
  bool begin() {
#if RPM_USE_MPU6050
    for (uint8_t a : {(uint8_t)0x68, (uint8_t)0x69}) {
      Wire.beginTransmission(a); Wire.write(0x75);
      if (Wire.endTransmission(false) != 0 || Wire.requestFrom(a, (uint8_t)1) != 1) continue;
      if ((Wire.read() & 0x7E) != 0x68) continue;
      addr_ = a; break;
    }
    if (!addr_) return false;
    ok_ = wr(0x1A, 0x03) && wr(0x19, 0x09) && wr(0x1B, 0x00) && wr(0x1C, 0x00) && wr(0x6B, 0x00);
#endif
    return ok_;
  }
  bool ok() const { return ok_; }
  bool read(float& ax, float& ay, float& az, float& gx, float& gy, float& gz) {
    if (!ok_) return false;
    Wire.beginTransmission(addr_); Wire.write(0x3B);
    if (Wire.endTransmission(false) != 0 || Wire.requestFrom(addr_, (uint8_t)14) != 14) { if (++errors_ > 25) ok_ = false; return false; }
    int16_t r[7];
    for (int i = 0; i < 7; i++) { uint16_t v = ((uint16_t)Wire.read() << 8) | (uint16_t)Wire.read(); r[i] = (int16_t)v; }
    errors_ = 0;
    ax = r[0] / 16384.0f; ay = r[1] / 16384.0f; az = r[2] / 16384.0f; gx = r[4] / 131.0f; gy = r[5] / 131.0f; gz = r[6] / 131.0f;
    return true;
  }
 private:
  bool wr(uint8_t reg, uint8_t v) { Wire.beginTransmission(addr_); Wire.write(reg); Wire.write(v); return Wire.endTransmission() == 0; }
  uint8_t addr_ = 0, errors_ = 0; bool ok_ = false;
};

// ------------------------------------------------------------------ identity + persistent sequence number
struct Identity { uint16_t deviceId = 0, patientId = 0, gatewayId = 0; uint8_t key[32] = {0}; bool provisioned = false; };
static Preferences nvs;
static Identity ident;
static uint32_t seqNo = 0, seqReserved = 0;

static void hmacSha256(const uint8_t* key, size_t keyLen, const uint8_t* msg, size_t n, uint8_t out[32]) {
  mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), key, keyLen, msg, n, out);
}

static void loadIdentity() {
  nvs.begin("rpm", false);
  ident.deviceId = nvs.getUShort("dev", 0); ident.patientId = nvs.getUShort("pat", 0); ident.gatewayId = nvs.getUShort("gw", 0);
  ident.provisioned = nvs.getBytes("key", ident.key, 32) == 32 && ident.deviceId && ident.patientId && ident.gatewayId;
  // Sequence numbers must never repeat (replay protection): resume after the last RESERVED block.
  seqNo = seqReserved = nvs.getULong("seq", 0);
}

static uint32_t nextSeq() {
  if (seqNo >= seqReserved) { seqReserved = seqNo + RPM_SEQ_PERSIST_BLOCK; nvs.putULong("seq", seqReserved); }
  return ++seqNo;
}

static bool provision(const String& arg) {
  unsigned dev, pat, gw; char hex[65] = {0};
  if (sscanf(arg.c_str(), "%u %u %u %64s", &dev, &pat, &gw, hex) != 4 || strlen(hex) != 64 || !dev || dev > 65535 || !pat || pat > 65535 || !gw || gw > 65535) return false;
  uint8_t key[32];
  for (int i = 0; i < 32; i++) { unsigned b; if (sscanf(hex + 2 * i, "%2x", &b) != 1) return false; key[i] = (uint8_t)b; }
  nvs.putUShort("dev", dev); nvs.putUShort("pat", pat); nvs.putUShort("gw", gw); nvs.putBytes("key", key, 32);
  nvs.putULong("seq", 0);                       // a new key starts a new sequence space (server resets its window too)
  memset(key, 0, sizeof(key));
  loadIdentity();
  return ident.provisioned;
}

// ------------------------------------------------------------------ globals
static LoRaAdapter lora;
static TemperatureSensor tempSensor;
static HrSpo2Sensor hrSensor;
static MotionSensor imu;
static rpm::FallDetector fallDet;
static uint32_t lastSampleMs = 0, lastTxMs = 0, lastImuMs = 0;
static bool sendNow = false, fallLatched = false, testFall = false;
static uint8_t lastAlertLevel = 0;
static String cmdBuf;

static uint8_t batteryPercent() {
#if RPM_PIN_BATTERY_ADC >= 0
  // Assumes a 1:2 divider on a single Li-ion cell (3.3 V = empty, 4.2 V = full). Calibrate before trusting it.
  float v = analogReadMilliVolts(RPM_PIN_BATTERY_ADC) * 2.0f / 1000.0f;
  return (uint8_t)constrain((int)((v - 3.3f) / 0.9f * 100.0f), 0, 100);
#else
  return rpm2::BATTERY_UNSUPPORTED;
#endif
}

static void localAlert(uint8_t level, uint32_t now) {      // LED + buzzer, non-blocking
  bool led = level >= 2 ? (now % 400) < 200 : level == 1 ? (now % 1000) < 500 : false;
  digitalWrite(RPM_PIN_LED, led ? HIGH : LOW);
  digitalWrite(RPM_PIN_BUZZER, (level >= 2 && led) ? HIGH : LOW);
}

static void sampleAndSend(uint32_t now, bool event) {
  if (!ident.provisioned) { Serial.println("ERR not provisioned - use PROVISION (see docs/ESP32_SETUP.md)"); return; }
  rpm2::Measurement m{};
  m.patientId = ident.patientId; m.sourceId = ident.deviceId; m.destinationId = ident.gatewayId;
  m.timestamp = now / 1000;                     // uptime: this node has no RTC, so F_TIME_SYNCED stays clear
  m.maxHopCount = RPM_MAX_HOP_COUNT; m.hopCount = 0; m.routingMode = RPM_ROUTING_MODE; m.battery = batteryPercent();
  uint8_t hr = 0, spo2 = 0; float tc = 0;
  if (hrSensor.read(hr, spo2)) { m.heartRate = hr; m.spO2 = spo2; } else m.flags |= rpm2::F_HRSPO2_FAULT;
  if (tempSensor.read(tc)) m.temperature_x100 = (int16_t)lroundf(tc * 100.0f); else m.flags |= rpm2::F_TEMP_FAULT;
  if (!imu.ok()) m.flags |= rpm2::F_IMU_FAULT;
  bool fall = fallLatched || testFall; fallLatched = false; testFall = false;
  if (fall) m.flags |= rpm2::F_FALL;
  rpm2::normalize(m);
  const bool hrOk = !(m.flags & rpm2::F_HRSPO2_FAULT), tOk = !(m.flags & rpm2::F_TEMP_FAULT);
  if (fall) m.alertLevel = 3;
  else if ((hrOk && (m.heartRate > RPM_HR_HIGH || m.spO2 < RPM_SPO2_LOW)) || (tOk && m.temperature_x100 >= (int16_t)(RPM_TEMP_HIGH_C * 100))) m.alertLevel = 2;
  else if ((hrOk && (m.heartRate > RPM_HR_WARN || m.spO2 < RPM_SPO2_WARN)) || (tOk && m.temperature_x100 >= (int16_t)(RPM_TEMP_WARN_C * 100))) m.alertLevel = 1;
  if (m.alertLevel >= 2) m.flags |= rpm2::F_CRITICAL;
  const bool escalated = m.alertLevel >= 2 && m.alertLevel > lastAlertLevel;
  m.payloadType = (event || escalated) ? rpm2::PT_ALERT : rpm2::PT_MEASUREMENT;
  lastAlertLevel = m.alertLevel;
  m.seqNo = nextSeq();
  uint8_t frame[rpm2::FRAME_LEN];
  rpm2::encode(m, ident.key, 32, hmacSha256, frame);
  const int repeats = m.payloadType == rpm2::PT_ALERT ? RPM_ALERT_REPEATS : 1;   // duplicates are dropped by (device, seqNo)
  bool ok = false;
  for (int i = 0; i < repeats; i++) { ok = lora.send(frame, sizeof(frame)) || ok; if (i + 1 < repeats) delay(150 + random(0, 200)); }
  lastTxMs = millis();
  Serial.printf("TX seq=%lu type=%u level=%u hr=%u spo2=%u temp=%.2f flags=0x%02X %s (radio err %d)\n", (unsigned long)m.seqNo, m.payloadType,
                m.alertLevel, m.heartRate, m.spO2, m.temperature_x100 == rpm2::TEMP_INVALID ? -999.0 : m.temperature_x100 / 100.0, m.flags,
                ok ? "OK" : "FAILED", lora.lastError());
}

static void handleCommand(String line) {
  line.trim(); if (!line.length()) return;
  int sp = line.indexOf(' ');
  String cmd = sp < 0 ? line : line.substring(0, sp); cmd.toUpperCase();
  String arg = sp < 0 ? "" : line.substring(sp + 1);
  if (cmd == "PROVISION") Serial.println(provision(arg) ? "OK provisioned" : "ERR usage: PROVISION <deviceId> <patientId> <gatewayId> <64 hex chars>");
  else if (cmd == "STATUS") {
    Serial.printf("STATUS provisioned=%d device=%u patient=%u gateway=%u seq=%lu radio=%s(%s, err %d) freq=%.3fMHz sf=%d sent=%lu failed=%lu\n",
                  ident.provisioned, ident.deviceId, ident.patientId, ident.gatewayId, (unsigned long)seqNo, RADIO_NAME, lora.ok() ? "ok" : "FAULT",
                  lora.lastError(), (double)RPM_LORA_FREQUENCY_MHZ, RPM_LORA_SPREADING_FACTOR, (unsigned long)lora.sent(), (unsigned long)lora.failures());
    Serial.printf("  sensors: DS18B20=%d MAX30102=%d MPU6050=%s battery=%s\n", RPM_USE_DS18B20, RPM_USE_MAX30102, imu.ok() ? "ok" : "missing",
                  RPM_PIN_BATTERY_ADC >= 0 ? "adc" : "not supported");
  } else if (cmd == "SEND") sendNow = true;
  else if (cmd == "FALLTEST") { testFall = true; sendNow = true; Serial.println("OK test fall frame queued (software test, not a physical fall)"); }
  else if (cmd == "FACTORYRESET") { nvs.clear(); loadIdentity(); Serial.println("OK identity and key erased"); }
  else Serial.println("Commands: PROVISION <dev> <patient> <gateway> <keyhex> | STATUS | SEND | FALLTEST | FACTORYRESET");
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(RPM_PIN_LED, OUTPUT); pinMode(RPM_PIN_BUZZER, OUTPUT);
  randomSeed(esp_random());
  loadIdentity();
  Wire.begin(RPM_PIN_SDA, RPM_PIN_SCL); Wire.setClock(400000);
  tempSensor.begin(); hrSensor.begin(); imu.begin();
  Serial.printf("\nRPM patient node (protocol v2, raw LoRa). Radio %s: %s\n", RADIO_NAME, lora.begin() ? "ready" : "INIT FAILED - check wiring/config.h");
  Serial.println(ident.provisioned ? "Identity loaded." : "NOT PROVISIONED: register the device in the dashboard, then send the PROVISION command.");
}

void loop() {
  uint32_t now = millis();
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\n' || ch == '\r') { if (cmdBuf.length()) { handleCommand(cmdBuf); cmdBuf = ""; } }
    else if (cmdBuf.length() < 120) cmdBuf += ch;
  }
  tempSensor.update(now);
  hrSensor.update();
  if (now - lastImuMs >= 20) {
    lastImuMs = now;
    float ax, ay, az, gx, gy, gz;
    if (imu.read(ax, ay, az, gx, gy, gz) && fallDet.update(ax, ay, az, now)) { fallLatched = true; sendNow = true; Serial.println("EVENT fall detected"); }
  }
  const bool due = now - lastSampleMs >= (uint32_t)RPM_SAMPLE_INTERVAL_S * 1000UL || lastSampleMs == 0;
  if ((sendNow || due) && now - lastTxMs >= RPM_MIN_TX_GAP_MS) {
    const bool event = sendNow && (fallLatched || testFall);
    sendNow = false; lastSampleMs = now;
    sampleAndSend(now, event);
  }
  localAlert(lastAlertLevel, now);
}
