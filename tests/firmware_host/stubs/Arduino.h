// Minimal Arduino stub: ONLY for host-side syntax/type checking of sketch.ino. Not a simulator.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdarg>
#include <cmath>
#include <string>
#define OUTPUT 1
#define HIGH 1
struct String {
  std::string s;
  String(const char* c = "") : s(c) {}
  String(const std::string& c) : s(c) {}
  unsigned length() const { return s.size(); }
  void trim() { size_t a = s.find_first_not_of(" \t\r\n"); size_t b = s.find_last_not_of(" \t\r\n"); s = a == std::string::npos ? "" : s.substr(a, b - a + 1); }
  void toUpperCase() { for (auto& c : s) c = toupper(c); }
  int indexOf(char c) const { auto p = s.find(c); return p == std::string::npos ? -1 : (int)p; }
  String substring(int a) const { return String(s.substr(a)); }
  String substring(int a, int b) const { return String(s.substr(a, b - a)); }
  long toInt() const { return atol(s.c_str()); }
  const char* c_str() const { return s.c_str(); }
  bool operator==(const char* o) const { return s == o; }
  String& operator+=(char c) { s += c; return *this; }
  String& operator=(const char* c) { s = c; return *this; }
};
struct SerialClass {
  void begin(int) {}
  int available() { return 0; }
  int read() { return -1; }
  void println(const char* c = "") { puts(c); }
  void printf(const char* f, ...) { va_list a; va_start(a, f); vprintf(f, a); va_end(a); }
};
static SerialClass Serial;
inline uint32_t millis() { return 0; }
inline void delay(uint32_t) {}
inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t, uint8_t) {}
inline void ledcAttach(uint8_t, int, int) {}
inline void ledcWriteTone(uint8_t, int) {}
#define ESP_ARDUINO_VERSION_MAJOR 3
