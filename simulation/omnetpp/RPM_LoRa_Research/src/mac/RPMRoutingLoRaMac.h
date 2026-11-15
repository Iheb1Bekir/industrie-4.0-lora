#ifndef RPM_ROUTING_LORA_MAC_H
#define RPM_ROUTING_LORA_MAC_H

#include "RPMLoRaMac.h"

namespace rpm_lora_research {

class RPMRoutingLoRaMac : public RPMLoRaMac
{
  protected:
    inet::Packet *encapsulate(inet::Packet *packet) override;
};

} // namespace rpm_lora_research

#endif
