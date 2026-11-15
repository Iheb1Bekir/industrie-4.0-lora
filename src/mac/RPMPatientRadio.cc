#include "RPMPatientRadio.h"
#include "inet/common/INETMath.h"

namespace rpm_lora_research {

Define_Module(RPMPatientRadio);

void RPMPatientRadio::initialize(int stage)
{
    flora::LoRaRadio::initialize(stage);

    if (stage == INITSTAGE_LOCAL) {
        loRaTP = inet::math::mW2dBmW(par("txPower").doubleValueInUnit("mW"));
        loRaCF = Hz(par("centerFrequency"));
        loRaSF = par("spreadingFactor").intValue();
        loRaBW = Hz(par("bandwidth"));
        loRaCR = par("codeRate").intValue();
        loRaUseHeader = true;
    }
}

void RPMPatientRadio::finish()
{
    recordScalar("loraTransmitterPower_dBm", loRaTP);
    flora::LoRaRadio::finish();
}

} // namespace rpm_lora_research
