package rpm_lora_research.src.mac;

import inet.linklayer.common.WirelessInterface;

module RPMGatewayNic extends WirelessInterface
{
    parameters:
        string macType = default("rpm_lora_research.src.mac.RPMRelayMac");
        *.interfaceTableModule = default(absPath(this.interfaceTableModule));
        radio.typename = default("LoRaGWRadio");
        radio.antenna.mobilityModule = "^.^.^.mobility";
        radio.transmitter.typename = "LoRaTransmitter";
        radio.transmitter.headerLength = 0B;
        radio.receiver.typename = "LoRaReceiver";
        mac.typename = default(macType);
        queue.typename = default("DropTailQueue");
        queue.packetCapacity = default(-1);
}
