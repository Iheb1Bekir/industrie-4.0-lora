#!/usr/bin/env bash
# Export the doctor.app vectors of the OMNeT++ validation run used in the report (read-only). Run inside WSL (opp_env).
set -euo pipefail
cd /home/opp_env/default_workspace/RPM_LoRa_Research/simulations/results/circular-deployment-validation-20261108-r6-default-coverage-aware
f=$(ls *.vec | head -1)
for n in endToEndDelay hopCount patientId heartRate spO2 temperature alertLevel; do
  id=$(grep "^vector" $f | grep "doctor.app $n" | awk '{print $2}')
  echo "#$n"
  awk -v id=$id '$1==id {print $3, $4}' $f
done
