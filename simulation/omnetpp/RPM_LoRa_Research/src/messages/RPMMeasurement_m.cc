//
// Generated file, do not edit! Created by opp_msgtool 6.5 from src/messages/RPMMeasurement.msg.
//

// Disable warnings about unused variables, empty switch stmts, etc:
#ifdef _MSC_VER
#  pragma warning(disable:4101)
#  pragma warning(disable:4065)
#endif

#if defined(__clang__)
#  pragma clang diagnostic ignored "-Wshadow"
#  pragma clang diagnostic ignored "-Wconversion"
#  pragma clang diagnostic ignored "-Wunused-parameter"
#  pragma clang diagnostic ignored "-Wc++98-compat"
#  pragma clang diagnostic ignored "-Wunreachable-code-break"
#  pragma clang diagnostic ignored "-Wold-style-cast"
#elif defined(__GNUC__)
#  pragma GCC diagnostic ignored "-Wshadow"
#  pragma GCC diagnostic ignored "-Wconversion"
#  pragma GCC diagnostic ignored "-Wunused-parameter"
#  pragma GCC diagnostic ignored "-Wold-style-cast"
#  pragma GCC diagnostic ignored "-Wsuggest-attribute=noreturn"
#  pragma GCC diagnostic ignored "-Wfloat-conversion"
#endif

#include <iostream>
#include <sstream>
#include <memory>
#include <type_traits>
#include "RPMMeasurement_m.h"

namespace omnetpp {

// Template pack/unpack rules. They are declared *after* a1l type-specific pack functions for multiple reasons.
// They are in the omnetpp namespace, to allow them to be found by argument-dependent lookup via the cCommBuffer argument

// Packing/unpacking an std::vector
template<typename T, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::vector<T,A>& v)
{
    int n = v.size();
    doParsimPacking(buffer, n);
    for (int i = 0; i < n; i++)
        doParsimPacking(buffer, v[i]);
}

template<typename T, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::vector<T,A>& v)
{
    int n;
    doParsimUnpacking(buffer, n);
    v.resize(n);
    for (int i = 0; i < n; i++)
        doParsimUnpacking(buffer, v[i]);
}

// std::vector<bool> elements are proxy objects (also for const access in libc++), so pack/unpack via a temporary
template<typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::vector<bool,A>& v)
{
    int n = v.size();
    doParsimPacking(buffer, n);
    for (int i = 0; i < n; i++) {
        bool x = v[i];
        doParsimPacking(buffer, x);
    }
}

template<typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::vector<bool,A>& v)
{
    int n;
    doParsimUnpacking(buffer, n);
    v.resize(n);
    for (int i = 0; i < n; i++) {
        bool x;
        doParsimUnpacking(buffer, x);
        v[i] = x;
    }
}

// Packing/unpacking an std::list
template<typename T, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::list<T,A>& l)
{
    doParsimPacking(buffer, (int)l.size());
    for (typename std::list<T,A>::const_iterator it = l.begin(); it != l.end(); ++it)
        doParsimPacking(buffer, (T&)*it);
}

template<typename T, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::list<T,A>& l)
{
    int n;
    doParsimUnpacking(buffer, n);
    for (int i = 0; i < n; i++) {
        l.push_back(T());
        doParsimUnpacking(buffer, l.back());
    }
}

// Packing/unpacking an std::set
template<typename T, typename Tr, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::set<T,Tr,A>& s)
{
    doParsimPacking(buffer, (int)s.size());
    for (typename std::set<T,Tr,A>::const_iterator it = s.begin(); it != s.end(); ++it)
        doParsimPacking(buffer, *it);
}

template<typename T, typename Tr, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::set<T,Tr,A>& s)
{
    int n;
    doParsimUnpacking(buffer, n);
    for (int i = 0; i < n; i++) {
        T x;
        doParsimUnpacking(buffer, x);
        s.insert(x);
    }
}

// Packing/unpacking an std::map
template<typename K, typename V, typename Tr, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::map<K,V,Tr,A>& m)
{
    doParsimPacking(buffer, (int)m.size());
    for (typename std::map<K,V,Tr,A>::const_iterator it = m.begin(); it != m.end(); ++it) {
        doParsimPacking(buffer, it->first);
        doParsimPacking(buffer, it->second);
    }
}

