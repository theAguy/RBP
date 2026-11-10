#!/usr/bin/env bash
set -Eeuo pipefail

: "${RBP_004A3_CPU_PARTITION:?explicit CPU partition required}"
: "${RBP_SLURM_MAIL_USER:?email required for BEGIN/END/FAIL notices}"
[[ "$RBP_004A3_CPU_PARTITION" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "Malformed CPU partition" >&2; exit 1; }
if [[ -n "${RBP_004A3_CPU_ACCOUNT:-}" && ! "$RBP_004A3_CPU_ACCOUNT" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  echo "Malformed CPU account" >&2; exit 1
fi
ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
cd "$ROOT"
[[ ! -e environment_return && ! -e environment_work && ! -e environment_staging ]] || {
  echo "Refusing pre-existing environment evidence/work root" >&2; exit 1;
}
SBATCH_ARGS=(--partition="$RBP_004A3_CPU_PARTITION")
if [[ -n "${RBP_004A3_CPU_ACCOUNT:-}" ]]; then
  SBATCH_ARGS+=(--account="$RBP_004A3_CPU_ACCOUNT")
fi
sbatch "${SBATCH_ARGS[@]}" \
  --mail-user="$RBP_SLURM_MAIL_USER" --mail-type=BEGIN,END,FAIL \
  --export=ALL,RBP_004A3_ROOT="$ROOT" \
  "$ROOT/hpc/newton/004a3/02_PREPARE_ENVIRONMENT.sbatch"
