/*
 * Remote patient monitoring - patient node (ESP32-S3), Wokwi simulation firmware.
 * Task 3: Local alert system (Normal, Borderline, Critical / Fall states)
 */
#include <Arduino.h>
#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include "telemetry.h"
#include "fall_detector.h"

// ---------------- Configuration & pins ----------------
static const uint16_t PATIENT_NUM = 1;              // -> "P001"
static const uint32_t DEFAULT_INTERVAL_S = 60;      // report: 60 s cycle
static const uint8_t PIN_ONEWIRE = 4, PIN_SDA = 8, PIN_SCL = 9, PIN_LED = 5, PIN_BUZZER = 6;
static const float TEMP_BORDERLINE_C = 37.5f, TEMP_CRITICAL_C = 38.0f;

// Seuils d'alerte du projet (Task 3)
static const uint8_t SPO2_LOW = 92, HR_HIGH = 120;
static const uint8_t SPO2_BORDERLINE_LOW = 95, HR_BORDERLINE_HIGH = 100;

enum Scenario { SC_NORMAL, SC_LOW_SPO2, SC_HIGH_HR, SC_HIGH_TEMP, SC_FALL, SC_SENSOR_ERROR, SC_COUNT };
static const char* SC_NAMES[SC_COUNT] = {"NORMAL", "LOW_SPO2", "HIGH_HR", "HIGH_TEMP", "FALL", "SENSOR_ERROR"};

// États pour le système d'alerte local (Task 3)
enum AlertState { STATE_NORMAL, STATE_BORDERLINE, STATE_CRITICAL };

// ---------------- Synthetic MAX30102 stand-in ----------------
class SyntheticHrSpo2 {
public:
  bool read(Scenario s, uint16_t n, uint8_t& hr, uint8_t& spo2) {
    if (s == SC_SENSOR_ERROR) return false;  // simule un capteur déconnecté
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
    const uint8_t addresses[] = {0x68, 0x69};
    for (uint8_t address : addresses) {
      Wire.beginTransmission(address);
      Wire.write(0x75);  // WHO_AM_I
      if (Wire.endTransmission(false) != 0 ||
          Wire.requestFrom(address, (uint8_t)1) != 1) continue;
      if ((Wire.read() & 0x7E) != 0x68) continue;
      address_ = address;
      break;
    }
    if (address_ == 0) return false;

    // Use known full-scale ranges so the raw-value conversions below stay valid.
    ok_ = writeRegister_(0x1A, 0x03) &&  // DLPF: reduce high-frequency noise
          writeRegister_(0x19, 0x09) &&  // 100 Hz sample rate
          writeRegister_(0x1B, 0x00) &&  // gyro: +/-250 degrees/s
          writeRegister_(0x1C, 0x00) &&  // accelerometer: +/-2 g
          writeRegister_(0x6B, 0x00);    // wake up
    return ok_;
  }
  bool ok() const { return ok_; }
  uint8_t address() const { return address_; }
  bool readMotion(float& ax, float& ay, float& az,
                  float& gx, float& gy, float& gz) {
    if (!ok_) return false;
    Wire.beginTransmission(address_); Wire.write(0x3B);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(address_, (uint8_t)14) != 14) return false;
    int16_t raw[7];
    for (int i = 0; i < 7; i++) {
      uint16_t value = ((uint16_t)Wire.read() << 8) | (uint16_t)Wire.read();
      raw[i] = (int16_t)value;
    }
    ax = raw[0] / 16384.0f; ay = raw[1] / 16384.0f; az = raw[2] / 16384.0f;
    gx = raw[4] / 131.0f; gy = raw[5] / 131.0f; gz = raw[6] / 131.0f;
    return true;
  }
private:
  bool writeRegister_(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(address_);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission() == 0;
  }

  uint8_t address_ = 0;
  bool ok_ = false;
};

// ---------------- Local alerts: LED + buzzer (Task 3) ----------------
class AlertManager {
public:
  void begin() {
    pinMode(PIN_LED, OUTPUT);
    digitalWrite(PIN_LED, LOW);
    pinMode(PIN_BUZZER, OUTPUT);
    digitalWrite(PIN_BUZZER, LOW);
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcAttach(PIN_BUZZER, 2000, 8);
#else
    ledcSetup(0, 2000, 8); ledcAttachPin(PIN_BUZZER, 0);
#endif
  }