template<typename K, typename V, typename Tr, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::map<K,V,Tr,A>& m)
{
    int n;
    doParsimUnpacking(buffer, n);
    for (int i = 0; i < n; i++) {
        K k; V v;
        doParsimUnpacking(buffer, k);
        doParsimUnpacking(buffer, v);
        m[k] = v;
    }
}

// Default pack/unpack function for arrays
template<typename T>
void doParsimArrayPacking(omnetpp::cCommBuffer *b, const T *t, int n)
{
    for (int i = 0; i < n; i++)
        doParsimPacking(b, t[i]);
}

template<typename T>
void doParsimArrayUnpacking(omnetpp::cCommBuffer *b, T *t, int n)
{
    for (int i = 0; i < n; i++)
        doParsimUnpacking(b, t[i]);
}

// Default rule to prevent compiler from choosing base class' doParsimPacking() function
template<typename T>
void doParsimPacking(omnetpp::cCommBuffer *, const T& t)
{
    throw omnetpp::cRuntimeError("Parsim error: No doParsimPacking() function for type %s", omnetpp::opp_typename(typeid(t)));
}

template<typename T>
void doParsimUnpacking(omnetpp::cCommBuffer *, T& t)
{
    throw omnetpp::cRuntimeError("Parsim error: No doParsimUnpacking() function for type %s", omnetpp::opp_typename(typeid(t)));
}

}  // namespace omnetpp


// Returns the string form of t produced by operator<<, or the given fallback string if there is no operator<<.
// (The fallback should be "" for compound types, whose fields can be displayed, and "(unprintable)" otherwise.)
template<typename T>
std::string toStringIfPrintable(const T& t, const char *fallback) {
    if constexpr (omnetpp::internal::is_printable<T>::value) {
        std::ostringstream os;
        os << t;
        return os.str();
    }
    return fallback;
}

template<typename T>
bool fromStringIfExtractable(T& t, const char *s) {
    if constexpr (omnetpp::internal::is_extractable<T>::value) {
        std::istringstream is(s);
        is >> t;
        return true;
    }
    return false;
}

