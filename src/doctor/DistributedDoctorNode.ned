package rpm_lora_research.src.doctor;

import inet.mobility.static.StationaryMobility;
import inet.networklayer.common.InterfaceTable;
import rpm_lora_research.src.mac.RPMGatewayNic;

module DistributedDoctorNode
{
    parameters:
        int doctorId = default(1);
        double positionX @unit(m) = default(2600m);
        double positionY @unit(m) = default(300m);
        double centerFrequency @unit(Hz) = default(868MHz);
        double bandwidth @unit(Hz) = default(125kHz);
        double txPower @unit(W) = default(14dBm);
        @networkNode();
        *.interfaceTableModule = default(absPath(".interfaceTable"));
        @display("i=misc/sensorgateway,green;t=Doctor Gateway");

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
                macType = "rpm_lora_research.src.mac.RPMDoctorMac";
                radio.centerFrequency = parent.centerFrequency;
                radio.bandwidth = parent.bandwidth;
                radio.receiver.sensitivity = -123dBm;
                radio.transmitter.power = parent.txPower;
                @display("p=150,180");
        }
        app: DistributedDoctorApp {
            parameters:
                doctorId = parent.doctorId;
                @display("p=250,60");
        }

    connections allowunconnected:
        app.socketOut --> LoRaNic.upperLayerIn;
        LoRaNic.upperLayerOut --> app.socketIn;
}
