#ifndef __RPM_DISTRIBUTEDDOCTORAPP_H_
#define __RPM_DISTRIBUTEDDOCTORAPP_H_

#include "DoctorApp.h"

#include <map>
#include <set>

namespace rpm_lora_research {

class DistributedDoctorApp : public DoctorApp
{
  protected:
    long duplicatePackets = 0;
    long droppedPackets = 0;
    long forwardedPackets = 0;
    long normalAlerts = 0;
    long warningAlerts = 0;
    long criticalAlerts = 0;
    long fallAlerts = 0;
    long directPackets = 0;
    long relayAssistedPackets = 0;
    cOutVector endToEndDelayVector;
    std::set<std::pair<int, long>> seenPackets;
    std::map<int, long> packetsPerPatient;

    void initialize(int stage) override;
    void finish() override;
    void processIncomingPacket(Packet *packet) override;
};

} // namespace rpm_lora_research

#endif
