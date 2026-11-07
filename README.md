# RPM LoRa Research

This project implements a minimal direct-mode remote patient monitoring proof of concept using the installed OMNeT++ 6.5.0, INET 4.6.0, and FLoRa 1.3.2 environment.

It is intentionally limited to Phase 1 of the project plan:
- one patient device
- one doctor station
- direct patient-to-doctor LoRa communication
- no relay or hybrid routing yet

## Verified environment

- OMNeT++: /home/opp_env/default_workspace/omnetpp-6.5.0
- INET: /home/opp_env/default_workspace/inet-4.6.0
- FLoRa: /home/opp_env/default_workspace/flora-1.3.2

## Build

From the project root:

make

## Run simulation

./out/gcc-release//RPM_LoRa_Research -u Cmdenv -c General -n .:../flora-1.3.2/src:../inet-4.6.0/src -l ../flora-1.3.2/src/libflora.so -l ../inet-4.6.0/src/libINET.so

## Project structure

- package.ned
- src/messages/RPMMeasurement.msg
- src/patient/PatientNode.ned
- src/patient/PatientApp.h
- src/patient/PatientApp.cc
- src/doctor/DoctorNode.ned
- src/doctor/DoctorApp.h
- src/doctor/DoctorApp.cc
- simulations/omnetpp.ini

## Notes

This direct-mode prototype uses the actual FLoRa wireless stack (`LoRaNic` -> `LoRaMac` -> `LoRaRadio`) and validates packet generation and doctor-side reception with an application payload containing patient health data.
