package rpm_lora_research.src.relay;

import inet.applications.contract.IApp;

simple RPMRelayApp like IApp
{
    parameters:
        int relayIndex = default(0);
        int nextHopRelayIndex = default(-1);
        int doctorId = default(1);
        int maxHopCount = default(4);
        @display("i=block/forward");
    gates:
        input socketIn;
        output socketOut;
}
