#!/usr/bin/env bash
# Linux / WSL / Raspberry Pi setup. Usage: scripts/setup.sh [--pi]   (--pi also installs the radio dependencies)
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
if [ "${1:-}" = "--pi" ]; then pip install spidev gpiozero lgpio; fi
[ -f ml/models/active.json ] || python ml/train.py
echo
echo "Development demo:  python -m gateway.manage seed-demo && python -m gateway.server"
echo "Production (Pi):   see docs/RASPBERRY_PI_SETUP.md"
