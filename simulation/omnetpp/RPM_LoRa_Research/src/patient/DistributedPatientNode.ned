package rpm_lora_research.src.patient;

import inet.mobility.static.StationaryMobility;
import inet.networklayer.common.InterfaceTable;
import rpm_lora_research.src.mac.RPMLoRaNic;

module DistributedPatientNode
{
    parameters:
        int patientId = default(1);
        int doctorId = default(1);
        int nextHopRelayIndex = default(0);
        int maxHopCount = default(4);
        int warningSequence = default(0);
        int criticalSequence = default(0);
        int fallSequence = default(0);
        double baseHeartRate = default(72);
        double baseSpO2 = default(97);
        double baseTemperature = default(36.8);
        double samplingInterval @unit(s) = default(60s);
        double initialDelay @unit(s) = default(1s);
        double positionX @unit(m) = default(100m);
        double positionY @unit(m) = default(100m);
        double centerFrequency @unit(Hz) = default(868MHz);
        double bandwidth @unit(Hz) = default(125kHz);
        int spreadingFactor = default(7);
        int codeRate = default(4);
        double txPower @unit(W) = default(14dBm);
        @networkNode();
        *.interfaceTableModule = default(absPath(".interfaceTable"));
        @display("i=device/cellphone,blue");

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
        LoRaNic: RPMLoRaNic {
            parameters:
                mac.typename = "rpm_lora_research.src.mac.RPMRoutingLoRaMac";
                radio.typename = "rpm_lora_research.src.mac.RPMPatientRadio";
                radio.centerFrequency = parent.centerFrequency;
                radio.bandwidth = parent.bandwidth;
                radio.txPower = parent.txPower;
                radio.spreadingFactor = parent.spreadingFactor;
                radio.codeRate = parent.codeRate;
                radio.receiver.sensitivity = -123dBm;
                radio.transmitter.power = parent.txPower;
                @display("p=150,180");
        }
        app: DistributedPatientApp {
            parameters:
                patientId = parent.patientId;
                doctorId = parent.doctorId;
                nextHopRelayIndex = parent.nextHopRelayIndex;
                maxHopCount = parent.maxHopCount;
                warningSequence = parent.warningSequence;
                criticalSequence = parent.criticalSequence;
                fallSequence = parent.fallSequence;
                baseHeartRate = parent.baseHeartRate;
                baseSpO2 = parent.baseSpO2;
                baseTemperature = parent.baseTemperature;
                samplingInterval = parent.samplingInterval;
                initialDelay = parent.initialDelay;
                centerFrequency = parent.centerFrequency;
                bandwidth = parent.bandwidth;
                spreadingFactor = parent.spreadingFactor;
                codeRate = parent.codeRate;
                txPower = parent.txPower;
                @display("p=250,60");
        }

    connections allowunconnected:
        app.socketOut --> LoRaNic.upperLayerIn;
        LoRaNic.upperLayerOut --> app.socketIn;
}
