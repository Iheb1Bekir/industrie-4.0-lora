package rpm_lora_research.src.topology;

import flora.LoRaPhy.LoRaMedium;
import rpm_lora_research.src.doctor.DistributedDoctorNode;
import rpm_lora_research.src.patient.DistributedPatientNode;
import rpm_lora_research.src.relay.DistributedRelayNode;

network DistributedRPMNetwork
{
    parameters:
        int innerPatientCount = default(8);
        int middlePatientCount = default(8);
        int outerPatientCount = default(4);
        int numPatients = default(innerPatientCount + middlePatientCount + outerPatientCount);
        int numRelays = default(3);
        int doctorId = default(1);
        int maxHopCount = default(4);
        double samplingInterval @unit(s) = default(60s);
        double centerFrequency @unit(Hz) = default(868MHz);
        double bandwidth @unit(Hz) = default(125kHz);
        double txPower @unit(W) = default(14dBm);
        int spreadingFactor = default(7);
        int codeRate = default(4);
        double deploymentCenterX @unit(m) = default(300m);
        double deploymentCenterY @unit(m) = default(300m);
        double innerPatientRadius @unit(m) = default(25m);
        double middlePatientRadius @unit(m) = default(45m);
        double outerPatientRadius @unit(m) = default(80m);
        double relayRadius @unit(m) = default(30m);
        double displayCenterX = default(600);
        double displayCenterY = default(480);
        double innerDisplayRadius = default(140);
        double middleDisplayRadius = default(280);
        double outerDisplayRadius = default(420);
        double relayDisplayRadius = default(340);
        @figure[innerDeploymentRing](type=oval; pos=460,340; size=280,280; lineColor=#a8bac9; lineOpacity=0.45; lineStyle=dashed; fillOpacity=0; zIndex=-100);
        @figure[middleDeploymentRing](type=oval; pos=320,200; size=560,560; lineColor=#a8bac9; lineOpacity=0.45; lineStyle=dashed; fillOpacity=0; zIndex=-100);
        @figure[outerDeploymentRing](type=oval; pos=180,60; size=840,840; lineColor=#a8bac9; lineOpacity=0.45; lineStyle=dashed; fillOpacity=0; zIndex=-100);

    submodules:
        patients[numPatients]: DistributedPatientNode {
            parameters:
                patientId = index + 1;
                doctorId = parent.doctorId;
                nextHopRelayIndex = index < parent.innerPatientCount + parent.middlePatientCount ? -1 : int(min(parent.numRelays - 1, (index - parent.innerPatientCount - parent.middlePatientCount) * parent.numRelays / parent.outerPatientCount));
                maxHopCount = parent.maxHopCount;
                warningSequence = index == 6 ? 2 : 0;
                criticalSequence = index == 19 ? 2 : 0;
                fallSequence = index == 19 ? 3 : 0;
                baseHeartRate = 68 + (index % 7) * 2;
                baseSpO2 = 95 + (index % 5) * 0.8;
                baseTemperature = 36.4 + (index % 6) * 0.1;
                samplingInterval = parent.samplingInterval;
                initialDelay = 1s + index * 1.5s;
                positionX = parent.deploymentCenterX + (index < parent.innerPatientCount ? parent.innerPatientRadius * cos(2 * acos(-1) * index / parent.innerPatientCount) : index < parent.innerPatientCount + parent.middlePatientCount ? parent.middlePatientRadius * cos(2 * acos(-1) * (index - parent.innerPatientCount) / parent.middlePatientCount + acos(-1) / parent.middlePatientCount) : parent.outerPatientRadius * cos(2 * acos(-1) * (index - parent.innerPatientCount - parent.middlePatientCount) / parent.outerPatientCount));
                positionY = parent.deploymentCenterY + (index < parent.innerPatientCount ? parent.innerPatientRadius * sin(2 * acos(-1) * index / parent.innerPatientCount) : index < parent.innerPatientCount + parent.middlePatientCount ? parent.middlePatientRadius * sin(2 * acos(-1) * (index - parent.innerPatientCount) / parent.middlePatientCount + acos(-1) / parent.middlePatientCount) : parent.outerPatientRadius * sin(2 * acos(-1) * (index - parent.innerPatientCount - parent.middlePatientCount) / parent.outerPatientCount));
                centerFrequency = parent.centerFrequency;
                bandwidth = parent.bandwidth;
                txPower = parent.txPower;
                spreadingFactor = parent.spreadingFactor;
                codeRate = parent.codeRate;
                @display("p=${parent.displayCenterX + (index < parent.innerPatientCount ? parent.innerDisplayRadius * cos(2 * acos(-1) * index / parent.innerPatientCount) : index < parent.innerPatientCount + parent.middlePatientCount ? parent.middleDisplayRadius * cos(2 * acos(-1) * (index - parent.innerPatientCount) / parent.middlePatientCount + acos(-1) / parent.middlePatientCount) : parent.outerDisplayRadius * cos(2 * acos(-1) * (index - parent.innerPatientCount - parent.middlePatientCount) / parent.outerPatientCount)},${parent.displayCenterY + (index < parent.innerPatientCount ? parent.innerDisplayRadius * sin(2 * acos(-1) * index / parent.innerPatientCount) : index < parent.innerPatientCount + parent.middlePatientCount ? parent.middleDisplayRadius * sin(2 * acos(-1) * (index - parent.innerPatientCount) / parent.middlePatientCount + acos(-1) / parent.middlePatientCount) : parent.outerDisplayRadius * sin(2 * acos(-1) * (index - parent.innerPatientCount - parent.middlePatientCount) / parent.outerPatientCount))}");
        }
        relay[numRelays]: DistributedRelayNode {
            parameters:
                relayIndex = index;
                nextHopRelayIndex = index < parent.numRelays - 1 ? index + 1 : -1;
                doctorId = parent.doctorId;
                maxHopCount = parent.maxHopCount;
                positionX = parent.deploymentCenterX + parent.relayRadius * cos(acos(-1) / 6 + 2 * acos(-1) * index / parent.numRelays);
                positionY = parent.deploymentCenterY + parent.relayRadius * sin(acos(-1) / 6 + 2 * acos(-1) * index / parent.numRelays);
                centerFrequency = parent.centerFrequency;
                bandwidth = parent.bandwidth;
                txPower = parent.txPower;
                @display("p=${parent.displayCenterX + parent.relayDisplayRadius * cos(acos(-1) / 6 + 2 * acos(-1) * index / parent.numRelays)},${parent.displayCenterY + parent.relayDisplayRadius * sin(acos(-1) / 6 + 2 * acos(-1) * index / parent.numRelays)}");
        }
        doctor: DistributedDoctorNode {
            parameters:
                doctorId = parent.doctorId;
                positionX = parent.deploymentCenterX;
                positionY = parent.deploymentCenterY;
                centerFrequency = parent.centerFrequency;
                bandwidth = parent.bandwidth;
                txPower = parent.txPower;
                @display("p=${parent.displayCenterX},${parent.displayCenterY}");
        }
        loRaMedium: LoRaMedium {
            @display("p=${parent.displayCenterX},30");
        }

    connections allowunconnected:
}
