# Remote Patient Monitoring over LoRa

This project simulates the collection and delivery of remote patient monitoring
(RPM) measurements over LoRa radios using OMNeT++ 6.5.0, INET 4.6.0, and
FLoRa 1.3.2. It retains the original direct patient-to-doctor network and adds
a separate multi-patient, multi-hop scenario.

The relay path is a project-specific forwarding protocol over FLoRa radio
modules. It is **not standard LoRaWAN mesh**; standard LoRaWAN does not define
this type of multi-hop relay behavior.

## Simulation scenarios

### DirectRPMNetwork

`DirectRPMNetwork` contains one `PatientNode` and one `DoctorNode`. The
patient's `PatientApp` periodically creates an `RPMMeasurement`, sends it via
the LoRa NIC, and the doctor's `DoctorApp` validates it and records valid
measurement vectors.

### DistributedRPMNetwork

`DistributedRPMNetwork` defaults to 20 patient nodes, 3 relay nodes, and one
doctor gateway. Patients occupy concentric rings of 8, 8, and 4 nodes. Patients
1–16 send directly to the doctor; patients 17–20 select relays 1, 1, 2, and 3.
Relays forward along the ordered relay chain using actual radio transmissions
and unicast LoRa MAC addresses. Each relay checks payload identity,
destination, duplicate key, previous hop, and hop limit, then increments
`hopCount`. The doctor validates measurements, suppresses duplicates, records
direct and relay-assisted packet totals, per-patient counts, alert totals, the
nine measurement vectors, and end-to-end delay.

Patient profiles have different baseline values. The configured scenario
includes a warning, a critical measurement, and a fall alert. Packet labels
include patient ID, sequence, physiological values, hop count, and alert type.
Patient and relay icons also change tint for activity and alerts.

The physical geometry is circular and distinct from Qtenv display geometry.
The doctor is at `(300 m, 300 m)`; the patient-ring radii are 25 m, 45 m, and
80 m; relays are positioned on a 30 m ring. Qtenv shows corresponding
concentric deployment guides and node rings around the doctor. Ring counts,
radii, and display radii are parameters in `DistributedRPMNetwork.ned`. These
are simulated deployment distances, not real regional distances.

The installed FLoRa `LoRaLogNormalShadowing` model uses `d0=40 m`,
`gamma=2.08`, and `sigma=3.57`. Its approximate median range at 14 dBm for the
SF7/125 kHz receiver sensitivity (-124 dBm) is about 129 m, not a guaranteed
coverage boundary. Shadowing can cause losses near that range; the validation
below reports observed delivery rather than assuming coverage.

## Radio profile and implementation notes

The distributed scenario uses:

- Center frequency: 868 MHz
- Bandwidth: 125 kHz
- Spreading factor: SF7
- Coding rate: 4/5
- Transmit power: 14 dBm (25.12 mW)

FLoRa's patient `LoRaTransmitter` reads the `LoRaRadio::loRaTP` member as dBm
when creating a transmission; its source does not initialize that member from
the NED transmitter power. The project-local `RPMPatientRadio` initializes
FLoRa's PHY metadata from the configured radio parameters without modifying
FLoRa. FLoRa's `LoRaReceiver` computes sensitivity from spreading factor and
bandwidth rather than the NED `receiver.sensitivity` parameter; for SF7 /
125 kHz its table gives -124 dBm.

The relay MAC implements INET's active queue-pull callbacks and resumes pulling
after FLoRa's duty-cycle timer, because the installed FLoRa gateway MAC does not
drain the NIC's passive transmit queue for this custom application-forwarding
use case.

## RPM measurement format

`RPMMeasurement.msg` preserves these payload fields:

- `patientId`, `seqNo`, `timestamp`
- `heartRate`, `spO2`, `temperature`
- `fallDetected`, `alertLevel`, `critical`
- `routingMode`, `sourceId`, `destinationId`
- `hopCount`, `maxHopCount`

The doctor records valid samples only, using vectors named `patientId`,
`sequenceNumber`, `measurementTimestamp`, `heartRate`, `spO2`, `temperature`,
`fallDetected`, `alertLevel`, and `hopCount`. The distributed doctor also
records an `endToEndDelay` vector. Vector samples use the current simulation
reception time; `measurementTimestamp` stores the payload timestamp in seconds.
Scalar packet counters, including direct and relay-assisted valid packets,
remain available in the `.sca` result.

## Requirements and installation paths

The existing environment used for validation is:

- OMNeT++: `/home/opp_env/default_workspace/omnetpp-6.5.0`
- INET: `/home/opp_env/default_workspace/inet-4.6.0`
- FLoRa: `/home/opp_env/default_workspace/flora-1.3.2`
- `opp_env` workspace: `/home/opp_env/default_workspace`

No INET or FLoRa source files are changed by this project. Build and run from
the project root with the installed `opp_env` environment:

```sh
opp_env run omnetpp-6.5.0 inet-4.6.0 --no-deps --no-isolated \
  -c 'make -j$(nproc)'
```

## Compile and launch

Run the distributed network in Cmdenv for its configured 120 seconds. Use a
new result directory for each run:

