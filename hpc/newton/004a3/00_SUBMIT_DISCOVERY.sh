#!/usr/bin/env bash
set -Eeuo pipefail
: "${RBP_004A3_INSTALL_LOCATION:?set login_node or cpu_job after site-policy confirmation}"
: "${RBP_004A3_QUOTA_AVAILABLE_BYTES:?numeric quota availability required}"
: "${RBP_SLURM_MAIL_USER:?email address required for BEGIN/END/FAIL notices}"
ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
[[ ! -e "$ROOT/discovery" ]] || { printf 'Refusing existing discovery evidence.\n' >&2; exit 1; }
export RBP_004A3_ROOT="$ROOT"
sbatch --mail-user="$RBP_SLURM_MAIL_USER" --mail-type=BEGIN,END,FAIL \
  --export=ALL "$ROOT/hpc/newton/004a3/01_DISCOVERY.sbatch"
