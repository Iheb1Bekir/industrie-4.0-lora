/*
 * Remote patient monitoring - patient node (ESP32-S3), Wokwi simulation firmware.
 *
 *  Real (Wokwi-simulated) devices : DS18B20 (temperature), MPU6050 (fall), LED, buzzer
 *  SYNTHETIC substitute           : MAX30102 HR/SpO2  -> class SyntheticHrSpo2 (no MAX30102 in Wokwi)
 *  Simulated radio                : SerialSimTransport prints "LORA_TX_SIM ..." - this is NOT LoRa.
 *  Hardware-only (not simulated)  : SX1276 -> see Sx1276Transport under #ifdef RPM_USE_SX1276 (untested)
 *
 * Type HELP in the Serial Monitor.
 */
#include <Arduino.h>
#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include "telemetry.h"
#include "fall_detector.h"

// ---------------- Configuration & pins ----------------
static const uint16_t PATIENT_NUM = 1;               // -> "P001"
static const uint32_t DEFAULT_INTERVAL_S = 60;       // report: 60 s cycle
static const uint8_t PIN_ONEWIRE = 4, PIN_SDA = 8, PIN_SCL = 9, PIN_LED = 5, PIN_BUZZER = 6;
// Hardware-only SX1276 wiring (ESP32-S3 FSPI): SCK=12 MISO=13 MOSI=11 NSS=10 RST=14 DIO0=15 (3V3, GND)
// Prototype local alert thresholds (same defaults as gateway/config.py; NOT clinically validated)
static const uint8_t SPO2_LOW = 92, HR_HIGH = 120, HR_LOW = 40;
static const int16_t TEMP_HIGH_X100 = 3800, TEMP_LOW_X100 = 3500;

enum Scenario { SC_NORMAL, SC_LOW_SPO2, SC_HIGH_HR, SC_HIGH_TEMP, SC_FALL, SC_SENSOR_ERROR, SC_COUNT };
static const char* SC_NAMES[SC_COUNT] = {"NORMAL", "LOW_SPO2", "HIGH_HR", "HIGH_TEMP", "FALL", "SENSOR_ERROR"};

// ---------------- Synthetic MAX30102 stand-in ----------------
class SyntheticHrSpo2 {
 public:
  bool read(Scenario s, uint16_t n, uint8_t& hr, uint8_t& spo2) {
    if (s == SC_SENSOR_ERROR) return false;  // simulates a disconnected sensor
    int j = (int)((n * 7) % 5) - 2;
    hr = 72 + j; spo2 = 97 + (j > 0 ? 1 : 0);
    if (s == SC_LOW_SPO2) { spo2 = 89 - (n % 2); hr = 88; }
    else if (s == SC_HIGH_HR) hr = 132 + j;
    else if (s == SC_FALL) hr = 95;
    return true;
  }
};

// ---------------- DS18B20 (non-blocking) ----------------
class TempSensor {
 public:
  TempSensor() : ow_(PIN_ONEWIRE), dt_(&ow_) {}
  void begin() { dt_.begin(); dt_.setWaitForConversion(false); present_ = dt_.getDeviceCount() > 0; }
  void update(uint32_t now) {
    if (!present_) return;
    if (!pending_) { dt_.requestTemperatures(); t0_ = now; pending_ = true; }
    else if (now - t0_ >= 800) {
      float c = dt_.getTempCByIndex(0); pending_ = false;
      valid_ = (c > -100.0f && c < 125.0f); last_ = c;
    }
  }
  bool present() const { return present_; }
  bool get(float& c) const { c = last_; return present_ && valid_; }
 private:
  OneWire ow_; DallasTemperature dt_;
  bool present_ = false, valid_ = false, pending_ = false; uint32_t t0_ = 0; float last_ = 0;
};

