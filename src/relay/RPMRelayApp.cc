#include "RPMRelayApp.h"
#include "inet/linklayer/common/MacAddressTag_m.h"
#include "inet/common/Units.h"
#include "LoRa/LoRaTagInfo_m.h"
#include "LoRa/LoRaMacFrame_m.h"
#include "LoRaPhy/LoRaPhyPreamble_m.h"

#include <algorithm>
#include <cstdio>

namespace rpm_lora_research {

Define_Module(RPMRelayApp);

void RPMRelayApp::initialize(int stage)
{
    if (stage == INITSTAGE_APPLICATION_LAYER) {
        relayIndex = par("relayIndex").intValue();
        nextHopRelayIndex = par("nextHopRelayIndex").intValue();
        maxHopCount = par("maxHopCount").intValue();
        doctorId = par("doctorId").intValue();

        auto network = getParentModule()->getParentModule();
        cModule *nextHop = nextHopRelayIndex < 0
                ? network->getSubmodule("doctor")
                : network->getSubmodule("relay", nextHopRelayIndex);
        if (nextHop == nullptr)
            throw cRuntimeError("Relay %d has invalid next-hop relay index %d", relayIndex, nextHopRelayIndex);
        auto nextHopMac = nextHop->getSubmodule("LoRaNic")->getSubmodule("mac");
        nextHopAddress.setAddress(nextHopMac->par("address").stringValue());

        char displayName[32];
        std::snprintf(displayName, sizeof(displayName), "Relay_%02d", relayIndex + 1);
        getParentModule()->getDisplayString().setTagArg("t", 0, displayName);
    }
}

void RPMRelayApp::handleMessage(cMessage *message)
{
    if (!message->arrivedOn("socketIn"))
        throw cRuntimeError("RPMRelayApp received an unexpected message");
    processPacket(check_and_cast<Packet *>(message));
}

void RPMRelayApp::processPacket(Packet *packet)
{
    ++receivedPackets;
    auto frontChunk = packet->peekAtFront<Chunk>();
    auto preamble = dynamicPtrCast<const flora::LoRaPhyPreamble>(frontChunk);
    if (preamble != nullptr) {
        auto loraTag = packet->addTagIfAbsent<flora::LoRaTag>();
        loraTag->setCenterFrequency(preamble->getCenterFrequency());
        loraTag->setBandwidth(preamble->getBandwidth());
        loraTag->setSpreadFactor(preamble->getSpreadFactor());
        loraTag->setPower(preamble->getPower());
        loraTag->setCodeRendundance(preamble->getCodeRendundance());
        loraTag->setUseHeader(preamble->getUseHeader());
        packet->popAtFront<flora::LoRaPhyPreamble>();
        frontChunk = packet->peekAtFront<Chunk>();
    }

    auto macFrame = dynamicPtrCast<const flora::LoRaMacFrame>(frontChunk);
    if (macFrame != nullptr) {
        if (packet->findTag<flora::LoRaTag>() == nullptr) {
            auto loraTag = packet->addTag<flora::LoRaTag>();
            loraTag->setCenterFrequency(macFrame->getLoRaCF());
            loraTag->setBandwidth(macFrame->getLoRaBW());
            loraTag->setSpreadFactor(macFrame->getLoRaSF());
            loraTag->setPower(W(macFrame->getLoRaTP()));
            loraTag->setCodeRendundance(macFrame->getLoRaCR());
            loraTag->setUseHeader(macFrame->getLoRaUseHeader());
        }
        auto sourceTag = packet->addTagIfAbsent<MacAddressInd>();
        sourceTag->setSrcAddress(macFrame->getTransmitterAddress());
        sourceTag->setDestAddress(macFrame->getReceiverAddress());
        packet->popAtFront<flora::LoRaMacFrame>();
        frontChunk = packet->peekAtFront<Chunk>();
    }

    auto payload = dynamicPtrCast<const RPMMeasurement>(frontChunk);
    if (payload == nullptr) {
        ++droppedPackets;
        EV_WARN << "Relay " << relayIndex + 1 << " dropped a packet without an RPMMeasurement payload" << endl;
        delete packet;
        return;
    }

    const auto packetKey = std::make_pair(payload->getPatientId(), payload->getSeqNo());
    if (seenPackets.find(packetKey) != seenPackets.end()) {
        ++duplicatePackets;
        ++droppedPackets;
        EV_INFO << "Relay " << relayIndex + 1 << " dropped duplicate patient "
                << packetKey.first << " sequence " << packetKey.second << endl;
        delete packet;
        return;
    }

    if (payload->getDestinationId() != doctorId || payload->getPatientId() <= 0 ||
            payload->getSeqNo() <= 0) {
        ++droppedPackets;
        EV_WARN << "Relay " << relayIndex + 1 << " dropped a packet with invalid routing identity" << endl;
        delete packet;
        return;
    }

    const int hopLimit = std::min(maxHopCount, payload->getMaxHopCount());
    if (payload->getHopCount() >= hopLimit) {
        ++droppedPackets;
        EV_WARN << "Relay " << relayIndex + 1 << " dropped patient " << payload->getPatientId()
                << " sequence " << payload->getSeqNo() << " at hop limit " << hopLimit << endl;
        delete packet;
        return;
    }

    const auto &sourceTag = packet->findTag<MacAddressInd>();
    if (sourceTag == nullptr || sourceTag->getSrcAddress() == nextHopAddress) {
        ++droppedPackets;
        EV_WARN << "Relay " << relayIndex + 1 << " refused to forward back to the previous hop" << endl;
        delete packet;
        return;
    }

    seenPackets.insert(packetKey);
    auto mutablePayload = packet->removeAtFront<RPMMeasurement>();
    mutablePayload->setHopCount(mutablePayload->getHopCount() + 1);
    packet->insertAtFront(mutablePayload);

    char packetName[80];
    std::snprintf(packetName, sizeof(packetName), "P%02d#%04ld HR%.0f O2%.0f T%.1f H%d",
            payload->getPatientId(), payload->getSeqNo(), payload->getHeartRate(),
            payload->getSpO2(), payload->getTemperature(), mutablePayload->getHopCount());
    packet->setName(packetName);
    packet->addTagIfAbsent<MacAddressReq>()->setDestAddress(nextHopAddress);

    getParentModule()->getDisplayString().setTagArg("i", 1, "orange");
    EV_INFO << "Relay " << relayIndex + 1 << " forwarding " << packetName
            << " to " << nextHopAddress << endl;
    send(packet, "socketOut");
}

void RPMRelayApp::finish()
{
    recordScalar("receivedPackets", receivedPackets);
    recordScalar("droppedPackets", droppedPackets);
    recordScalar("duplicatePackets", duplicatePackets);
}

} // namespace rpm_lora_research
