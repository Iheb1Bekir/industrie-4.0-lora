#!/usr/bin/env python3
"""Gateway simulator CLI (SIMULATION MODE - not LoRa).

Sources (choose one):
  --stdin            paste lines copied from the Wokwi Serial Monitor (MANUAL step), Ctrl-D/Ctrl-Z to finish
  --file FILE        a text file containing those lines
  --generate SCEN    deterministic synthetic packets (NORMAL LOW_SPO2 HIGH_HR HIGH_TEMP FALL SENSOR_ERROR)
Only lines containing 'hex=<32 hex chars>' are used; everything else is ignored.
"""
import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from gateway.bridge import Gateway, HttpForwarder  # noqa: E402
from gateway.radio import SimulationTransport  # noqa: E402
from simulated_patients import SCENARIOS, lines  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--stdin", action="store_true")
    src.add_argument("--file")
    src.add_argument("--generate", choices=SCENARIOS)
    ap.add_argument("--pid", default="P001"); ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--api", default=os.environ.get("API_URL", "http://127.0.0.1:5000"))
    ap.add_argument("--token", default=os.environ.get("DOCTOR_TOKEN", ""))
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between generated packets (API throttle is 30 s/patient by default)")
    a = ap.parse_args(argv)
    if not a.token: ap.error("set DOCTOR_TOKEN or pass --token")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if a.generate:
        def gen():
            for l in lines(a.pid, a.generate, a.count):
                yield l
                if a.delay: time.sleep(a.delay)
        it = gen()
    elif a.file:
        it = open(a.file)
    else:
        it = sys.stdin
    clock = time.time
    if a.generate:   # virtual timestamps 60 s apart ending now, so history has a time axis (data stays flagged SYNTHETIC)
        base = int(time.time()) - 60 * (a.count - 1)
        counter = iter(range(a.count))
        clock = lambda: base + 60 * next(counter)  # noqa: E731
    gw = Gateway(SimulationTransport(it), HttpForwarder(a.api, a.token), source="sim-serial", clock=clock)
    print(json.dumps(gw.run(), indent=2))


if __name__ == "__main__":
    main()
