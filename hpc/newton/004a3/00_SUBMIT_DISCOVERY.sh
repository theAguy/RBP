#!/usr/bin/env bash
set -Eeuo pipefail
: "${RBP_004A3_INSTALL_LOCATION:?set login_node or cpu_job after site-policy confirmation}"
: "${RBP_004A3_QUOTA_AVAILABLE_BYTES:?numeric quota availability required}"
: "${RBP_SLURM_PARTITION:?explicit reviewed Slurm partition required}"
: "${RBP_SLURM_MAIL_USER:?email address required for BEGIN/END/FAIL notices}"
: "${USER:?non-empty USER required before discovery submission}"
: "${HOME:?non-empty HOME required before discovery submission}"
[[ "$RBP_004A3_QUOTA_AVAILABLE_BYTES" =~ ^[1-9][0-9]*$ ]] || {
  printf 'RBP_004A3_QUOTA_AVAILABLE_BYTES must be a positive integer in bytes.\n' >&2
  exit 2
}
[[ "$RBP_SLURM_PARTITION" =~ ^[A-Za-z0-9._-]+$ ]] || {
  printf 'RBP_SLURM_PARTITION is malformed.\n' >&2
  exit 2
}
SBATCH_ROUTING=(--partition="$RBP_SLURM_PARTITION")
if [[ -n "${RBP_SLURM_ACCOUNT:-}" ]]; then
  [[ "$RBP_SLURM_ACCOUNT" =~ ^[A-Za-z0-9._-]+$ ]] || {
    printf 'RBP_SLURM_ACCOUNT is malformed.\n' >&2
    exit 2
  }
  SBATCH_ROUTING+=(--account="$RBP_SLURM_ACCOUNT")
fi
ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
[[ ! -e "$ROOT/discovery" ]] || { printf 'Refusing existing discovery evidence.\n' >&2; exit 1; }
export RBP_004A3_ROOT="$ROOT"
sbatch "${SBATCH_ROUTING[@]}" \
  --mail-user="$RBP_SLURM_MAIL_USER" --mail-type=BEGIN,END,FAIL \
  --export=ALL "$ROOT/hpc/newton/004a3/01_DISCOVERY.sbatch"
