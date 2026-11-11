#!/usr/bin/env bash
set -Eeuo pipefail

: "${RBP_004A3_CPU_PARTITION:?explicit CPU partition required}"
: "${RBP_SLURM_MAIL_USER:?email required for BEGIN/END/FAIL notices}"
: "${RBP_004A3_CONDA_EXE:?validated Conda executable required}"
: "${RBP_004A3_STOPPED_ROOT:?stopped checkout root required}"
: "${RBP_004A3_STOPPED_JOB_ID:?stopped job ID required}"
: "${RBP_004A3_STOPPED_RETURN_SHA256:?stopped-return SHA-256 required}"
: "${RBP_004A3_LOCK_SHA256:?environment-lock SHA-256 required}"
: "${RBP_004A3_LOCK_ENTRY_COUNT:?environment-lock entry count required}"
[[ "$RBP_004A3_CPU_PARTITION" =~ ^[A-Za-z0-9_.-]+$ ]]
[[ -z "${RBP_004A3_CPU_ACCOUNT:-}" || "$RBP_004A3_CPU_ACCOUNT" =~ ^[A-Za-z0-9_.-]+$ ]]
[[ "$RBP_004A3_CONDA_EXE" = /* && -x "$RBP_004A3_CONDA_EXE" ]]
[[ "$RBP_004A3_STOPPED_ROOT" = /* && -d "$RBP_004A3_STOPPED_ROOT" && ! -L "$RBP_004A3_STOPPED_ROOT" ]]
[[ "$RBP_004A3_STOPPED_JOB_ID" =~ ^[1-9][0-9]*$ ]]
[[ "$RBP_004A3_STOPPED_RETURN_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$RBP_004A3_LOCK_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$RBP_004A3_LOCK_ENTRY_COUNT" =~ ^[1-9][0-9]*$ ]]

ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
cd "$ROOT"
[[ ! -e environment_recovery_return && ! -e environment_recovery_work ]] || {
  echo "Refusing pre-existing environment recovery evidence/work root" >&2; exit 1;
}
FINAL="$HOME/.conda/envs/rbpbench-004a3-${RBP_004A3_LOCK_SHA256:0:12}"
[[ ! -e "$FINAL" ]] || { echo "Refusing existing final prefix: $FINAL" >&2; exit 1; }

SBATCH_ARGS=(--partition="$RBP_004A3_CPU_PARTITION")
if [[ -n "${RBP_004A3_CPU_ACCOUNT:-}" ]]; then
  SBATCH_ARGS+=(--account="$RBP_004A3_CPU_ACCOUNT")
fi
sbatch "${SBATCH_ARGS[@]}" \
  --mail-user="$RBP_SLURM_MAIL_USER" --mail-type=BEGIN,END,FAIL \
  --export=ALL,RBP_004A3_ROOT="$ROOT" \
  "$ROOT/hpc/newton/004a3/02_RECOVER_ENVIRONMENT.sbatch"
