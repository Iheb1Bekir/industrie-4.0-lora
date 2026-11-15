package rpm_lora_research.src.patient;

import inet.applications.contract.IApp;

simple DistributedPatientApp like IApp
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
        volatile double samplingInterval @unit(s) = default(60s);
        double initialDelay @unit(s) = default(1s);
        double centerFrequency @unit(Hz) = default(868MHz);
        double bandwidth @unit(Hz) = default(125kHz);
        int spreadingFactor = default(7);
        int codeRate = default(4);
        double txPower @unit(W) = default(14dBm);
        @display("i=block/source");
    gates:
        input socketIn;
        output socketOut;
}
