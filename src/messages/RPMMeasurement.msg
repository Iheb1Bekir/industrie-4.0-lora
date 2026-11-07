import inet.common.INETDefs;
import inet.common.packet.chunk.Chunk;

namespace rpm_lora_research;

class RPMMeasurement extends inet::FieldsChunk
{
    int patientId = 0;
    long seqNo = 0;
    simtime_t timestamp = 0;
    double heartRate = 0;
    double spO2 = 0;
    double temperature = 0;
    bool fallDetected = false;
    int alertLevel = 0;
    int routingMode = 0;
    int sourceId = 0;
    int destinationId = 0;
    int hopCount = 0;
    int maxHopCount = 0;
    bool critical = false;
}
