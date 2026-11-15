#include "RPMDoctorMac.h"
#include "LoRa/LoRaMacFrame_m.h"
#include "LoRaPhy/LoRaPhyPreamble_m.h"

namespace rpm_lora_research {

Define_Module(RPMDoctorMac);

void RPMDoctorMac::handleLowerMessage(omnetpp::cMessage *message)
{
    auto packet = omnetpp::check_and_cast<inet::Packet *>(message);
    auto preamble = packet->popAtFront<flora::LoRaPhyPreamble>();
    if (preamble == nullptr)
        throw omnetpp::cRuntimeError("RPMDoctorMac received a packet without a LoRa PHY preamble");
    const auto &frame = packet->peekAtFront<flora::LoRaMacFrame>();
    if (frame == nullptr)
        throw omnetpp::cRuntimeError("RPMDoctorMac received a packet without a LoRa MAC frame");

    const auto destination = frame->getReceiverAddress();
    if (destination != address && !destination.isBroadcast()) {
        ++droppedPackets;
        delete packet;
        return;
    }

    ++receivedPackets;
    sendUp(packet);
}

void RPMDoctorMac::finish()
{
    flora::LoRaGWMac::finish();
    recordScalar("receivedPackets", receivedPackets);
    recordScalar("droppedPackets", droppedPackets);
}

} // namespace rpm_lora_research
