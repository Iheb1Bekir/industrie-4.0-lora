package rpm_lora_research.src.patient;

import inet.applications.contract.IApp;

simple PatientApp like IApp
{
    parameters:
        int patientId = default(1);
        int doctorId = default(1);
        volatile double samplingInterval @unit(s) = default(5s);
        @display("i=block/source");
    gates:
        input socketIn;
        output socketOut;
}