#ifndef __RPM_PATIENTAPP_H_
#define __RPM_PATIENTAPP_H_

#include <omnetpp.h>
#include "inet/common/packet/Packet.h"
#include "inet/common/ModuleAccess.h"
#include "inet/common/InitStages.h"
#include "../messages/RPMMeasurement_m.h"
#include "LoRa/LoRaTagInfo_m.h"

using namespace omnetpp;
using namespace inet;

namespace rpm_lora_research {

class PatientApp : public cSimpleModule
{
  protected:
    cMessage *sendMeasurementTimer = nullptr;
    int patientId = 0;
    long sequenceNumber = 0;
    int generatedPackets = 0;
    int transmittedPackets = 0;
    int doctorId = 1;
    simtime_t samplingInterval;

    int numInitStages() const override { return inet::NUM_INIT_STAGES; }
    void initialize(int stage) override;
    void handleMessage(cMessage *msg) override;
    void finish() override;

    void sendMeasurement();
    void sendToLowerLayer(Packet *packet);

  public:
    PatientApp() {}
};

} // namespace rpm_lora_research

#endif
