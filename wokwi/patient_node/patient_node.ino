/*
 * Remote patient monitoring - patient node (ESP32-S3), Wokwi simulation firmware.
 * HR/SpO2 use software profiles; temperature and motion use Wokwi sensors.
 * SerialSimTransport is a test path, not LoRa.
 * Type HELP in the Serial Monitor.
 */
#include <Arduino.h>
#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include "telemetry.h"
#include "fall_detector.h"
#include "patient_reading.h"

// ---------------- Configuration & pins ----------------
static const uint16_t PATIENT_NUM = 1;               // -> "P001"
static const uint32_t DEFAULT_INTERVAL_S = 60;       // report: 60 s cycle
static const uint32_t DEFAULT_PATIENT_SAMPLE_INTERVAL_MS = 5000;
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
static uint32_t patientSampleIntervalMs = DEFAULT_PATIENT_SAMPLE_INTERVAL_MS, lastPatientSampleMs = 0;
static uint16_t patientNum = PATIENT_NUM, seqNo = 0;
static rpm::PatientProfile patientProfile = rpm::PROFILE_NORMAL;
static bool sendNow = false, tempSynthetic = false, firstTx = true, patientSampleStarted = false;
static bool simulatedFallPending = false;
static uint8_t lastFlags = 0; static uint8_t lastHr = 0, lastSpo2 = 0; static int16_t lastTemp = 0;
static String cmdBuf;

// ---------------- Patient reading ----------------
static rpm::PatientReading readPatientData(uint32_t now, rpm::PatientReadingSources& sources) {
  const rpm::SimulatedVitals simulated = rpm::simulatedVitals(patientProfile);
  rpm::PatientReading reading{};
  reading.patient_id = patientNum;
  reading.timestamp_ms = now;
  reading.heart_rate_bpm = simulated.heart_rate_bpm;
  reading.spo2_percent = simulated.spo2_percent;
  sources.heart_rate = "SIMULATED_PROFILE";
  sources.spo2 = "SIMULATED_PROFILE";

  if (scenario == SC_LOW_SPO2) { reading.heart_rate_bpm = 88; reading.spo2_percent = 89; }
  else if (scenario == SC_HIGH_HR) reading.heart_rate_bpm = 132;

  float temperature = 0;
  bool temperatureOk = false;
  if (scenario == SC_HIGH_TEMP) {
    temperature = 38.9f;
    temperatureOk = true;
    sources.temperature = "SIMULATED_SCENARIO";
  } else if (tempSynthetic) {
    temperature = simulated.temperature_c;
    temperatureOk = true;
    sources.temperature = "SIMULATED_PROFILE";
  } else if (tempSensor.get(temperature)) {
    temperatureOk = temperature >= 20.0f && temperature <= 45.0f;
    sources.temperature = temperatureOk ? "DS18B20_SENSOR" : "UNAVAILABLE_OUT_OF_RANGE";
  } else {
    sources.temperature = "UNAVAILABLE_SENSOR";
  }
  sources.temperature_valid = temperatureOk;
  if (temperatureOk) reading.temperature_c = temperature;

  const bool commandFall = rpm::consumeSimulatedFall(simulatedFallPending);
  const bool scenarioFall = scenario == SC_FALL;
  const bool sensorFall = imu.ok() && fallDet.active(now);
  reading.fall_detected = commandFall || scenarioFall || sensorFall;
  if (commandFall) sources.fall = "SERIAL_COMMAND_SIMULATED";
  else if (scenarioFall) sources.fall = "SIMULATED_SCENARIO";
  else if (sensorFall) sources.fall = "MPU6050_HEURISTIC";
  else sources.fall = imu.ok() ? "MPU6050_SENSOR_NO_FALL" : "UNAVAILABLE_ACCELEROMETER";

  const bool sensorFault = scenario == SC_SENSOR_ERROR ||
                           !sources.temperature_valid || !imu.ok();
  alerts.evaluate(reading.heart_rate_bpm, reading.spo2_percent,
                  reading.temperature_c, sources.temperature_valid,
                  reading.fall_detected, sensorFault);
  return reading;
}

static void printPatientData(const rpm::PatientReading& reading,
                             const rpm::PatientReadingSources& sources) {
  const std::string json = rpm::serializePatientReading(reading, sources);
  Serial.println(json.c_str());
}

