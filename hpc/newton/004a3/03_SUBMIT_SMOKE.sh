#!/usr/bin/env bash
set -Eeuo pipefail
: "${RBP_004A3_ENV_PREFIX:?verified environment prefix required}"
: "${RBP_SLURM_MAIL_USER:?email address required for BEGIN/END/FAIL notices}"
ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
cd "$ROOT"
[[ ! -e "$ROOT/run/accepted" && ! -e "$ROOT/run/STOPPED.json" ]] || {
  printf 'Refusing existing process evidence.\n' >&2; exit 1;
}
export RBP_004A3_ROOT="$ROOT"
GPU_REQUEST=$("$RBP_004A3_ENV_PREFIX/bin/python" -c \
  'import json; c=json.load(open("BUNDLE_CONFIG.json")); print(c["gpu_gres"]+"|"+c["gpu_constraint"]+"|"+c["gpu_nodelist"])')
IFS='|' read -r GPU_GRES GPU_CONSTRAINT GPU_NODELIST <<< "$GPU_REQUEST"
SBATCH_ARGS=(--gres="$GPU_GRES" --nodelist="$GPU_NODELIST")
if [[ -n "$GPU_CONSTRAINT" ]]; then SBATCH_ARGS+=(--constraint="$GPU_CONSTRAINT"); fi
sbatch "${SBATCH_ARGS[@]}" --mail-user="$RBP_SLURM_MAIL_USER" --mail-type=BEGIN,END,FAIL \
  --export=ALL "$ROOT/hpc/newton/004a3/RUN_004A3_SMOKE.sbatch"
