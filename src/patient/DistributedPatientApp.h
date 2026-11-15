#ifndef __RPM_DISTRIBUTEDPATIENTAPP_H_
#define __RPM_DISTRIBUTEDPATIENTAPP_H_

#include <omnetpp.h>
#include "inet/common/packet/Packet.h"
#include "inet/common/InitStages.h"
#include "inet/linklayer/common/MacAddress.h"
#include "../messages/RPMMeasurement_m.h"

using namespace omnetpp;
using namespace inet;

namespace rpm_lora_research {

class DistributedPatientApp : public cSimpleModule
{
  protected:
    cMessage *sendMeasurementTimer = nullptr;
    int patientId = 0;
    int doctorId = 1;
    int warningSequence = 0;
    int criticalSequence = 0;
    int fallSequence = 0;
    int maxHopCount = 0;
    double baseHeartRate = 72;
    double baseSpO2 = 97;
    double baseTemperature = 36.8;
    long sequenceNumber = 0;
    long generatedPackets = 0;
    long transmittedPackets = 0;
    simtime_t samplingInterval;
    MacAddress nextHopAddress;

    int numInitStages() const override { return inet::NUM_INIT_STAGES; }
    void initialize(int stage) override;
    void handleMessage(cMessage *message) override;
    void finish() override;

    void sendMeasurement();

  public:
    ~DistributedPatientApp() override;
};

} // namespace rpm_lora_research

#endif
