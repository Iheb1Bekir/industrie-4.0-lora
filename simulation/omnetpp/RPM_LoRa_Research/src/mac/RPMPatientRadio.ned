package rpm_lora_research.src.mac;

import flora.LoRa.LoRaRadio;

module RPMPatientRadio extends LoRaRadio
{
    parameters:
        double txPower @unit(W) = default(14dBm);
        int spreadingFactor = default(7);
        int codeRate = default(4);
        @class(RPMPatientRadio);
}
