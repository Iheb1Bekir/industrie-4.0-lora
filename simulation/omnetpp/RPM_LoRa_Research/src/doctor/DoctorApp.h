#ifndef __RPM_DOCTORAPP_H_
#define __RPM_DOCTORAPP_H_

#include <omnetpp.h>
#include "inet/common/packet/Packet.h"
#include "inet/common/InitStages.h"
#include "../messages/RPMMeasurement_m.h"

using namespace omnetpp;
using namespace inet;

namespace rpm_lora_research {

class DoctorApp : public cSimpleModule
{
  protected:
    int receivedPackets = 0;
    int validPackets = 0;
    int invalidPackets = 0;
    int doctorId = 1;

    cOutVector patientIdVector;
    cOutVector sequenceNumberVector;
    cOutVector measurementTimestampVector;
    cOutVector heartRateVector;
    cOutVector spO2Vector;
    cOutVector temperatureVector;
    cOutVector fallDetectedVector;
    cOutVector alertLevelVector;
    cOutVector hopCountVector;

    int numInitStages() const override { return inet::NUM_INIT_STAGES; }
    void initialize(int stage) override;
    void handleMessage(cMessage *msg) override;
    void finish() override;

    virtual void processIncomingPacket(Packet *packet);

  public:
    DoctorApp() {}
};

} // namespace rpm_lora_research

#endif
