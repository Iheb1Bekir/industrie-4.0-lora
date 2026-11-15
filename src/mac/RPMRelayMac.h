#ifndef RPM_RELAY_MAC_H
#define RPM_RELAY_MAC_H

#include "LoRa/LoRaGWMac.h"
#include "inet/queueing/contract/IActivePacketSink.h"

namespace rpm_lora_research {

class RPMRelayMac : public flora::LoRaGWMac, public inet::queueing::IActivePacketSink
{
  protected:
    long deliveredPackets = 0;
    long droppedPackets = 0;
    long forwardedPackets = 0;

    void initialize(int stage) override;
    void handleSelfMessage(omnetpp::cMessage *message) override;
    void handleUpperMessage(omnetpp::cMessage *message) override;
    void handleLowerMessage(omnetpp::cMessage *message) override;
    void processQueuedPacket();

  public:
    inet::queueing::IPassivePacketSource *getProvider(const omnetpp::cGate *gate) override;
    void handleCanPullPacketChanged(const omnetpp::cGate *gate) override;
    void handlePullPacketProcessed(inet::Packet *packet, const omnetpp::cGate *gate, bool successful) override;
    void finish() override;
};

} // namespace rpm_lora_research

#endif
