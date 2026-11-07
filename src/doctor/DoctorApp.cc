#include "DoctorApp.h"
#include "inet/common/packet/Packet.h"
#include "LoRa/LoRaMacFrame_m.h"
#include "../messages/RPMMeasurement_m.h"
#include "LoRa/LoRaMacFrame_m.h"

namespace rpm_lora_research {

Define_Module(DoctorApp);

void DoctorApp::initialize(int stage)
{
    if (stage == INITSTAGE_APPLICATION_LAYER) {
        doctorId = par("doctorId").intValue();
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
    packet->popAtFront<flora::LoRaMacFrame>();
    packet->popAtFront<flora::LoRaMacFrame>();
    auto payload = packet->peekAtFront<RPMMeasurement>();

    if (payload == nullptr) {
        ++invalidPackets;
        EV << "DoctorApp: invalid payload" << endl;
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
        EV << "DoctorApp: bad patient ID" << endl;
        return;
    }

    if (payload->getSeqNo() <= 0) {
        ++invalidPackets;
        EV << "DoctorApp: bad sequence number" << endl;
        return;
    }

    ++validPackets;
    EV << "DoctorApp: valid measurement received for patient " << payload->getPatientId()
       << " seq " << payload->getSeqNo() << endl;
}

} // namespace rpm_lora_research
