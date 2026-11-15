package rpm_lora_research.src.doctor;

import inet.mobility.static.StationaryMobility;
import inet.networklayer.common.InterfaceTable;
import flora.LoRa.LoRaGWNic;

module DoctorNode
{
    parameters:
        int doctorId = default(1);
        @networkNode();
        *.interfaceTableModule = default(absPath(".interfaceTable"));
        @display("bgb=300,250;i=device/doctor");

    submodules:
        interfaceTable: InterfaceTable {
            @display("p=30,20");
        }
        mobility: StationaryMobility {
            @display("p=30,120");
        }
        LoRaNic: LoRaGWNic {
            parameters:
                radio.centerFrequency = 868MHz;
                radio.bandwidth = 125kHz;
                @display("p=150,180");
        }
        app: DoctorApp {
            parameters:
                doctorId = parent.doctorId;
                @display("p=250,60");
        }

    connections allowunconnected:
        app.socketOut --> LoRaNic.upperLayerIn;
        LoRaNic.upperLayerOut --> app.socketIn;
}