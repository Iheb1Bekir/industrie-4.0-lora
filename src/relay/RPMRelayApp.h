#ifndef __RPM_RELAYAPP_H_
#define __RPM_RELAYAPP_H_

#include <omnetpp.h>
#include "inet/common/packet/Packet.h"
#include "inet/common/InitStages.h"
#include "inet/linklayer/common/MacAddress.h"
#include "../messages/RPMMeasurement_m.h"

#include <set>

using namespace omnetpp;
using namespace inet;

namespace rpm_lora_research {

class RPMRelayApp : public cSimpleModule
{
  protected:
    int relayIndex = 0;
    int nextHopRelayIndex = -1;
    int maxHopCount = 0;
    int doctorId = 1;
    long receivedPackets = 0;
    long droppedPackets = 0;
    long duplicatePackets = 0;
    MacAddress nextHopAddress;
    std::set<std::pair<int, long>> seenPackets;

    int numInitStages() const override { return inet::NUM_INIT_STAGES; }
    void initialize(int stage) override;
    void handleMessage(cMessage *message) override;
    void finish() override;

    void processPacket(Packet *packet);
};

} // namespace rpm_lora_research

#endif
