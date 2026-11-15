// Host cross-check of firmware/patient_node_lora/rpm_protocol_v2.h against gateway/protocol.py.
// argv[1] = 64 hex chars: the HMAC tag computed by Python (the header is crypto-agnostic; mbedTLS is used on the ESP32).
#include <cstdio>
#include <cstdlib>
#include "rpm_protocol_v2.h"

static uint8_t TAG[32];
static void fakeHmac(const uint8_t*, size_t, const uint8_t* msg, size_t n, uint8_t out[32]) {
  for (size_t i = 0; i < n; i++) printf("%02X", msg[i]);  // line 1: the exact bytes the firmware authenticates
  printf("\n");
  memcpy(out, TAG, 32);
}
static void dump(const uint8_t* f) {
  for (int i = 0; i < 34; i++) printf("%02X", f[i]);
  printf("\n");
}

int main(int argc, char** argv) {
  if (argc < 2) return 2;
  for (int i = 0; i < 32; i++) { unsigned b; sscanf(argv[1] + 2 * i, "%2x", &b); TAG[i] = (uint8_t)b; }
  rpm2::Measurement m{};
  m.patientId = 7; m.sourceId = 107; m.destinationId = 1; m.seqNo = 4242; m.timestamp = 1800000000u;
  m.heartRate = 88; m.spO2 = 96; m.temperature_x100 = 3725;
  m.flags = rpm2::F_FALL | rpm2::F_CRITICAL | rpm2::F_TIME_SYNCED;
  m.alertLevel = 3; m.routingMode = 1; m.hopCount = 0; m.maxHopCount = 4; m.payloadType = rpm2::PT_ALERT; m.battery = 81;
  rpm2::normalize(m);
  uint8_t key[32] = {0}, f[34];
  rpm2::encode(m, key, 32, fakeHmac, f);
  dump(f);
  printf("%d\n", rpm2::checkFrame(f, 34));
  bool ok = rpm2::relayForward(f, 34, 4);
  dump(f);
  for (int i = 0; i < 3; i++) ok = rpm2::relayForward(f, 34, 4) && ok;
  printf("%d %d\n", ok, rpm2::relayForward(f, 34, 4));    // 4 hops allowed, the 5th is refused
  rpm2::DedupCache<4> c;
  c.add(7, 4242);
  printf("%d %d\n", c.seen(7, 4242), c.seen(7, 4243));
  f[9] ^= 1;
  printf("%d\n", rpm2::checkFrame(f, 34));
  rpm2::Measurement bad{};
  bad.heartRate = 255; bad.spO2 = 30; bad.temperature_x100 = 9000;
  rpm2::normalize(bad);
  printf("%d %d %d\n", bad.flags, bad.heartRate, bad.temperature_x100);
  return 0;
}
