#include "DistributedDoctorApp.h"
#include "LoRa/LoRaMacFrame_m.h"
#include "../messages/RPMMeasurement_m.h"

#include <cstdio>

namespace rpm_lora_research {

Define_Module(DistributedDoctorApp);

void DistributedDoctorApp::initialize(int stage)
{
    DoctorApp::initialize(stage);
    if (stage == INITSTAGE_APPLICATION_LAYER) {
        endToEndDelayVector.setName("endToEndDelay");
        getParentModule()->getDisplayString().setTagArg("t", 0, "DoctorGateway");
    }
}

void DistributedDoctorApp::processIncomingPacket(Packet *packet)
{
    const auto &frontChunk = packet->peekAtFront<Chunk>();
    const auto macFrame = dynamicPtrCast<const flora::LoRaMacFrame>(frontChunk);
    if (macFrame != nullptr)
        packet->popAtFront<flora::LoRaMacFrame>();

    const auto &payloadChunk = packet->peekAtFront<Chunk>();
    const auto payload = dynamicPtrCast<const RPMMeasurement>(payloadChunk);
    if (payload != nullptr && payload->getDestinationId() == doctorId &&
            payload->getPatientId() > 0 && payload->getSeqNo() > 0) {
        const auto packetKey = std::make_pair(payload->getPatientId(), payload->getSeqNo());
        if (seenPackets.find(packetKey) != seenPackets.end()) {
            ++receivedPackets;
            ++duplicatePackets;
            ++droppedPackets;
            EV_INFO << "DoctorGateway dropped duplicate patient " << packetKey.first
                    << " sequence " << packetKey.second << endl;
            return;
        }
    }

    const int previousValidCount = validPackets;
    const int previousInvalidCount = invalidPackets;
    DoctorApp::processIncomingPacket(packet);
    if (validPackets == previousValidCount) {
        if (invalidPackets > previousInvalidCount)
            ++droppedPackets;
        return;
    }

    const auto &validPayload = packet->peekAtFront<RPMMeasurement>();
    const auto packetKey = std::make_pair(validPayload->getPatientId(), validPayload->getSeqNo());
    seenPackets.insert(packetKey);
    ++packetsPerPatient[validPayload->getPatientId()];
    if (validPayload->getRoutingMode() == 0)
        ++directPackets;
    else
        ++relayAssistedPackets;
    endToEndDelayVector.record((simTime() - validPayload->getTimestamp()).dbl());

    if (validPayload->getFallDetected())
        ++fallAlerts;
    if (validPayload->getCritical() || validPayload->getAlertLevel() >= 2) {
        ++criticalAlerts;
        getParentModule()->getDisplayString().setTagArg("i", 1, "red");
    }
    else if (validPayload->getAlertLevel() == 1)
        ++warningAlerts;
    else if (!validPayload->getFallDetected())
        ++normalAlerts;
}

void DistributedDoctorApp::finish()
{
    DoctorApp::finish();
    recordScalar("duplicatePackets", duplicatePackets);
    recordScalar("droppedPackets", droppedPackets);
    recordScalar("forwardedPackets", forwardedPackets);
    recordScalar("normalAlerts", normalAlerts);
    recordScalar("warningAlerts", warningAlerts);
    recordScalar("criticalAlerts", criticalAlerts);
    recordScalar("fallAlerts", fallAlerts);
    recordScalar("directPackets", directPackets);
    recordScalar("relayAssistedPackets", relayAssistedPackets);
    for (const auto& entry : packetsPerPatient) {
        char scalarName[64];
        std::snprintf(scalarName, sizeof(scalarName), "validPackets_patient_%d", entry.first);
        recordScalar(scalarName, entry.second);
    }
}

} // namespace rpm_lora_research