  // Évaluation des 3 états (Normal, Borderline, Critique)
  void evaluate(float hr, float spo2, float temperatureC, bool temperatureValid,
                bool fall, bool sensorFault) {
    if (fall || sensorFault || !temperatureValid || hr > HR_HIGH ||
        spo2 < SPO2_LOW || temperatureC > TEMP_CRITICAL_C) {
      currentState = STATE_CRITICAL;
    } else if (temperatureC >= TEMP_BORDERLINE_C ||
               hr > HR_BORDERLINE_HIGH || spo2 < SPO2_BORDERLINE_LOW) {
      currentState = STATE_BORDERLINE;
    } else {
      currentState = STATE_NORMAL;
    }
  }

  bool isAlert() const { return currentState != STATE_NORMAL; }

  void update(uint32_t now) {
    bool ledOn = false;
    bool beep = false;

    switch (currentState) {
      case STATE_CRITICAL:
        // Fast non-blocking LED blink and pulsed buzzer.
        ledOn = (now % 400) < 200;
        beep = ledOn;
        break;

      case STATE_BORDERLINE:
        // Medium blink, no buzzer.
        ledOn = (now % 1000) < 500;
        beep = false;
        break;

      case STATE_NORMAL:
      default:
        // Active-HIGH outputs stay off when measurements are normal.
        ledOn = false;
        beep = false;
        break;
    }

    digitalWrite(PIN_LED, ledOn ? HIGH : LOW);
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

  AlertState currentState = STATE_NORMAL;
  int cur_ = -1;
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

// ---------------- Globals ----------------
static SyntheticHrSpo2 max30102_sim;
static TempSensor tempSensor;
static Mpu6050 imu;
static rpm::FallDetector fallDet;
static AlertManager alerts;
static SerialSimTransport serialTransport;
static Transport* transport = &serialTransport;

static Scenario scenario = SC_NORMAL;
static uint32_t intervalMs = DEFAULT_INTERVAL_S * 1000UL, lastTxMs = 0, lastImuMs = 0, lastMpuLogMs = 0;
static uint16_t patientNum = PATIENT_NUM, seqNo = 0;
static bool sendNow = false, tempSynthetic = false, firstTx = true;
static uint8_t lastFlags = 0; static uint8_t lastHr = 0, lastSpo2 = 0; static int16_t lastTemp = 0;
static String cmdBuf;

static bool readTemperature(float& c) {
  if (scenario == SC_SENSOR_ERROR) return false;
  if (scenario == SC_HIGH_TEMP) { c = 38.9f; return true; }
  if (tempSynthetic) { c = 36.6f; return true; }
  return tempSensor.get(c);
}

static void refreshAlerts(uint32_t now) {
  uint8_t hr = 0, spo2 = 0;
  bool hrSpo2Valid = max30102_sim.read(scenario, seqNo, hr, spo2);
  float temperatureC = 0;
  bool temperatureValid = readTemperature(temperatureC);
  bool fall = (scenario == SC_FALL) || fallDet.active(now);
  bool sensorFault = !hrSpo2Valid || !temperatureValid || !imu.ok();
  alerts.evaluate(hr, spo2, temperatureC, temperatureValid, fall, sensorFault);
}

// ---------------- Telemetry build + send ----------------
static void buildAndSend(uint32_t now) {
  rpm::Telemetry t{}; t.pid = patientNum; t.seq = seqNo; t.uptime_s = now / 1000;
  t.flags = rpm::F_SYNTH;
  if (!max30102_sim.read(scenario, seqNo, t.hr, t.spo2)) t.flags |= rpm::F_HRSPO2_FAULT;

  float c = 0;
  bool tOk = readTemperature(c);

  if (!tOk) t.flags |= rpm::F_TEMP_FAULT; else t.temp_x100 = (int16_t)lroundf(c * 100.0f);

  bool fall = (scenario == SC_FALL) || fallDet.active(now);
  if (fall) t.flags |= rpm::F_FALL;
  if (!imu.ok()) t.flags |= rpm::F_IMU_FAULT;
  rpm::normalize(t);

  uint8_t buf[rpm::PACKET_LEN]; rpm::encode(t, buf);
  Serial.printf("DBG {\"pid\":\"P%03u\",\"seq\":%u,\"hr\":%u,\"spo2\":%u,\"temp\":%.2f,\"flags\":%u,\"scenario\":\"%s\",\"uptime\":%lu,\"alert\":%d}\n",
                t.pid, t.seq, t.hr, t.spo2, t.temp_x100 == rpm::TEMP_INVALID ? -999.0 : t.temp_x100 / 100.0,
                t.flags, SC_NAMES[scenario], (unsigned long)t.uptime_s, (int)alerts.isAlert());

  bool ok = transport->send(buf, sizeof(buf), t.seq);
  if (!ok) Serial.println("ERR transmit failed");
  lastFlags = t.flags; lastHr = t.hr; lastSpo2 = t.spo2; lastTemp = t.temp_x100;
  seqNo++; lastTxMs = now;
}

// ---------------- Serial commands ----------------
static void printHelp() {
  Serial.println("Commands: HELP | STATUS | SEND | SET_INTERVAL <s > | SET_PATIENT <1..999> | TEMP_SOURCE <SENSOR|SYNTH>");
  Serial.println("          SET_SCENARIO <NORMAL|LOW_SPO2|HIGH_HR|HIGH_TEMP|FALL|SENSOR_ERROR>");
}

static void printStatus(uint32_t now) {
  Serial.printf("STATUS patient=P%03u scenario=%s interval=%lus seq=%u uptime=%lus\n", patientNum, SC_NAMES[scenario],
                (unsigned long)(intervalMs / 1000), seqNo, (unsigned long)(now / 1000));
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
  else if (cmd == "SET_SCENARIO") {
    for (int i = 0; i < SC_COUNT; i++) if (arg == SC_NAMES[i]) {
      scenario = (Scenario)i; sendNow = true; Serial.printf("OK scenario=%s\n", SC_NAMES[i]); return;
    }
    Serial.println("ERR unknown scenario.");
  } else Serial.println("ERR unknown command - type HELP");
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
  alerts.begin();
  Serial.println("\nRPM patient node starting with Local Alert System (Task 3).");
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);
  tempSensor.begin();
  if (imu.begin()) {
    Serial.printf("MPU6050 ready at I2C address 0x%02X (SDA=%u, SCL=%u)\n",
                  imu.address(), PIN_SDA, PIN_SCL);
  } else {
    Serial.println("ERR MPU6050 not found at I2C address 0x68 or 0x69; check SDA/SCL wiring");
  }
  printHelp();
}

void loop() {
  uint32_t now = millis();
  pollSerial(now);
  tempSensor.update(now);

  if (now - lastImuMs >= 20) {
    lastImuMs = now;
    float ax, ay, az, gx, gy, gz;
    if (imu.readMotion(ax, ay, az, gx, gy, gz)) {
      if (now - lastMpuLogMs >= 500) {
        lastMpuLogMs = now;
        Serial.printf("MPU6050 a[g]=%.2f,%.2f,%.2f gyro[dps]=%.1f,%.1f,%.1f\n",
                      ax, ay, az, gx, gy, gz);
      }
      if (fallDet.update(ax, ay, az, gx, gy, gz, now)) {
        Serial.println("EVENT fall/sudden motion detected");
        sendNow = true;
      }
    } else if (imu.ok() && now - lastMpuLogMs >= 1000) {
      lastMpuLogMs = now;
      Serial.println("ERR MPU6050 I2C motion read failed");
    }
  }

  refreshAlerts(now);

  if (firstTx && now >= 3000) { sendNow = true; firstTx = false; }
  if (sendNow || (now - lastTxMs >= intervalMs && !firstTx)) { sendNow = false; buildAndSend(now); }

  // Mise à jour continue du système d'alerte local (LED / Buzzer)
  alerts.update(now);
}