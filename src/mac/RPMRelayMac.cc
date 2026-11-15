#include "RPMRelayMac.h"
#include "inet/linklayer/common/MacAddressTag_m.h"
#include "inet/common/Units.h"
#include "LoRa/LoRaTagInfo_m.h"
#include "LoRa/LoRaMacFrame_m.h"
#include "LoRaPhy/LoRaPhyPreamble_m.h"

namespace rpm_lora_research {

Define_Module(RPMRelayMac);

void RPMRelayMac::initialize(int stage)
{
    flora::LoRaGWMac::initialize(stage);
    if (stage == INITSTAGE_LOCAL)
        txQueue = getQueue(gate(upperLayerInGateId));
}

inet::queueing::IPassivePacketSource *RPMRelayMac::getProvider(const omnetpp::cGate *gate)
{
    return gate->getId() == upperLayerInGateId ? txQueue.get() : nullptr;
}

void RPMRelayMac::handleCanPullPacketChanged(const omnetpp::cGate *gate)
{
    Enter_Method("handleCanPullPacketChanged");
    if (gate->getId() == upperLayerInGateId && !waitingForDC)
        processQueuedPacket();
}

void RPMRelayMac::handlePullPacketProcessed(inet::Packet *packet, const omnetpp::cGate *gate, bool successful)
{
    Enter_Method("handlePullPacketProcessed");
    throw omnetpp::cRuntimeError("RPMRelayMac does not support pull callbacks");
}

void RPMRelayMac::handleSelfMessage(omnetpp::cMessage *message)
{
    flora::LoRaGWMac::handleSelfMessage(message);
    if (message == dutyCycleTimer)
        processQueuedPacket();
}

void RPMRelayMac::processQueuedPacket()
{
    if (!waitingForDC && canDequeuePacket())
        handleUpperMessage(dequeuePacket());
}

void RPMRelayMac::handleLowerMessage(omnetpp::cMessage *message)
{
    auto packet = omnetpp::check_and_cast<inet::Packet *>(message);
    auto preamble = packet->popAtFront<flora::LoRaPhyPreamble>();
    if (preamble == nullptr)
        throw omnetpp::cRuntimeError("RPMRelayMac received a packet without a LoRa PHY preamble");

    const auto &frame = packet->peekAtFront<flora::LoRaMacFrame>();
    if (frame == nullptr)
        throw omnetpp::cRuntimeError("RPMRelayMac received a packet without a LoRa MAC frame");

    const auto destination = frame->getReceiverAddress();
    if (destination != address && !destination.isBroadcast()) {
        ++droppedPackets;
        delete packet;
        return;
    }

    auto loraTag = packet->addTagIfAbsent<flora::LoRaTag>();
    loraTag->setCenterFrequency(frame->getLoRaCF());
    loraTag->setBandwidth(frame->getLoRaBW());
    loraTag->setSpreadFactor(frame->getLoRaSF());
    loraTag->setPower(preamble->getPower());
    loraTag->setCodeRendundance(frame->getLoRaCR());
    loraTag->setUseHeader(frame->getLoRaUseHeader());

    auto macAddressInd = packet->addTagIfAbsent<inet::MacAddressInd>();
    macAddressInd->setSrcAddress(frame->getTransmitterAddress());
    macAddressInd->setDestAddress(destination);

    packet->popAtFront<flora::LoRaMacFrame>();
    ++deliveredPackets;
    sendUp(packet);
}

void RPMRelayMac::handleUpperMessage(omnetpp::cMessage *message)
{
    auto packet = omnetpp::check_and_cast<inet::Packet *>(message);
    const auto &destinationTag = packet->findTag<inet::MacAddressReq>();
    const auto &loraTag = packet->findTag<flora::LoRaTag>();
    if (destinationTag == nullptr || loraTag == nullptr)
        throw omnetpp::cRuntimeError("RPMRelayMac requires MacAddressReq and LoRaTag on outgoing packets");

    auto frame = inet::makeShared<flora::LoRaMacFrame>();
    frame->setChunkLength(inet::B(par("headerLength").intValue()));
    frame->setTransmitterAddress(address);
    frame->setReceiverAddress(destinationTag->getDestAddress());
    frame->setSequenceNumber(forwardedPackets);
    frame->setLoRaCF(loraTag->getCenterFrequency());
    frame->setLoRaBW(loraTag->getBandwidth());
    frame->setLoRaSF(loraTag->getSpreadFactor());
    frame->setLoRaCR(loraTag->getCodeRendundance());
    frame->setLoRaTP(loraTag->getPower().get() * 1000);
    frame->setLoRaUseHeader(loraTag->getUseHeader());
    packet->insertAtFront(frame);

    const auto previousForwardedCount = GW_forwardedDown;
    const auto previousDroppedCount = GW_droppedDC;
    flora::LoRaGWMac::handleUpperMessage(packet);
    if (GW_forwardedDown > previousForwardedCount)
        ++forwardedPackets;
    else if (GW_droppedDC > previousDroppedCount)
        ++droppedPackets;
}

void RPMRelayMac::finish()
{
    flora::LoRaGWMac::finish();
    recordScalar("receivedPackets", deliveredPackets);
    recordScalar("forwardedPackets", forwardedPackets);
    recordScalar("droppedPackets", droppedPackets);
}

} // namespace rpm_lora_research
