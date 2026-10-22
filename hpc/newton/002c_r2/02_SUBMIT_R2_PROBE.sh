#!/usr/bin/env bash
set -Eeuo pipefail

# Run on Newton's login node from the extracted bundle.  The actual probe is
# submitted to Slurm; nothing computationally heavy runs on the login node.

BUNDLE_ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
SUBMISSION_DIR="${BUNDLE_ROOT}.slurm_submission"
ENV_PREFIX=${RBP_NEWTON_ENV_PREFIX:-"$HOME/.conda/envs/rbpbench-r2-newton"}
ACCOUNT=${NEWTON_ACCOUNT:-}
PARTITION=${NEWTON_PARTITION:-}
MEMORY=${NEWTON_MEMORY:-96G}
TIME_LIMIT=${NEWTON_TIME_LIMIT:-08:00:00}

if ! command -v sbatch >/dev/null 2>&1; then
  printf 'sbatch is unavailable. Run this script on the Newton login node.\n' >&2
  exit 1
fi

for required in \
  "$BUNDLE_ROOT/R2_INPUT_MANIFEST.json" \
  "$BUNDLE_ROOT/R2_INPUT_MANIFEST.sha256" \
  "$BUNDLE_ROOT/R2_NEWTON_CONFIG.json" \
  "$ENV_PREFIX/newton_runtime_receipt.json" \
  "$ENV_PREFIX/newton_runtime_receipt.json.sha256"; do
  [[ -f "$required" ]] || { printf 'Missing required file: %s\n' "$required" >&2; exit 1; }
done

for forbidden in r2_output return execution_logs; do
  [[ ! -e "$BUNDLE_ROOT/$forbidden" ]] || {
    printf 'Refusing reused bundle: %s already exists. Extract a fresh copy.\n' "$forbidden" >&2
    exit 1
  }
done

mkdir -p "$SUBMISSION_DIR"
SBATCH_ARGS=(
  --job-name=rbp-r2-probe
  --cpus-per-task=4
  --mem="$MEMORY"
  --time="$TIME_LIMIT"
  --no-requeue
  --output="$SUBMISSION_DIR/slurm-%j.out"
  --error="$SUBMISSION_DIR/slurm-%j.err"
  --export="ALL,RBP_BUNDLE_ROOT=$BUNDLE_ROOT,RBP_ENV_PREFIX=$ENV_PREFIX"
)
[[ -n "$ACCOUNT" ]] && SBATCH_ARGS+=(--account="$ACCOUNT")
[[ -n "$PARTITION" ]] && SBATCH_ARGS+=(--partition="$PARTITION")

printf 'Submitting CPU-only R2 probe (no GPU):\n'
printf '  bundle:   %s\n' "$BUNDLE_ROOT"
printf '  env:      %s\n' "$ENV_PREFIX"
printf '  CPUs:     4\n'
printf '  memory:   %s\n' "$MEMORY"
printf '  time:     %s\n' "$TIME_LIMIT"
printf '  account:  %s\n' "${ACCOUNT:-Newton default}"
printf '  partition:%s\n' "${PARTITION:-Newton default}"

SUBMISSION=$(sbatch "${SBATCH_ARGS[@]}" "$BUNDLE_ROOT/hpc/newton/002c_r2/RUN_R2_PROBE.sbatch")
printf '%s\n' "$SUBMISSION" | tee "$SUBMISSION_DIR/submission.txt"
printf 'Use 03_CHECK_STATUS.sh to monitor the job.\n'