// ---------------- MPU6050 (raw I2C) ----------------
class Mpu6050 {
 public:
  bool begin() {
    Wire.beginTransmission(0x68); Wire.write(0x6B); Wire.write(0x00);  // wake
    ok_ = (Wire.endTransmission() == 0); return ok_;
  }
  bool ok() const { return ok_; }
  bool readG(float& x, float& y, float& z) {
    if (!ok_) return false;
    Wire.beginTransmission(0x68); Wire.write(0x3B);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom((uint8_t)0x68, (uint8_t)6) != 6) return false;
    int16_t a[3];
    for (int i = 0; i < 3; i++) { int hi = Wire.read(); int lo = Wire.read(); a[i] = (int16_t)((hi << 8) | lo); }
    x = a[0] / 16384.0f; y = a[1] / 16384.0f; z = a[2] / 16384.0f;  // +-2 g range
    return true;
  }
 private:
  bool ok_ = false;
};

// ---------------- Local alerts: LED + buzzer (non-blocking) ----------------
class AlertManager {
 public:
  void begin() {
    pinMode(PIN_LED, OUTPUT);
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcAttach(PIN_BUZZER, 2000, 8);
#else
    ledcSetup(0, 2000, 8); ledcAttachPin(PIN_BUZZER, 0);
#endif
  }
  void set(bool alert, bool critical) { alert_ = alert; critical_ = critical; }
  bool alert() const { return alert_; }
  void update(uint32_t now) {
    bool led = alert_ ? true : ((now % 2000) < 100);   // solid on alert, heartbeat blink otherwise
    digitalWrite(PIN_LED, led);
    bool beep = false;
    if (critical_) beep = (now % 400) < 200;           // fall / critical: 2.5 Hz beeping
    else if (alert_) beep = (now % 5000) < 150;        // other alerts: short beep every 5 s
    tone_(beep ? 2000 : 0);
  }
 private:
  void tone_(int f) {
    if (f == cur_) return;
    cur_ = f;
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWriteTone(PIN_BUZZER, f);
#else
    ledcWriteTone(0, f);
#endif
  }
  bool alert_ = false, critical_ = false; int cur_ = -1;
};

// ---------------- Transport abstraction ----------------
class Transport {
 public:
  virtual ~Transport() {}
  virtual bool send(const uint8_t* p, size_t n, uint16_t seq) = 0;
  virtual const char* name() const = 0;
};

class SerialSimTransport : public Transport {  // SIMULATION ONLY - not LoRa
 public:
  bool send(const uint8_t* p, size_t n, uint16_t seq) override {
    Serial.printf("LORA_TX_SIM seq=%u hex=", seq);
    for (size_t i = 0; i < n; i++) Serial.printf("%02X", p[i]);
    Serial.println();
    return true;
  }
  const char* name() const override { return "SERIAL_SIM (not LoRa)"; }
};

#ifdef RPM_USE_SX1276   // HARDWARE MODE - requires RadioLib in libraries.txt and a physical SX1276 module; UNTESTED
#include <RadioLib.h>
#include <SPI.h>
class Sx1276Transport : public Transport {
 public:
  Sx1276Transport() : radio_(new Module(10, 15, 14, RADIOLIB_NC)) {}
  bool begin() {
    SPI.begin(12, 13, 11, 10);
    return radio_.begin(868.1, 125.0, 7, 5, 0x12, 14) == RADIOLIB_ERR_NONE;  // MHz, kHz, SF, CR4/5, sync, dBm
  }
  bool send(const uint8_t* p, size_t n, uint16_t) override { return radio_.transmit((uint8_t*)p, n) == RADIOLIB_ERR_NONE; }
  const char* name() const override { return "SX1276 LoRa"; }
 private:
  SX1276 radio_;
};
#endif

// ---------------- Globals ----------------
static SyntheticHrSpo2 max30102_sim;
static TempSensor tempSensor;
static Mpu6050 imu;
static rpm::FallDetector fallDet;
static AlertManager alerts;
static SerialSimTransport serialTransport;
static Transport* transport = &serialTransport;

static Scenario scenario = SC_NORMAL;
static uint32_t intervalMs = DEFAULT_INTERVAL_S * 1000UL, lastTxMs = 0, lastImuMs = 0;
static uint16_t patientNum = PATIENT_NUM, seqNo = 0;
static bool sendNow = false, tempSynthetic = false, firstTx = true;
static uint8_t lastFlags = 0; static uint8_t lastHr = 0, lastSpo2 = 0; static int16_t lastTemp = 0;
static String cmdBuf;

