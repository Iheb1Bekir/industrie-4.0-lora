# Simulation guide

Three different things are called "simulation" in this project. They are kept apart on purpose.

| | What it is | Where | Feeds the dashboard? |
|---|---|---|---|
| **A. Built-in simulation mode** | virtual patient devices generating signed protocol-v2 frames through a statistical LoRa network model, into the *real* ingestion → prediction → alert pipeline | `gateway/simulator.py`, Simulation page | Yes, live, in the separate simulation database |
| **B. OMNeT++ / FLoRa research model** | packet-level radio simulation of 20 patients / 3 relays / 1 gateway | WSL `opp_env`: `/home/opp_env/default_workspace/RPM_LoRa_Research` | Only as imported, read-only result summaries (LoRa network → Research scenario) |
| **C. Wokwi firmware simulation** | the ESP32 sketch running in the Wokwi simulator with simulated sensors | `wokwi/` | Only through the legacy serial bridge (`RPM_ALLOW_LEGACY_V1`), manual |

None of them drives or represents physical radios.

## A. Built-in simulation mode

### Start
1. `python -m gateway.server` and sign in as an administrator doctor (development: `python -m gateway.manage seed-demo`, credentials in `data/demo_credentials.txt`).
2. Open **Simulation**. The operating-mode selector must be on **Simulation** (yellow "SIMULATION MODE" bar on every page).
3. Choose scenario, number of patients (3 = your physical setup, 20 = research topology), speed, sampling interval, relays → **Start simulation**.

Controls: **Pause**, **Resume**, **Stop**, **Reset scenario data**, and per patient **Trigger** an event at any time. Start always wipes and re-seeds the *simulation* database only.

### Scenarios
| | Name | What happens (simulated time) | What to watch |
|---|---|---|---|
| A | Normal operation | stable vitals for everyone | Overview all green, delivery ratio, live charts |
| B | Gradual deterioration | patient 1: HR ↑, SpO2 ↓, temperature ↑ over 10 min from t = 60 s | predictive warning, then threshold alerts, escalation if not acknowledged |
| C | Sudden fall | patient 2 falls at t = 45 s | immediate critical alert (event frame), map marker pulses, caregiver view "urgent" |
| D | SpO2 decline | patient 1 desaturates over 8 min | LOW_SPO2 alert, SpO2 chart crossing the limit line |
| E | Network failure | patient 2: 50 % loss from t = 40 s, device off at t = 240 s | lost frames, "Network degraded", then "Device offline" |
| F | Multi-patient emergency | patient 1 deterioration, patient 2 fall, patient 3 SpO2 decline, patients 4–5 fever | several alert types at once, notification handling |
| G | Predictive warning | patient 1: slow HR rise starting at t = 240 s | **Predictive warning appears before the HIGH_HR threshold alert**; explanation on the alert and AI page |

Manual events: `deterioration, spo2_decline, hr_rise, fever, fall, sensor_fault, disconnect, reconnect, packet_loss, recover, predictive_trend`.

### What is simulated, precisely
* **Physiology**: per-patient baselines taken from the OMNeT++ model's formulas (`baseHeartRate = 68 + (i mod 7)·2`, …), AR(1) noise, slow drift, additive effects with smooth onset; values are quantised like the device would send them.
* **Devices**: each virtual device has its own id (60001…) and 256-bit key; frames are encoded with the production encoder, relayed with the production relay function, and verified by the production pipeline.
* **Network** (statistical twin of the FLoRa scenario): ring geometry 25 / 45 / 80 m, 14 dBm, log-normal shadowing (d₀ = 40 m, γ = 2.08, σ = 3.57), SF7/125 kHz sensitivity −124 dBm, the outer ~20 % of patients routed through the relay chain (as in `DistributedRPMNetwork.ned`), configurable random loss, duplicates and delays; relays apply duplicate and hop-limit rules and count received / forwarded / dropped.
* **Movement**: a small random walk around fictional coordinates in a Mahdia demonstration area; every location has `source = simulated`.
* **Device failure**: "disconnect" simply stops transmitting — the backend has to notice by timeout, exactly as with hardware.

### What the speed factor means
Speed ×N compresses both the sampling interval and the physiological tempo in wall-clock time. **Stored timestamps are always the real current UTC time** (no fake dates). At high speed, trends are steeper than those the model was trained on; ×1–×4 is representative, higher is for quick demonstrations. Offline timeout in simulation = max(8 s, 3.5 × real sampling interval).

### Guarantees (tested)
* every simulated record has `sim_session_id`, patients have `is_synthetic = 1`, the UI labels everything as simulation;
* nothing simulated can reach the hardware database; a simulated frame submitted to the hardware pipeline is rejected as an unknown device;
* after **Stop** no further synthetic record is created; pausing freezes the stream;
* switching to hardware mode stops the engine; real data is never deleted by simulation actions.

### Not simulated
Radio collisions and capture, duty-cycle enforcement, clock drift, battery discharge, real sensor behaviour. Use the OMNeT++ model for radio-level questions.

## B. OMNeT++ / FLoRa research model

Location and versions (unchanged by this work): OMNeT++ 6.5.0, INET 4.6.0, FLoRa 1.3.2 in the WSL distro `opp_env`. Build and run exactly as described in that project's README, e.g.

```sh
# inside WSL (opp_env), project root /home/opp_env/default_workspace/RPM_LoRa_Research
opp_env run omnetpp-6.5.0 inet-4.6.0 --no-deps --no-isolated \
  -c 'cd simulations && ../RPM_LoRa_Research -u Cmdenv -c DistributedRPM -n ..:../../flora-1.3.2/src:../../inet-4.6.0/src --result-dir=results/<new-dir> omnetpp.ini'
```
Note: the plain login shell of that distro prints `Multiple versions specified for project inet: [4.6.0, 4.7.0]`; this pre-existing condition was left as is — always name the versions explicitly as above.

Import a result into the dashboard (reads the `.sca` file only):

```powershell
# Windows PowerShell, from the repository root
wsl -d opp_env -u opp_env -e cat "/home/opp_env/default_workspace/RPM_LoRa_Research/simulations/results/<run>/DistributedRPM-#0.sca" > $env:TEMP\run.sca
.\.venv\Scripts\python.exe tools\import_omnet_results.py $env:TEMP\run.sca --label "<run>" --source "<run>/DistributedRPM-#0.sca"
```
One run is already imported: `circular-mixed-route-r6` (20 patients, 3 relays, 80 generated, 79 valid at the doctor: 64 direct + 15 relay-assisted — identical to the figures in the research README).

Relationship between the models:

| Concept | OMNeT++ module | Built-in simulation | Real hardware |
|---|---|---|---|
| Patient app | `DistributedPatientApp` | `_VPatient` + `protocol.encode` | `firmware/patient_node_lora` |
| Patient radio | `RPMLoRaNic` / `RPMPatientRadio` | shadowing model | RadioLib + SX127x/SX126x |
| Relay | `RPMRelayApp` + `RPMRelayMac` | `protocol.relay_forward` + dedup set | `firmware/relay_node` |
| Doctor gateway | `DistributedDoctorApp` + `RPMGatewayNic` | `Pipeline.handle_frame` | `hw_gateway` + `Pipeline.handle_frame` |
| Message | `RPMMeasurement.msg` | protocol v2 frame | protocol v2 frame |

## C. Wokwi firmware

Unchanged; see the root README section "Wokwi simulation firmware". It demonstrates sensors and local alerts; its serial output is protocol v1.