```sh
cd simulations
../RPM_LoRa_Research -u Cmdenv -c DistributedRPM \
  -n ..:../../flora-1.3.2/src:../../inet-4.6.0/src \
  --result-dir=results/circular-deployment-validation omnetpp.ini
```

Launch the same configuration in Qtenv (use a new result directory when
repeating a run):

```sh
cd simulations
../RPM_LoRa_Research -u Qtenv -c DistributedRPM \
  -n ..:../../flora-1.3.2/src:../../inet-4.6.0/src \
  --result-dir=results/qtenv-visual-check omnetpp.ini
```

Top-level patient and relay display positions are calculated from separate
display radii; radio mobility positions come from the deployment radii.
Top-level deployment-ring figures are decorative only, use the same display
coordinate system, and have a negative z-order behind the nodes. No permanent
wireless links are drawn. Packet animation reflects actual radio transmissions.
The interactive view has not been visually inspected in this environment.

Run the direct-network regression with a separate result directory:

```sh
cd simulations
../RPM_LoRa_Research -u Cmdenv -c General \
  -n ..:../../flora-1.3.2/src:../../inet-4.6.0/src \
  --sim-time-limit=54s --result-dir=results/direct-regression-54s omnetpp.ini
```

When using the `opp_env` wrapper, run each command from the project root, e.g.:

```sh
opp_env run omnetpp-6.5.0 inet-4.6.0 --no-deps --no-isolated \
  -c 'cd simulations && ../RPM_LoRa_Research -u Cmdenv -c DistributedRPM -n ..:../../flora-1.3.2/src:../../inet-4.6.0/src omnetpp.ini'
```

## Inspect results

OMNeT++ writes scalar, vector, and vector-index files (`.sca`, `.vec`, `.vci`)
under the configured result directory. Open them in the OMNeT++ IDE result
analysis tools, or inspect counters from the project root with:

```sh
grep '^scalar DistributedRPMNetwork.doctor.app ' \
  simulations/results/circular-deployment-validation-20261108-r6-default-coverage-aware/DistributedRPM-#0.sca
grep '^scalar DistributedRPMNetwork.relay' \
  simulations/results/circular-deployment-validation-20261108-r6-default-coverage-aware/DistributedRPM-#0.sca
```

The nine measurement vectors and the distributed delay vector are in the
matching `.vec` file. Do not reuse a result directory if its existing contents
need to be preserved.

## Validation results

The previous all-relayed regression used 20 patients, 3 relays, and a
120-second simulation in
`simulations/results/multi-patient-validation-20261108-0250-r13-queue-drain/`.
It delivered 80/80 valid measurements before the circular, mixed-route
deployment was introduced.

The current circular mixed-route run is in
`simulations/results/circular-deployment-validation-20261108-r6-default-coverage-aware/`
(120 s):

- Generated/transmitted: 80/80 (4 per patient)
- Doctor received/valid/invalid: 79/79/0; duplicates: 0
- Valid packets: 64 direct and 15 relay-assisted
- Valid samples per patient (1–20): 4 for every patient except patient 18,
  which contributed 3
- Each of the nine measurement vectors and the `endToEndDelay` vector contains
  79 samples
- Relay app receive progression: 7, 11, and 15 packets; no relay drops or
  duplicate drops
- Doctor alerts: 76 normal, 1 warning, 2 critical, including 1 fall
- Radio receivers reported zero collisions; below-sensitivity receptions were
  observed, consistent with the probabilistic shadowing model

The circular validation run therefore does **not** meet 80/80 delivery. A
focused Cmdenv trace identified the missing `P18#0001` packet: relay 1's
receiver recorded an unsuccessful reception at `0.000331413 pW` (about
`-124.8 dBm`), below the SF7/125 kHz sensitivity; the nearby relay heard the
transmission but was not its MAC destination. The other 79 packets were valid,
with no doctor invalid or duplicate drops. This is a measured, probabilistic
result, not a coverage guarantee.

The direct-network regression completed without runtime errors in
`simulations/results/direct-regression-circular-20261108-r1/`:

- Generated: 10; transmitted: 10
- Doctor received and validated: 10; invalid: 0
- Each of the nine doctor measurement vectors contained 10 samples
- Receiver counters showed 0 collisions and 0 below-sensitivity receptions

The default 50-second General run generated its tenth packet at the 50-second
simulation limit, leaving no simulation time for its radio delivery; it
therefore recorded 10 generated/transmitted and 9 received/valid. The 54-second
regression gives that final transmission time to complete.

## Scope and limitations

- Relaying is a custom application/MAC forwarding design, not LoRaWAN mesh.
- The current routing is a deterministic first-hop assignment followed by a
  relay chain; it does not calculate arbitrary routes from a changing topology.
- The circular geometry does not model terrain, buildings, patient mobility,
  or a calibrated regional radio link. LoRa shadowing makes delivery
  probabilistic, particularly at outer-ring distances.
- The simulation does not implement a dashboard, hardware interfaces, a
  production LoRaWAN network server, or dynamic alert-specific packet colors.
- Qtenv loaded the project's NED and image resources during validation, but the
  interactive network view was not visually inspected in this session.
- Cmdenv reports eight unused direct-network configuration entries when the
  distributed configuration is selected; they are inherited from `[General]`
  and do not prevent the distributed run from completing.