// ---------------- Telemetry build + send ----------------
static void buildAndSend(uint32_t now) {
  rpm::Telemetry t{}; t.pid = patientNum; t.seq = seqNo; t.uptime_s = now / 1000;
  t.flags = rpm::F_SYNTH;  // HR/SpO2 are always synthetic in this build -> packet marked SYNTHETIC
  if (!max30102_sim.read(scenario, seqNo, t.hr, t.spo2)) t.flags |= rpm::F_HRSPO2_FAULT;

  float c = 0; bool tOk;
  if (scenario == SC_SENSOR_ERROR) tOk = false;
  else if (scenario == SC_HIGH_TEMP) { c = 38.9f; tOk = true; }
  else if (tempSynthetic) { c = 36.6f; tOk = true; }
  else { tOk = tempSensor.get(c); }                 // genuine DS18B20 reading (simulated device in Wokwi)
  if (!tOk) t.flags |= rpm::F_TEMP_FAULT; else t.temp_x100 = (int16_t)lroundf(c * 100.0f);

  bool fall = (scenario == SC_FALL) || fallDet.active(now);
  if (fall) t.flags |= rpm::F_FALL;
  if (!imu.ok()) t.flags |= rpm::F_IMU_FAULT;
  rpm::normalize(t);

  // local alert evaluation (prototype thresholds)
  bool critical = fall;
  bool alert = critical || (t.flags & (rpm::F_HRSPO2_FAULT | rpm::F_TEMP_FAULT | rpm::F_IMU_FAULT));
  if (!(t.flags & rpm::F_HRSPO2_FAULT)) alert |= (t.spo2 < SPO2_LOW) || (t.hr > HR_HIGH) || (t.hr < HR_LOW);
  if (!(t.flags & rpm::F_TEMP_FAULT)) alert |= (t.temp_x100 >= TEMP_HIGH_X100) || (t.temp_x100 < TEMP_LOW_X100);
  alerts.set(alert, critical);

  uint8_t buf[rpm::PACKET_LEN]; rpm::encode(t, buf);
  Serial.printf("DBG {\"pid\":\"P%03u\",\"seq\":%u,\"hr\":%u,\"spo2\":%u,\"temp\":%.2f,\"flags\":%u,\"scenario\":\"%s\",\"uptime\":%lu,\"alert\":%d}\n",
                t.pid, t.seq, t.hr, t.spo2, t.temp_x100 == rpm::TEMP_INVALID ? -999.0 : t.temp_x100 / 100.0,
                t.flags, SC_NAMES[scenario], (unsigned long)t.uptime_s, (int)alert);
  bool ok = transport->send(buf, sizeof(buf), t.seq);
  if (!ok) Serial.println("ERR transmit failed (will retry next interval)");
  lastFlags = t.flags; lastHr = t.hr; lastSpo2 = t.spo2; lastTemp = t.temp_x100;
  seqNo++; lastTxMs = now;
}

// ---------------- Serial commands ----------------
static void printHelp() {
  Serial.println("Commands: HELP | STATUS | SEND | SET_INTERVAL <5..3600 s> | SET_PATIENT <1..999> | TEMP_SOURCE <SENSOR|SYNTH>");
  Serial.println("          SET_SCENARIO <NORMAL|LOW_SPO2|HIGH_HR|HIGH_TEMP|FALL|SENSOR_ERROR>");
}

