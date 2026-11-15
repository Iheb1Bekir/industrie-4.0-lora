#include "RPMRoutingLoRaMac.h"
#include "inet/linklayer/common/MacAddressTag_m.h"
#include "LoRa/LoRaMacFrame_m.h"

namespace rpm_lora_research {

Define_Module(RPMRoutingLoRaMac);

inet::Packet *RPMRoutingLoRaMac::encapsulate(inet::Packet *packet)
{
    const auto &destinationTag = packet->findTag<inet::MacAddressReq>();
    inet::MacAddress destination;
    const bool hasDestination = destinationTag != nullptr;
    if (hasDestination)
        destination = destinationTag->getDestAddress();

    auto encapsulatedPacket = flora::LoRaMac::encapsulate(packet);
    if (hasDestination) {
        auto frame = encapsulatedPacket->removeAtFront<flora::LoRaMacFrame>();
        frame->setReceiverAddress(destination);
        encapsulatedPacket->insertAtFront(frame);
    }
    return encapsulatedPacket;
}

} // namespace rpm_lora_research