namespace rpm_lora_research {

Register_Class(RPMMeasurement)

RPMMeasurement::RPMMeasurement() : ::inet::FieldsChunk()
{
}

RPMMeasurement::RPMMeasurement(const RPMMeasurement& other) : ::inet::FieldsChunk(other)
{
    copy(other);
}

RPMMeasurement::~RPMMeasurement()
{
}

RPMMeasurement& RPMMeasurement::operator=(const RPMMeasurement& other)
{
    if (this == &other) return *this;
    ::inet::FieldsChunk::operator=(other);
    copy(other);
    return *this;
}

void RPMMeasurement::copy(const RPMMeasurement& other)
{
    this->patientId = other.patientId;
    this->seqNo = other.seqNo;
    this->timestamp = other.timestamp;
    this->heartRate = other.heartRate;
    this->spO2 = other.spO2;
    this->temperature = other.temperature;
    this->fallDetected = other.fallDetected;
    this->alertLevel = other.alertLevel;
    this->routingMode = other.routingMode;
    this->sourceId = other.sourceId;
    this->destinationId = other.destinationId;
    this->hopCount = other.hopCount;
    this->maxHopCount = other.maxHopCount;
    this->critical = other.critical;
}

void RPMMeasurement::parsimPack(omnetpp::cCommBuffer *b) const
{
    ::inet::FieldsChunk::parsimPack(b);
    doParsimPacking(b,this->patientId);
    doParsimPacking(b,this->seqNo);
    doParsimPacking(b,this->timestamp);
    doParsimPacking(b,this->heartRate);
    doParsimPacking(b,this->spO2);
    doParsimPacking(b,this->temperature);
    doParsimPacking(b,this->fallDetected);
    doParsimPacking(b,this->alertLevel);
    doParsimPacking(b,this->routingMode);
    doParsimPacking(b,this->sourceId);
    doParsimPacking(b,this->destinationId);
    doParsimPacking(b,this->hopCount);
    doParsimPacking(b,this->maxHopCount);
    doParsimPacking(b,this->critical);
}

void RPMMeasurement::parsimUnpack(omnetpp::cCommBuffer *b)
{
    ::inet::FieldsChunk::parsimUnpack(b);
    doParsimUnpacking(b,this->patientId);
    doParsimUnpacking(b,this->seqNo);
    doParsimUnpacking(b,this->timestamp);
    doParsimUnpacking(b,this->heartRate);
    doParsimUnpacking(b,this->spO2);
    doParsimUnpacking(b,this->temperature);
    doParsimUnpacking(b,this->fallDetected);
    doParsimUnpacking(b,this->alertLevel);
    doParsimUnpacking(b,this->routingMode);
    doParsimUnpacking(b,this->sourceId);
    doParsimUnpacking(b,this->destinationId);
    doParsimUnpacking(b,this->hopCount);
    doParsimUnpacking(b,this->maxHopCount);
    doParsimUnpacking(b,this->critical);
}

int RPMMeasurement::getPatientId() const
{
    return this->patientId;
}

void RPMMeasurement::setPatientId(int patientId)
{
    handleChange();
    this->patientId = patientId;
}

long RPMMeasurement::getSeqNo() const
{
    return this->seqNo;
}

void RPMMeasurement::setSeqNo(long seqNo)
{
    handleChange();
    this->seqNo = seqNo;
}

::omnetpp::simtime_t RPMMeasurement::getTimestamp() const
{
    return this->timestamp;
}

void RPMMeasurement::setTimestamp(::omnetpp::simtime_t timestamp)
{
    handleChange();
    this->timestamp = timestamp;
}

double RPMMeasurement::getHeartRate() const
{
    return this->heartRate;
}

void RPMMeasurement::setHeartRate(double heartRate)
{
    handleChange();
    this->heartRate = heartRate;
}

double RPMMeasurement::getSpO2() const
{
    return this->spO2;
}

void RPMMeasurement::setSpO2(double spO2)
{
    handleChange();
    this->spO2 = spO2;
}

double RPMMeasurement::getTemperature() const
{
    return this->temperature;
}

void RPMMeasurement::setTemperature(double temperature)
{
    handleChange();
    this->temperature = temperature;
}

bool RPMMeasurement::getFallDetected() const
{
    return this->fallDetected;
}

void RPMMeasurement::setFallDetected(bool fallDetected)
{
    handleChange();
    this->fallDetected = fallDetected;
}

int RPMMeasurement::getAlertLevel() const
{
    return this->alertLevel;
}

void RPMMeasurement::setAlertLevel(int alertLevel)
{
    handleChange();
    this->alertLevel = alertLevel;
}

int RPMMeasurement::getRoutingMode() const
{
    return this->routingMode;
}

void RPMMeasurement::setRoutingMode(int routingMode)
{
    handleChange();
    this->routingMode = routingMode;
}

int RPMMeasurement::getSourceId() const
{
    return this->sourceId;
}

void RPMMeasurement::setSourceId(int sourceId)
{
    handleChange();
    this->sourceId = sourceId;
}

int RPMMeasurement::getDestinationId() const
{
    return this->destinationId;
}

void RPMMeasurement::setDestinationId(int destinationId)
{
    handleChange();
    this->destinationId = destinationId;
}

int RPMMeasurement::getHopCount() const
{
    return this->hopCount;
}

void RPMMeasurement::setHopCount(int hopCount)
{
    handleChange();
    this->hopCount = hopCount;
}

int RPMMeasurement::getMaxHopCount() const
{
    return this->maxHopCount;
}

void RPMMeasurement::setMaxHopCount(int maxHopCount)
{
    handleChange();
    this->maxHopCount = maxHopCount;
}

bool RPMMeasurement::getCritical() const
{
    return this->critical;
}

void RPMMeasurement::setCritical(bool critical)
{
    handleChange();
    this->critical = critical;
}

class RPMMeasurementDescriptor : public omnetpp::cClassDescriptor
{
  private:
    mutable const char **propertyNames;
    enum FieldConstants {
        FIELD_patientId,
        FIELD_seqNo,
        FIELD_timestamp,
        FIELD_heartRate,
        FIELD_spO2,
        FIELD_temperature,
        FIELD_fallDetected,
        FIELD_alertLevel,
        FIELD_routingMode,
        FIELD_sourceId,
        FIELD_destinationId,
        FIELD_hopCount,
        FIELD_maxHopCount,
        FIELD_critical,
    };
  public:
    RPMMeasurementDescriptor();
    virtual ~RPMMeasurementDescriptor();

