package rpm_lora_research.src.mac;

import inet.linklayer.common.WirelessInterface;

module RPMLoRaNic extends WirelessInterface
{
    parameters:
        @display("i=block/ifcard");
        *.interfaceTableModule = default(absPath(this.interfaceTableModule));

        radio.typename = default("LoRaRadio");
        radio.antenna.mobilityModule = "^.^.^.mobility";
        radio.transmitter.typename = "LoRaTransmitter";
        radio.transmitter.headerLength = 0B;
        radio.receiver.typename = "LoRaReceiver";

        mac.typename = "rpm_lora_research.src.mac.RPMLoRaMac";

        queue.typename = default("DropTailQueue");
        queue.packetCapacity = default(-1);
}
