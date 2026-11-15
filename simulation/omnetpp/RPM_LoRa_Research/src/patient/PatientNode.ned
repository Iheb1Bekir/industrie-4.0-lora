package rpm_lora_research.src.patient;

import inet.mobility.static.StationaryMobility;
import inet.networklayer.common.InterfaceTable;
import rpm_lora_research.src.mac.RPMLoRaNic;

module PatientNode
{
    parameters:
        int patientId = default(1);
        int doctorId = default(1);
        volatile double samplingInterval @unit(s) = default(5s);
        @networkNode();
        *.interfaceTableModule = default(absPath(".interfaceTable"));
        @display("bgb=300,250;i=device/cellphone");

    submodules:
        interfaceTable: InterfaceTable {
            @display("p=30,20");
        }
        mobility: StationaryMobility {
            @display("p=30,120");
        }
        LoRaNic: RPMLoRaNic {
            parameters:
                mac.typename = "rpm_lora_research.src.mac.RPMLoRaMac";
                radio.centerFrequency = 868MHz;
                radio.bandwidth = 125kHz;
                radio.transmitter.centerFrequency = 868MHz;
                radio.transmitter.bandwidth = 125kHz;
                radio.receiver.centerFrequency = 868MHz;
                radio.receiver.bandwidth = 125kHz;
                radio.receiver.sensitivity = -137dBm;
                radio.transmitter.power = 14dBm;
                @display("p=150,180");
        }
        app: PatientApp {
            parameters:
                patientId = parent.patientId;
                doctorId = parent.doctorId;
                samplingInterval = parent.samplingInterval;
                @display("p=250,60");
        }

    connections allowunconnected:
        app.socketOut --> LoRaNic.upperLayerIn;
        LoRaNic.upperLayerOut --> app.socketIn;
}