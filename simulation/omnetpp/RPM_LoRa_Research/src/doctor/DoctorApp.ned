package rpm_lora_research.src.doctor;

import inet.applications.contract.IApp;

simple DoctorApp like IApp
{
    parameters:
        int doctorId = default(1);
        @display("i=block/sink");
    gates:
        input socketIn;
        output socketOut;
}