    virtual bool doesSupport(omnetpp::cObject *obj) const override;
    virtual const char **getPropertyNames() const override;
    virtual const char *getProperty(const char *propertyName) const override;
    virtual std::string getValueAsString(omnetpp::any_ptr object) const override;
    virtual void setValueAsString(omnetpp::any_ptr object, const char *value) const override;
    virtual int getFieldCount() const override;
    virtual const char *getFieldName(int field) const override;
    virtual int findField(const char *fieldName) const override;
    virtual unsigned int getFieldTypeFlags(int field) const override;
    virtual const char *getFieldTypeString(int field) const override;
    virtual const char **getFieldPropertyNames(int field) const override;
    virtual const char *getFieldProperty(int field, const char *propertyName) const override;
    virtual int getFieldArraySize(omnetpp::any_ptr object, int field) const override;
    virtual void setFieldArraySize(omnetpp::any_ptr object, int field, int size) const override;

    virtual const char *getFieldDynamicTypeString(omnetpp::any_ptr object, int field, int i) const override;
    virtual std::string getFieldValueAsString(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldValueAsString(omnetpp::any_ptr object, int field, int i, const char *value) const override;
    virtual omnetpp::cValue getFieldValue(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldValue(omnetpp::any_ptr object, int field, int i, const omnetpp::cValue& value) const override;

    virtual const char *getFieldStructName(int field) const override;
    virtual omnetpp::any_ptr getFieldStructValuePointer(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldStructValuePointer(omnetpp::any_ptr object, int field, int i, omnetpp::any_ptr ptr) const override;
};

Register_ClassDescriptor(RPMMeasurementDescriptor)

RPMMeasurementDescriptor::RPMMeasurementDescriptor() : omnetpp::cClassDescriptor(omnetpp::opp_typename(typeid(rpm_lora_research::RPMMeasurement)), "inet::FieldsChunk")
{
    propertyNames = nullptr;
}

RPMMeasurementDescriptor::~RPMMeasurementDescriptor()
{
    delete[] propertyNames;
}

bool RPMMeasurementDescriptor::doesSupport(omnetpp::cObject *obj) const
{
    return dynamic_cast<RPMMeasurement *>(obj)!=nullptr;
}

const char **RPMMeasurementDescriptor::getPropertyNames() const
{
    if (!propertyNames) {
        static const char *names[] = {  nullptr };
        omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
        const char **baseNames = base ? base->getPropertyNames() : nullptr;
        propertyNames = mergeLists(baseNames, names);
    }
    return propertyNames;
}

const char *RPMMeasurementDescriptor::getProperty(const char *propertyName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    return base ? base->getProperty(propertyName) : nullptr;
}

std::string RPMMeasurementDescriptor::getValueAsString(omnetpp::any_ptr object) const
{
    RPMMeasurement *pp = omnetpp::fromAnyPtr<RPMMeasurement>(object); (void)pp;
    return ((cObject*)pp)->str();
}

void RPMMeasurementDescriptor::setValueAsString(omnetpp::any_ptr object, const char *value) const
{
    RPMMeasurement *pp = omnetpp::fromAnyPtr<RPMMeasurement>(object); (void)pp;
    if (!fromStringIfExtractable(*pp, value))
        cClassDescriptor::setValueAsString(object, value);
}

int RPMMeasurementDescriptor::getFieldCount() const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    return base ? 14+base->getFieldCount() : 14;
}

unsigned int RPMMeasurementDescriptor::getFieldTypeFlags(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldTypeFlags(field);
        field -= base->getFieldCount();
    }
    static unsigned int fieldTypeFlags[] = {
        FD_ISEDITABLE,    // FIELD_patientId
        FD_ISEDITABLE,    // FIELD_seqNo
        FD_ISEDITABLE,    // FIELD_timestamp
        FD_ISEDITABLE,    // FIELD_heartRate
        FD_ISEDITABLE,    // FIELD_spO2
        FD_ISEDITABLE,    // FIELD_temperature
        FD_ISEDITABLE,    // FIELD_fallDetected
        FD_ISEDITABLE,    // FIELD_alertLevel
        FD_ISEDITABLE,    // FIELD_routingMode
        FD_ISEDITABLE,    // FIELD_sourceId
        FD_ISEDITABLE,    // FIELD_destinationId
        FD_ISEDITABLE,    // FIELD_hopCount
        FD_ISEDITABLE,    // FIELD_maxHopCount
        FD_ISEDITABLE,    // FIELD_critical
    };
    return (field >= 0 && field < 14) ? fieldTypeFlags[field] : 0;
}

const char *RPMMeasurementDescriptor::getFieldName(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldName(field);
        field -= base->getFieldCount();
    }
    static const char *fieldNames[] = {
        "patientId",
        "seqNo",
        "timestamp",
        "heartRate",
        "spO2",
        "temperature",
        "fallDetected",
        "alertLevel",
        "routingMode",
        "sourceId",
        "destinationId",
        "hopCount",
        "maxHopCount",
        "critical",
    };
    return (field >= 0 && field < 14) ? fieldNames[field] : nullptr;
}

int RPMMeasurementDescriptor::findField(const char *fieldName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    int baseIndex = base ? base->getFieldCount() : 0;
    if (strcmp(fieldName, "patientId") == 0) return baseIndex + 0;
    if (strcmp(fieldName, "seqNo") == 0) return baseIndex + 1;
    if (strcmp(fieldName, "timestamp") == 0) return baseIndex + 2;
    if (strcmp(fieldName, "heartRate") == 0) return baseIndex + 3;
    if (strcmp(fieldName, "spO2") == 0) return baseIndex + 4;
    if (strcmp(fieldName, "temperature") == 0) return baseIndex + 5;
    if (strcmp(fieldName, "fallDetected") == 0) return baseIndex + 6;
    if (strcmp(fieldName, "alertLevel") == 0) return baseIndex + 7;
    if (strcmp(fieldName, "routingMode") == 0) return baseIndex + 8;
    if (strcmp(fieldName, "sourceId") == 0) return baseIndex + 9;
    if (strcmp(fieldName, "destinationId") == 0) return baseIndex + 10;
    if (strcmp(fieldName, "hopCount") == 0) return baseIndex + 11;
    if (strcmp(fieldName, "maxHopCount") == 0) return baseIndex + 12;
    if (strcmp(fieldName, "critical") == 0) return baseIndex + 13;
    return base ? base->findField(fieldName) : -1;
}

const char *RPMMeasurementDescriptor::getFieldTypeString(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldTypeString(field);
        field -= base->getFieldCount();
    }
    static const char *fieldTypeStrings[] = {
        "int",    // FIELD_patientId
        "long",    // FIELD_seqNo
        "omnetpp::simtime_t",    // FIELD_timestamp
        "double",    // FIELD_heartRate
        "double",    // FIELD_spO2
        "double",    // FIELD_temperature
        "bool",    // FIELD_fallDetected
        "int",    // FIELD_alertLevel
        "int",    // FIELD_routingMode
        "int",    // FIELD_sourceId
        "int",    // FIELD_destinationId
        "int",    // FIELD_hopCount
        "int",    // FIELD_maxHopCount
        "bool",    // FIELD_critical
    };
    return (field >= 0 && field < 14) ? fieldTypeStrings[field] : nullptr;
}

