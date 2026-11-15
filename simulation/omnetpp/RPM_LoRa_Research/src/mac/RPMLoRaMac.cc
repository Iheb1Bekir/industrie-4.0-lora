#include "RPMLoRaMac.h"

namespace rpm_lora_research {

Define_Module(RPMLoRaMac);

bool RPMLoRaMac::isForUs(const inet::Ptr<const flora::LoRaMacFrame>& frame)
{
    return isBroadcast(frame) || flora::LoRaMac::isForUs(frame);
}

} // namespace rpm_lora_research