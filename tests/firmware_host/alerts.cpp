#include <cassert>
#include "patient_node.ino"

int main() {
  AlertManager alerts;
  alerts.begin();

  alerts.evaluate(100, 95, 23.8f, true, false, false);
  assert(!alerts.isAlert());
  alerts.update(0);
  assert(stubLedValue == LOW && stubToneFrequency == 0);
  alerts.update(100);
  assert(stubLedValue == LOW);

  alerts.evaluate(100, 97, 37.5f, true, false, false);
  assert(alerts.isAlert());
  alerts.update(0);
  assert(stubLedValue == HIGH && stubToneFrequency == 0);
  alerts.update(500);
  assert(stubLedValue == LOW && stubToneFrequency == 0);

  alerts.evaluate(100, 97, 38.0f, true, false, false);
  assert(alerts.isAlert());
  alerts.update(0);
  assert(stubLedValue == HIGH && stubToneFrequency == 0);

  alerts.evaluate(100, 97, 38.01f, true, false, false);
  assert(alerts.isAlert());
  alerts.update(0);
  assert(stubLedValue == HIGH && stubToneFrequency == 2000);
  alerts.update(200);
  assert(stubLedValue == LOW && stubToneFrequency == 0);

  alerts.evaluate(120, 97, 23.8f, true, false, false);
  assert(alerts.isAlert());

  alerts.evaluate(80, 94, 23.8f, true, false, false);
  assert(alerts.isAlert());
  alerts.update(0);
  assert(stubLedValue == HIGH && stubToneFrequency == 0);

  alerts.evaluate(121, 97, 23.8f, true, false, false);
  assert(alerts.isAlert());
  alerts.update(0);
  assert(stubLedValue == HIGH && stubToneFrequency == 2000);
  alerts.update(200);
  assert(stubLedValue == LOW && stubToneFrequency == 0);

  alerts.evaluate(88, 91, 23.8f, true, false, false);
  assert(alerts.isAlert());
  alerts.evaluate(80, 97, 23.8f, true, true, false);
  assert(alerts.isAlert());
  alerts.evaluate(80, 97, 23.8f, true, false, true);
  assert(alerts.isAlert());

  alerts.evaluate(80, 97, 23.8f, true, false, false);
  assert(!alerts.isAlert());
  alerts.evaluate(80, 97, 23.8f, false, false, false);
  assert(alerts.isAlert());
}
