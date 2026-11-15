#!/usr/bin/env python3
"""Import one OMNeT++ scalar result file (.sca) of the RPM_LoRa_Research project into the dashboard.

The OMNeT++/FLoRa project stays untouched: this tool only READS a .sca file and writes a small JSON summary to
simulation/omnetpp/imported_results/, which the "LoRa network" page shows under "Research scenario".

  python tools/import_omnet_results.py path/to/DistributedRPM-#0.sca --label "circular mixed-route r6"
  wsl -d opp_env -e cat /home/opp_env/default_workspace/RPM_LoRa_Research/simulations/results/<run>/DistributedRPM-#0.sca \
      | python tools/import_omnet_results.py - --label "<run>" --source "<run>/DistributedRPM-#0.sca"
"""
import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCALAR = re.compile(r'^scalar\s+(\S+)\s+("[^"]*"|\S+)\s+(\S+)')


def parse(text):
    scal, attrs = {}, {}
    for line in text.splitlines():
        m = SCALAR.match(line)
        if m:
            try:
                scal[(m.group(1), m.group(2).strip('"'))] = float(m.group(3))
            except ValueError:
                pass
        elif line.startswith(("config ", "itervar ", "attr ")):
            parts = line.split(None, 2)
            if len(parts) == 3:
                attrs[parts[1]] = parts[2].strip('"')
    return scal, attrs


def summarize(scal, attrs, label, source):
    def g(mod_suffix, name, default=0):
        for (mod, n), v in scal.items():
            if n == name and mod.endswith(mod_suffix):
                return v
        return default
    patients = sorted({m for (m, n) in scal if n == "generatedPackets" and ".patients[" in m})
    generated = int(sum(v for (m, n), v in scal.items() if n == "generatedPackets" and ".patients[" in m))
    relays = sorted({m.split(".app")[0] for (m, n) in scal if ".relay[" in m and m.endswith(".app") and n == "receivedPackets"})
    relay_stats = []
    for i, r in enumerate(relays):
        mac_fwd = next((v for (m, n), v in scal.items() if m.startswith(r + ".") and m.endswith(".mac") and n == "forwardedPackets"), None)
        relay_stats.append({"index": i, "received": int(g(r + ".app", "receivedPackets")), "forwarded": None if mac_fwd is None else int(mac_fwd),
                            "dropped": int(g(r + ".app", "droppedPackets")), "duplicates": int(g(r + ".app", "duplicatePackets"))})
    direct, relay = int(g(".doctor.app", "directPackets")), int(g(".doctor.app", "relayAssistedPackets"))
    valid = direct + relay
    if not patients or not generated:
        raise SystemExit("this file does not look like a DistributedRPM result (no patients[*].app generatedPackets scalars)")
    return {"label": label, "source": source, "imported_at": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()),
            "tool": "OMNeT++ 6.5.0 / INET 4.6.0 / FLoRa 1.3.2", "sim_time": attrs.get("sim-time-limit", "?"),
            "patients": len(patients), "relays": len(relays), "generated": generated, "doctor_valid": valid,
            "direct": direct, "relay_assisted": relay, "pdr": round(valid / generated, 4),
            "duplicates": int(g(".doctor.app", "duplicatePackets")),
            "alerts": {"normal": int(g(".doctor.app", "normalAlerts")), "warning": int(g(".doctor.app", "warningAlerts")),
                       "critical": int(g(".doctor.app", "criticalAlerts")), "fall": int(g(".doctor.app", "fallAlerts"))},
            "relay_stats": relay_stats}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sca", help=".sca file, or - for stdin"); ap.add_argument("--label", required=True)
    ap.add_argument("--source", default=None); ap.add_argument("--out", default=os.path.join(ROOT, "simulation", "omnetpp", "imported_results"))
    a = ap.parse_args(argv)
    text = sys.stdin.read() if a.sca == "-" else open(a.sca, encoding="utf-8", errors="replace").read()
    summary = summarize(*parse(text), a.label, a.source or a.sca)
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, re.sub(r"[^A-Za-z0-9._-]+", "_", a.label) + ".json")
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2)); print("written:", path)


if __name__ == "__main__":
    main()