static void printStatus(uint32_t now) {
  Serial.printf("STATUS patient=P%03u scenario=%s interval=%lus seq=%u uptime=%lus transport=%s\n", patientNum, SC_NAMES[scenario],
                (unsigned long)(intervalMs / 1000), seqNo, (unsigned long)(now / 1000), transport->name());
  Serial.printf("  sensors: DS18B20=%s MPU6050=%s MAX30102=SYNTHETIC(no real sensor) temp_source=%s\n",
                tempSensor.present() ? "present" : "MISSING", imu.ok() ? "present" : "MISSING", tempSynthetic ? "SYNTH" : "SENSOR");
  Serial.printf("  last: hr=%u spo2=%u temp=%.2f flags=0x%02X local_alert=%s\n", lastHr, lastSpo2,
                lastFlags & rpm::F_TEMP_FAULT ? -999.0 : lastTemp / 100.0, lastFlags, alerts.alert() ? "ON" : "off");
}

static void handleCommand(String line, uint32_t now) {
  line.trim(); if (line.length() == 0) return;
  line.toUpperCase();
  int sp = line.indexOf(' ');
  String cmd = sp < 0 ? line : line.substring(0, sp);
  String arg = sp < 0 ? "" : line.substring(sp + 1); arg.trim();
  if (cmd == "HELP") printHelp();
  else if (cmd == "STATUS") printStatus(now);
  else if (cmd == "SEND") { sendNow = true; Serial.println("OK sending now"); }
  else if (cmd == "SET_INTERVAL") {
    long v = arg.toInt();
    if (arg.length() == 0 || v < 5 || v > 3600) Serial.println("ERR usage: SET_INTERVAL <5..3600> (seconds), e.g. SET_INTERVAL 10");
    else { intervalMs = (uint32_t)v * 1000UL; Serial.printf("OK interval=%lds\n", v); }
  } else if (cmd == "SET_PATIENT") {
    long v = arg.toInt();
    if (arg.length() == 0 || v < 1 || v > 999) Serial.println("ERR usage: SET_PATIENT <1..999>");
    else { patientNum = (uint16_t)v; Serial.printf("OK patient=P%03ld\n", v); }
  } else if (cmd == "TEMP_SOURCE") {
    if (arg == "SENSOR") tempSynthetic = false; else if (arg == "SYNTH") tempSynthetic = true;
    else { Serial.println("ERR usage: TEMP_SOURCE <SENSOR|SYNTH>"); return; }
    Serial.printf("OK temp_source=%s\n", arg.c_str());
  } else if (cmd == "SET_SCENARIO") {
    for (int i = 0; i < SC_COUNT; i++) if (arg == SC_NAMES[i]) {
      scenario = (Scenario)i; sendNow = true; Serial.printf("OK scenario=%s (sending now)\n", SC_NAMES[i]); return;
    }
    Serial.println("ERR unknown scenario. Valid: NORMAL LOW_SPO2 HIGH_HR HIGH_TEMP FALL SENSOR_ERROR");
  } else Serial.printf("ERR unknown command '%s' - type HELP\n", cmd.c_str());
}

static void pollSerial(uint32_t now) {
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\n' || ch == '\r') { if (cmdBuf.length()) { handleCommand(cmdBuf, now); cmdBuf = ""; } }
    else if (cmdBuf.length() < 64) cmdBuf += ch;
  }
}

// ---------------- Arduino entry points ----------------
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nRPM patient node starting. MAX30102 is SYNTHETIC; radio is SERIAL_SIM (not LoRa).");
  Wire.begin(PIN_SDA, PIN_SCL);
  tempSensor.begin();
  imu.begin();
  alerts.begin();
  Serial.printf("DS18B20 %s, MPU6050 %s\n", tempSensor.present() ? "found" : "NOT found", imu.ok() ? "found" : "NOT found");
  printHelp();
}

void loop() {
  uint32_t now = millis();
  pollSerial(now);
  tempSensor.update(now);

  if (now - lastImuMs >= 20) {  // 50 Hz IMU sampling for fall detection
    lastImuMs = now;
    float x, y, z;
    if (imu.readG(x, y, z) && fallDet.update(x, y, z, now)) { Serial.println("EVENT possible fall detected (MPU6050)"); sendNow = true; }
  }

  if (firstTx && now >= 3000) { sendNow = true; firstTx = false; }
  if (sendNow || (now - lastTxMs >= intervalMs && !firstTx)) { sendNow = false; buildAndSend(now); }
  alerts.update(now);
}
