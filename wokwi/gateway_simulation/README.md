# Gateway simulation (SIMULATION MODE — not LoRa)
`gateway_simulator.py` reads packet lines (`... hex=<32 hex>`) from `--stdin`, `--file`, or `--generate SCENARIO`, then runs the real gateway code (decode → CRC → duplicate/loss tracking → `POST /api/vitals`) and prints reception statistics as JSON.
`simulated_patients.py` generates the same scenario values as the firmware using the same encoder.
Automatic: everything after the lines are fed in. Manual: copying lines out of the Wokwi Serial Monitor. Env: `API_URL`, `DOCTOR_TOKEN`.
