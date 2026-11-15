package rpm_lora_research.src.topology;

import flora.LoRaPhy.LoRaMedium;
import rpm_lora_research.src.patient.PatientNode;
import rpm_lora_research.src.doctor.DoctorNode;

network DirectRPMNetwork
{
    parameters:
        @display("bgb=500,300");

    submodules:
        patient: PatientNode {
            @display("p=100,100");
        }
        doctor: DoctorNode {
            @display("p=300,100");
        }
        loRaMedium: LoRaMedium {
            @display("p=200,30");
        }

    connections allowunconnected:
}