static bool readTemperature(float& c) {
  if (scenario == SC_SENSOR_ERROR) return false;
  if (scenario == SC_HIGH_TEMP) { c = 38.9f; return true; }
  if (tempSynthetic) { c = 36.6f; return true; }
  return tempSensor.get(c);
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
  Serial.println("Commands: HELP | STATUS | NORMAL | WARNING | CRITICAL | FALL");
  Serial.println("          SET_SAMPLE_INTERVAL <1..3600 s> | SET_PATIENT <1..999> | TEMP_SOURCE <SENSOR|SYNTH>");
  Serial.println("          SEND | SET_INTERVAL <5..3600 s> | SET_SCENARIO <...>");
  Serial.println("          SET_SCENARIO <NORMAL|LOW_SPO2|HIGH_HR|HIGH_TEMP|FALL|SENSOR_ERROR>");
}

static void printStatus(uint32_t now) {
  Serial.printf("STATUS patient=%u profile=%s scenario=%s sample_interval=%lus tx_interval=%lus seq=%u uptime=%lus transport=%s\n",
                patientNum, patientProfile == rpm::PROFILE_NORMAL ? "NORMAL" : patientProfile == rpm::PROFILE_WARNING ? "WARNING" : "CRITICAL", SC_NAMES[scenario],
                (unsigned long)(patientSampleIntervalMs / 1000),
                (unsigned long)(intervalMs / 1000), seqNo, (unsigned long)(now / 1000), transport->name());
  Serial.printf("  sensors: DS18B20=%s MPU6050=%s MAX30102=SYNTHETIC(no real sensor) temp_source=%s\n",
                tempSensor.present() ? "present" : "MISSING", imu.ok() ? "present" : "MISSING", tempSynthetic ? "SYNTH" : "SENSOR");
  Serial.printf("  last: hr=%u spo2=%u temp=%.2f flags=0x%02X local_alert=%s\n", lastHr, lastSpo2,
                lastFlags & rpm::F_TEMP_FAULT ? -999.0 : lastTemp / 100.0,
                lastFlags, alerts.isAlert() ? "ON" : "off");
}

static void handleCommand(String line, uint32_t now) {
  line.trim(); if (line.length() == 0) return;
  line.toUpperCase();
  int sp = line.indexOf(' ');
  String cmd = sp < 0 ? line : line.substring(0, sp);
  String arg = sp < 0 ? "" : line.substring(sp + 1); arg.trim();
  if (cmd == "HELP") printHelp();
  else if (cmd == "STATUS") printStatus(now);
  else if (cmd == "NORMAL" || cmd == "WARNING" || cmd == "CRITICAL") {
    patientProfile = cmd == "WARNING" ? rpm::PROFILE_WARNING :
                     cmd == "CRITICAL" ? rpm::PROFILE_CRITICAL : rpm::PROFILE_NORMAL;
    scenario = SC_NORMAL;
    Serial.printf("OK profile=%s (applies to the next patient reading)\n", cmd.c_str());
  } else if (cmd == "FALL") {
    scenario = SC_NORMAL;
    simulatedFallPending = true;
    Serial.println("OK simulated fall queued for the next patient reading");
  } else if (cmd == "SET_SAMPLE_INTERVAL") {
    long v = arg.toInt();
    if (arg.length() == 0 || v < 1 || v > 3600) Serial.println("ERR usage: SET_SAMPLE_INTERVAL <1..3600> seconds");
    else {
      patientSampleIntervalMs = (uint32_t)v * 1000UL;
      Serial.printf("OK patient_sample_interval=%lds\n", v);
    }
  }
  else if (cmd == "SEND") { sendNow = true; Serial.println("OK sending now"); }
  else if (cmd == "SET_SCENARIO") {
    for (int i = 0; i < SC_COUNT; i++) if (arg == SC_NAMES[i]) {
      if (i == SC_NORMAL) patientProfile = rpm::PROFILE_NORMAL;
      scenario = (Scenario)i; sendNow = true; Serial.printf("OK scenario=%s (sending now)\n", SC_NAMES[i]); return;
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
  delay(300);
  Serial.println("\nRPM patient node starting. HR/SpO2 are simulated; timestamp_ms is elapsed time since startup.");
  alerts.begin();
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

  if (rpm::patientSampleDue(now, lastPatientSampleMs, patientSampleStarted, patientSampleIntervalMs)) {
    patientSampleStarted = true;
    lastPatientSampleMs = now;
    rpm::PatientReadingSources sources{};
    const rpm::PatientReading reading = readPatientData(now, sources);
    printPatientData(reading, sources);
  }

  if (firstTx && now >= 3000) { sendNow = true; firstTx = false; }
  if (sendNow || (now - lastTxMs >= intervalMs && !firstTx)) { sendNow = false; buildAndSend(now); }

  // Mise à jour continue du système d'alerte local (LED / Buzzer)
  alerts.update(now);
}