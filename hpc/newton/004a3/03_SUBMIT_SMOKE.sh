#!/usr/bin/env bash
set -Eeuo pipefail
: "${RBP_004A3_ENV_PREFIX:?verified environment prefix required}"
: "${RBP_SLURM_MAIL_USER:?email address required for BEGIN/END/FAIL notices}"
ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
[[ ! -e "$ROOT/run/primary.json" && ! -e "$ROOT/run/repeat.json" ]] || {
  printf 'Refusing existing process evidence.\n' >&2; exit 1;
}
export RBP_004A3_ROOT="$ROOT"
sbatch --mail-user="$RBP_SLURM_MAIL_USER" --mail-type=BEGIN,END,FAIL \
  --export=ALL "$ROOT/hpc/newton/004a3/RUN_004A3_SMOKE.sbatch"
