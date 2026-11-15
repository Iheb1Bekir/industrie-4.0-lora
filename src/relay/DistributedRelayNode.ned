package rpm_lora_research.src.relay;

import inet.mobility.static.StationaryMobility;
import inet.networklayer.common.InterfaceTable;
import rpm_lora_research.src.mac.RPMGatewayNic;

module DistributedRelayNode
{
    parameters:
        int relayIndex = default(0);
        int nextHopRelayIndex = default(-1);
        int doctorId = default(1);
        int maxHopCount = default(4);
        double positionX @unit(m) = default(1500m);
        double positionY @unit(m) = default(300m);
        double centerFrequency @unit(Hz) = default(868MHz);
        double bandwidth @unit(Hz) = default(125kHz);
        double txPower @unit(W) = default(14dBm);
        @networkNode();
        *.interfaceTableModule = default(absPath(".interfaceTable"));
        @display("i=device/antennatower,orange");

    submodules:
        interfaceTable: InterfaceTable {
            @display("p=30,20");
        }
        mobility: StationaryMobility {
            parameters:
                initialX = parent.positionX;
                initialY = parent.positionY;
                initFromDisplayString = false;
                updateFromDisplayString = false;
                @display("p=30,120");
        }
        LoRaNic: RPMGatewayNic {
            parameters:
                macType = "rpm_lora_research.src.mac.RPMRelayMac";
                radio.centerFrequency = parent.centerFrequency;
                radio.bandwidth = parent.bandwidth;
                radio.receiver.sensitivity = -123dBm;
                radio.transmitter.power = parent.txPower;
                @display("p=150,180");
        }
        app: RPMRelayApp {
            parameters:
                relayIndex = parent.relayIndex;
                nextHopRelayIndex = parent.nextHopRelayIndex;
                doctorId = parent.doctorId;
                maxHopCount = parent.maxHopCount;
                @display("p=250,60");
        }

    connections allowunconnected:
        app.socketOut --> LoRaNic.upperLayerIn;
        LoRaNic.upperLayerOut --> app.socketIn;
}