const char **RPMMeasurementDescriptor::getFieldPropertyNames(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldPropertyNames(field);
        field -= base->getFieldCount();
    }
    switch (field) {
        default: return nullptr;
    }
}

const char *RPMMeasurementDescriptor::getFieldProperty(int field, const char *propertyName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldProperty(field, propertyName);
        field -= base->getFieldCount();
    }
    switch (field) {
        default: return nullptr;
    }
}

int RPMMeasurementDescriptor::getFieldArraySize(omnetpp::any_ptr object, int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldArraySize(object, field);
        field -= base->getFieldCount();
    }
    RPMMeasurement *pp = omnetpp::fromAnyPtr<RPMMeasurement>(object); (void)pp;
    switch (field) {
        default: return 0;
    }
}

void RPMMeasurementDescriptor::setFieldArraySize(omnetpp::any_ptr object, int field, int size) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldArraySize(object, field, size);
            return;
        }
        field -= base->getFieldCount();
    }
    RPMMeasurement *pp = omnetpp::fromAnyPtr<RPMMeasurement>(object); (void)pp;
    switch (field) {
        default: throw omnetpp::cRuntimeError("Cannot set array size of field %d of class 'RPMMeasurement'", field);
    }
}

const char *RPMMeasurementDescriptor::getFieldDynamicTypeString(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldDynamicTypeString(object,field,i);
        field -= base->getFieldCount();
    }
    RPMMeasurement *pp = omnetpp::fromAnyPtr<RPMMeasurement>(object); (void)pp;
    switch (field) {
        default: return nullptr;
    }
}

