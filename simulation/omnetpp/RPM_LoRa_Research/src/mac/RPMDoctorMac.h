#ifndef RPM_DOCTOR_MAC_H
#define RPM_DOCTOR_MAC_H

#include "LoRa/LoRaGWMac.h"

namespace rpm_lora_research {

class RPMDoctorMac : public flora::LoRaGWMac
{
  protected:
    long receivedPackets = 0;
    long droppedPackets = 0;

    void handleLowerMessage(omnetpp::cMessage *message) override;

  public:
    void finish() override;
};

} // namespace rpm_lora_research

#endif
