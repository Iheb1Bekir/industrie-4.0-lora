#ifndef RPM_PATIENT_RADIO_H
#define RPM_PATIENT_RADIO_H

#include "LoRa/LoRaRadio.h"

namespace rpm_lora_research {

class RPMPatientRadio : public flora::LoRaRadio
{
  protected:
    void initialize(int stage) override;
    void finish() override;
};

} // namespace rpm_lora_research

#endif