std::string RPMMeasurementDescriptor::getFieldValueAsString(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldValueAsString(object,field,i);
        field -= base->getFieldCount();
    }
    RPMMeasurement *pp = omnetpp::fromAnyPtr<RPMMeasurement>(object); (void)pp;
    switch (field) {
        case FIELD_patientId: return long2string(pp->getPatientId());
        case FIELD_seqNo: return long2string(pp->getSeqNo());
        case FIELD_timestamp: return simtime2string(pp->getTimestamp());
        case FIELD_heartRate: return double2string(pp->getHeartRate());
        case FIELD_spO2: return double2string(pp->getSpO2());
        case FIELD_temperature: return double2string(pp->getTemperature());
        case FIELD_fallDetected: return bool2string(pp->getFallDetected());
        case FIELD_alertLevel: return long2string(pp->getAlertLevel());
        case FIELD_routingMode: return long2string(pp->getRoutingMode());
        case FIELD_sourceId: return long2string(pp->getSourceId());
        case FIELD_destinationId: return long2string(pp->getDestinationId());
        case FIELD_hopCount: return long2string(pp->getHopCount());
        case FIELD_maxHopCount: return long2string(pp->getMaxHopCount());
        case FIELD_critical: return bool2string(pp->getCritical());
        default: return "";
    }
}

void RPMMeasurementDescriptor::setFieldValueAsString(omnetpp::any_ptr object, int field, int i, const char *value) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldValueAsString(object, field, i, value);
            return;
        }
        field -= base->getFieldCount();
    }
    RPMMeasurement *pp = omnetpp::fromAnyPtr<RPMMeasurement>(object); (void)pp;
    switch (field) {
        case FIELD_patientId: pp->setPatientId(string2long(value)); break;
        case FIELD_seqNo: pp->setSeqNo(string2long(value)); break;
        case FIELD_timestamp: pp->setTimestamp(string2simtime(value)); break;
        case FIELD_heartRate: pp->setHeartRate(string2double(value)); break;
        case FIELD_spO2: pp->setSpO2(string2double(value)); break;
        case FIELD_temperature: pp->setTemperature(string2double(value)); break;
        case FIELD_fallDetected: pp->setFallDetected(string2bool(value)); break;
        case FIELD_alertLevel: pp->setAlertLevel(string2long(value)); break;
        case FIELD_routingMode: pp->setRoutingMode(string2long(value)); break;
        case FIELD_sourceId: pp->setSourceId(string2long(value)); break;
        case FIELD_destinationId: pp->setDestinationId(string2long(value)); break;
        case FIELD_hopCount: pp->setHopCount(string2long(value)); break;
        case FIELD_maxHopCount: pp->setMaxHopCount(string2long(value)); break;
        case FIELD_critical: pp->setCritical(string2bool(value)); break;
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'RPMMeasurement'", field);
    }
}

