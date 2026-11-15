#include "DistributedPatientApp.h"
#include "inet/common/Units.h"
#include "inet/linklayer/common/MacAddressTag_m.h"
#include "LoRa/LoRaTagInfo_m.h"

#include <cstdio>

namespace rpm_lora_research {

Define_Module(DistributedPatientApp);

void DistributedPatientApp::initialize(int stage)
{
    if (stage == INITSTAGE_APPLICATION_LAYER) {
        patientId = par("patientId").intValue();
        doctorId = par("doctorId").intValue();
        warningSequence = par("warningSequence").intValue();
        criticalSequence = par("criticalSequence").intValue();
        fallSequence = par("fallSequence").intValue();
        maxHopCount = par("maxHopCount").intValue();
        baseHeartRate = par("baseHeartRate").doubleValue();
        baseSpO2 = par("baseSpO2").doubleValue();
        baseTemperature = par("baseTemperature").doubleValue();
        samplingInterval = par("samplingInterval");

        const int nextHopIndex = par("nextHopRelayIndex").intValue();
        auto network = getParentModule()->getParentModule();
        cModule *nextHop = nextHopIndex < 0
                ? network->getSubmodule("doctor")
                : network->getSubmodule("relay", nextHopIndex);
        if (nextHop == nullptr)
            throw cRuntimeError("Patient %d has invalid next-hop relay index %d", patientId, nextHopIndex);
        auto nextHopMac = nextHop->getSubmodule("LoRaNic")->getSubmodule("mac");
        nextHopAddress.setAddress(nextHopMac->par("address").stringValue());

        sendMeasurementTimer = new cMessage("sendMeasurementTimer");
        scheduleAt(simTime() + par("initialDelay"), sendMeasurementTimer);

        char displayName[32];
        std::snprintf(displayName, sizeof(displayName), "Patient_%02d", patientId);
        getParentModule()->getDisplayString().setTagArg("t", 0, displayName);
    }
}

void DistributedPatientApp::handleMessage(cMessage *message)
{
    if (message == sendMeasurementTimer) {
        sendMeasurement();
        scheduleAt(simTime() + samplingInterval, sendMeasurementTimer);
    }
    else
        delete message;
}

void DistributedPatientApp::finish()
{
    recordScalar("generatedPackets", generatedPackets);
    recordScalar("transmittedPackets", transmittedPackets);
    recordScalar("patientId", patientId);
}

void DistributedPatientApp::sendMeasurement()
{
    auto packet = new Packet();
    auto payload = makeShared<RPMMeasurement>();
    const long seqNo = ++sequenceNumber;
    const bool warning = warningSequence > 0 && seqNo == warningSequence;
    const bool critical = criticalSequence > 0 && seqNo == criticalSequence;
    const bool fallDetected = fallSequence > 0 && seqNo == fallSequence;
    const double heartRateVariation = static_cast<double>((patientId + seqNo) % 5) - 2.0;
    const double oxygenVariation = static_cast<double>((patientId + seqNo) % 3) - 1.0;

    payload->setPatientId(patientId);
    payload->setSeqNo(seqNo);
    payload->setTimestamp(simTime());
    payload->setHeartRate(baseHeartRate + heartRateVariation);
    payload->setSpO2(baseSpO2 + oxygenVariation * 0.2);
    payload->setTemperature(baseTemperature + ((patientId + seqNo) % 3 - 1) * 0.05);
    payload->setFallDetected(fallDetected);
    payload->setAlertLevel(fallDetected ? 3 : critical ? 2 : warning ? 1 : 0);
    payload->setRoutingMode(par("nextHopRelayIndex").intValue() < 0 ? 0 : 1);
    payload->setSourceId(patientId);
    payload->setDestinationId(doctorId);
    payload->setHopCount(0);
    payload->setMaxHopCount(maxHopCount);
    payload->setCritical(critical || fallDetected);

    if (warning) {
        payload->setHeartRate(118.0);
        payload->setSpO2(92.0);
    }
    if (critical) {
        payload->setHeartRate(148.0);
        payload->setSpO2(87.0);
        payload->setTemperature(39.1);
    }
    if (fallDetected) {
        payload->setHeartRate(132.0);
        payload->setFallDetected(true);
    }

    payload->setChunkLength(B(70));
    packet->insertAtBack(payload);
    ++generatedPackets;

    char packetName[80];
    const char *alertType = fallDetected ? "FALL" : critical ? "CRITICAL" : warning ? "WARNING" : "NORMAL";
    std::snprintf(packetName, sizeof(packetName), "P%02d#%04ld HR%.0f O2%.0f T%.1f H0 %s",
            patientId, seqNo, payload->getHeartRate(), payload->getSpO2(), payload->getTemperature(), alertType);
    packet->setName(packetName);

    auto macAddressReq = packet->addTagIfAbsent<MacAddressReq>();
    macAddressReq->setDestAddress(nextHopAddress);

    auto loraTag = packet->addTagIfAbsent<flora::LoRaTag>();
    loraTag->setCenterFrequency(Hz(par("centerFrequency")));
    loraTag->setBandwidth(Hz(par("bandwidth")));
    loraTag->setSpreadFactor(par("spreadingFactor").intValue());
    loraTag->setPower(W(par("txPower")));
    loraTag->setCodeRendundance(par("codeRate").intValue());
    loraTag->setUseHeader(true);

    auto& displayString = getParentModule()->getDisplayString();
    displayString.setTagArg("i", 1, fallDetected || critical ? "red" : warning ? "orange" : "blue");
    EV_INFO << "Generated " << packetName << " HR=" << payload->getHeartRate()
            << " SpO2=" << payload->getSpO2()
            << " temperature=" << payload->getTemperature() << endl;

    ++transmittedPackets;
    send(packet, "socketOut");
}

DistributedPatientApp::~DistributedPatientApp()
{
    cancelAndDelete(sendMeasurementTimer);
}

} // namespace rpm_lora_research
