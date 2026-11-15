#ifndef RPM_LORA_MAC_H
#define RPM_LORA_MAC_H

#include "LoRa/LoRaMac.h"

namespace rpm_lora_research {

class RPMLoRaMac : public flora::LoRaMac
{
  protected:
    bool isForUs(const inet::Ptr<const flora::LoRaMacFrame>& frame) override;
};

} // namespace rpm_lora_research

#endif
