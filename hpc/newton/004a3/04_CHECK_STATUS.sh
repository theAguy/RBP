#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
if [[ -f "$ROOT/run/accepted/comparison.json" ]]; then
  printf '004A-3 smoke completed; verify the ZIP and checksum in return/.\n'
elif [[ -f "$ROOT/run/STOPPED.json" ]]; then
  printf '004A-3 smoke stopped. Do not retry; return STOPPED.json and the Slurm logs.\n'
else
  squeue --me --name=rbp-004a3-smoke || true
fi
