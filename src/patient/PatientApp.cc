#include "PatientApp.h"
#include "inet/common/packet/Packet.h"
#include "inet/common/Units.h"
#include "inet/linklayer/common/MacAddress.h"
#include "inet/linklayer/common/MacAddressTag_m.h"
#include "inet/common/ProtocolTag_m.h"
#include "inet/common/packet/chunk/FieldsChunk.h"

#include "LoRa/LoRaTagInfo_m.h"

namespace rpm_lora_research {

Define_Module(PatientApp);

void PatientApp::initialize(int stage)
{
    if (stage == INITSTAGE_APPLICATION_LAYER) {
        patientId = par("patientId").intValue();
        doctorId = par("doctorId").intValue();
        samplingInterval = par("samplingInterval");
        sendMeasurementTimer = new cMessage("sendMeasurementTimer");
        scheduleAt(simTime() + samplingInterval, sendMeasurementTimer);
    }
}

void PatientApp::handleMessage(cMessage *msg)
{
    if (msg == sendMeasurementTimer) {
        sendMeasurement();
        scheduleAt(simTime() + samplingInterval, sendMeasurementTimer);
    }
    else {
        delete msg;
    }
}

void PatientApp::finish()
{
    recordScalar("generatedPackets", generatedPackets);
    recordScalar("transmittedPackets", transmittedPackets);
    recordScalar("patientId", patientId);
}

void PatientApp::sendMeasurement()
{
    auto packet = new Packet("RPMMeasurement");
    auto payload = makeShared<RPMMeasurement>();

    payload->setPatientId(patientId);
    payload->setSeqNo(++sequenceNumber);
    payload->setTimestamp(simTime());
    payload->setHeartRate(72.0 + patientId * 0.8);
    payload->setSpO2(97.0 - patientId * 0.1);
    payload->setTemperature(36.8 + patientId * 0.05);
    payload->setFallDetected(false);
    payload->setAlertLevel(0);
    payload->setRoutingMode(0);
    payload->setSourceId(patientId);
    payload->setDestinationId(doctorId);
    payload->setHopCount(0);
    payload->setMaxHopCount(1);
    payload->setCritical(false);

    payload->setChunkLength(B(70));
    packet->insertAtBack(payload);
    ++generatedPackets;

    auto loraTag = packet->addTagIfAbsent<flora::LoRaTag>();
    loraTag->setCenterFrequency(MHz(868));
    loraTag->setBandwidth(kHz(125));
    loraTag->setSpreadFactor(7);
    loraTag->setPower(mW(14));
    loraTag->setCodeRendundance(4);
    loraTag->setUseHeader(true);

    sendToLowerLayer(packet);
}

void PatientApp::sendToLowerLayer(Packet *packet)
{
    ++transmittedPackets;
    send(packet, "socketOut");
}

} // namespace rpm_lora_research
