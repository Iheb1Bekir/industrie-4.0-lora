#include "DoctorApp.h"
#include "inet/common/packet/Packet.h"
#include "LoRa/LoRaMacFrame_m.h"
#include "../messages/RPMMeasurement_m.h"

namespace rpm_lora_research {

Define_Module(DoctorApp);

void DoctorApp::initialize(int stage)
{
    if (stage == INITSTAGE_APPLICATION_LAYER) {
        doctorId = par("doctorId").intValue();

        patientIdVector.setName("patientId");
        sequenceNumberVector.setName("sequenceNumber");
        measurementTimestampVector.setName("measurementTimestamp");
        heartRateVector.setName("heartRate");
        spO2Vector.setName("spO2");
        temperatureVector.setName("temperature");
        fallDetectedVector.setName("fallDetected");
        alertLevelVector.setName("alertLevel");
        hopCountVector.setName("hopCount");
    }
}

void DoctorApp::handleMessage(cMessage *msg)
{
    if (msg->arrivedOn("socketIn")) {
        auto packet = check_and_cast<Packet *>(msg);
        processIncomingPacket(packet);
    }
    delete msg;
}

void DoctorApp::finish()
{
    recordScalar("receivedPackets", receivedPackets);
    recordScalar("validPackets", validPackets);
    recordScalar("invalidPackets", invalidPackets);
}

void DoctorApp::processIncomingPacket(Packet *packet)
{
    ++receivedPackets;

    // The FLoRa gateway MAC forwards the packet up after stripping the PHY preamble,
    // but the LoRa MAC header is still the first chunk at this point. We must remove
    // exactly one LoRaMacFrame before inspecting the application payload.
    const auto &frontChunk = packet->peekAtFront<Chunk>();
    const auto macFrame = dynamicPtrCast<const flora::LoRaMacFrame>(frontChunk);
    if (macFrame != nullptr) {
        packet->popAtFront<flora::LoRaMacFrame>();
        EV << "DoctorApp: removed LoRaMacFrame from received packet" << endl;
    }
    else {
        EV << "DoctorApp: no LoRaMacFrame present; packet may already have been decapsulated" << endl;
    }

    const auto &payloadChunk = packet->peekAtFront<Chunk>();
    auto payload = dynamicPtrCast<const RPMMeasurement>(payloadChunk);
    if (payload == nullptr) {
        ++invalidPackets;
        EV << "DoctorApp: invalid payload format; packet at upper layer is not RPMMeasurement" << endl;
        return;
    }

    if (payload->getDestinationId() != doctorId) {
        ++invalidPackets;
        EV << "DoctorApp: wrong destination ID observed; expected " << doctorId
           << ", got " << payload->getDestinationId() << endl;
        return;
    }

    if (payload->getPatientId() <= 0) {
        ++invalidPackets;
        EV << "DoctorApp: invalid patient ID " << payload->getPatientId() << endl;
        return;
    }

    if (payload->getSeqNo() <= 0) {
        ++invalidPackets;
        EV << "DoctorApp: invalid sequence number " << payload->getSeqNo() << endl;
        return;
    }

    ++validPackets;
    patientIdVector.record(payload->getPatientId());
    sequenceNumberVector.record(payload->getSeqNo());
    measurementTimestampVector.record(payload->getTimestamp().dbl());
    heartRateVector.record(payload->getHeartRate());
    spO2Vector.record(payload->getSpO2());
    temperatureVector.record(payload->getTemperature());
    fallDetectedVector.record(payload->getFallDetected() ? 1 : 0);
    alertLevelVector.record(payload->getAlertLevel());
    hopCountVector.record(payload->getHopCount());

    EV << "DoctorApp: valid measurement received for patient " << payload->getPatientId()
       << " seq " << payload->getSeqNo() << " heartRate=" << payload->getHeartRate()
       << " SpO2=" << payload->getSpO2() << " temp=" << payload->getTemperature() << endl;
}

} // namespace rpm_lora_research