omnetpp::cValue RPMMeasurementDescriptor::getFieldValue(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldValue(object,field,i);
        field -= base->getFieldCount();
    }
    RPMMeasurement *pp = omnetpp::fromAnyPtr<RPMMeasurement>(object); (void)pp;
    switch (field) {
        case FIELD_patientId: return pp->getPatientId();
        case FIELD_seqNo: return (omnetpp::intval_t)(pp->getSeqNo());
        case FIELD_timestamp: return pp->getTimestamp().dbl();
        case FIELD_heartRate: return pp->getHeartRate();
        case FIELD_spO2: return pp->getSpO2();
        case FIELD_temperature: return pp->getTemperature();
        case FIELD_fallDetected: return pp->getFallDetected();
        case FIELD_alertLevel: return pp->getAlertLevel();
        case FIELD_routingMode: return pp->getRoutingMode();
        case FIELD_sourceId: return pp->getSourceId();
        case FIELD_destinationId: return pp->getDestinationId();
        case FIELD_hopCount: return pp->getHopCount();
        case FIELD_maxHopCount: return pp->getMaxHopCount();
        case FIELD_critical: return pp->getCritical();
        default: throw omnetpp::cRuntimeError("Cannot return field %d of class 'RPMMeasurement' as cValue -- field index out of range?", field);
    }
}

void RPMMeasurementDescriptor::setFieldValue(omnetpp::any_ptr object, int field, int i, const omnetpp::cValue& value) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldValue(object, field, i, value);
            return;
        }
        field -= base->getFieldCount();
    }
    RPMMeasurement *pp = omnetpp::fromAnyPtr<RPMMeasurement>(object); (void)pp;
    switch (field) {
        case FIELD_patientId: pp->setPatientId(omnetpp::checked_int_cast<int>(value.intValue())); break;
        case FIELD_seqNo: pp->setSeqNo(omnetpp::checked_int_cast<long>(value.intValue())); break;
        case FIELD_timestamp: pp->setTimestamp(value.doubleValue()); break;
        case FIELD_heartRate: pp->setHeartRate(value.doubleValue()); break;
        case FIELD_spO2: pp->setSpO2(value.doubleValue()); break;
        case FIELD_temperature: pp->setTemperature(value.doubleValue()); break;
        case FIELD_fallDetected: pp->setFallDetected(value.boolValue()); break;
        case FIELD_alertLevel: pp->setAlertLevel(omnetpp::checked_int_cast<int>(value.intValue())); break;
        case FIELD_routingMode: pp->setRoutingMode(omnetpp::checked_int_cast<int>(value.intValue())); break;
        case FIELD_sourceId: pp->setSourceId(omnetpp::checked_int_cast<int>(value.intValue())); break;
        case FIELD_destinationId: pp->setDestinationId(omnetpp::checked_int_cast<int>(value.intValue())); break;
        case FIELD_hopCount: pp->setHopCount(omnetpp::checked_int_cast<int>(value.intValue())); break;
        case FIELD_maxHopCount: pp->setMaxHopCount(omnetpp::checked_int_cast<int>(value.intValue())); break;
        case FIELD_critical: pp->setCritical(value.boolValue()); break;
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'RPMMeasurement'", field);
    }
}

const char *RPMMeasurementDescriptor::getFieldStructName(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldStructName(field);
        field -= base->getFieldCount();
    }
    switch (field) {
        default: return nullptr;
    };
}

omnetpp::any_ptr RPMMeasurementDescriptor::getFieldStructValuePointer(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldStructValuePointer(object, field, i);
        field -= base->getFieldCount();
    }
    RPMMeasurement *pp = omnetpp::fromAnyPtr<RPMMeasurement>(object); (void)pp;
    switch (field) {
        default: return omnetpp::any_ptr(nullptr);
    }
}

void RPMMeasurementDescriptor::setFieldStructValuePointer(omnetpp::any_ptr object, int field, int i, omnetpp::any_ptr ptr) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldStructValuePointer(object, field, i, ptr);
            return;
        }
        field -= base->getFieldCount();
    }
    RPMMeasurement *pp = omnetpp::fromAnyPtr<RPMMeasurement>(object); (void)pp;
    switch (field) {
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'RPMMeasurement'", field);
    }
}

}  // namespace rpm_lora_research

namespace omnetpp {

}  // namespace omnetpp

