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

memory_mib() {
  local value
  value=$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')
  [[ "$value" =~ ^([0-9]+)([KMGT]?)$ ]] || return 1
  local number=$((10#${BASH_REMATCH[1]}))
  case "${BASH_REMATCH[2]}" in
    K) printf '%s\n' "$((number / 1024))" ;;
    ''|M) printf '%s\n' "$number" ;;
    G) printf '%s\n' "$((number * 1024))" ;;
    T) printf '%s\n' "$((number * 1024 * 1024))" ;;
  esac
}

time_seconds() {
  local value=$1 days=0 hours minutes seconds
  if [[ "$value" =~ ^([0-9]+)-([0-9]+):([0-9][0-9]):([0-9][0-9])$ ]]; then
    days=$((10#${BASH_REMATCH[1]})); hours=$((10#${BASH_REMATCH[2]}))
    minutes=$((10#${BASH_REMATCH[3]})); seconds=$((10#${BASH_REMATCH[4]}))
  elif [[ "$value" =~ ^([0-9]+):([0-9][0-9]):([0-9][0-9])$ ]]; then
    hours=$((10#${BASH_REMATCH[1]})); minutes=$((10#${BASH_REMATCH[2]})); seconds=$((10#${BASH_REMATCH[3]}))
  else
    return 1
  fi
  (( minutes < 60 && seconds < 60 )) || return 1
  printf '%s\n' "$((days * 86400 + hours * 3600 + minutes * 60 + seconds))"
}

if ! command -v sbatch >/dev/null 2>&1; then
  printf 'sbatch is unavailable. Run this script on the Newton login node.\n' >&2
  exit 1
fi

[[ "$BUNDLE_ROOT" != *,* && "$ENV_PREFIX" != *,* ]] || {
  printf 'Bundle and environment paths must not contain commas (Slurm --export boundary).\n' >&2
  exit 1
}
MEMORY_MIB=$(memory_mib "$MEMORY") || {
  printf 'Invalid NEWTON_MEMORY %s; use an integer with K/M/G/T suffix (for example 96G).\n' "$MEMORY" >&2
  exit 1
}
TIME_SECONDS=$(time_seconds "$TIME_LIMIT") || {
  printf 'Invalid NEWTON_TIME_LIMIT %s; use HH:MM:SS or D-HH:MM:SS.\n' "$TIME_LIMIT" >&2
  exit 1
}
(( MEMORY_MIB >= 96 * 1024 )) || {
  printf 'Refusing NEWTON_MEMORY=%s: the reviewed minimum is 96G; overrides may only increase it.\n' "$MEMORY" >&2
  exit 1
}
(( TIME_SECONDS >= 8 * 3600 )) || {
  printf 'Refusing NEWTON_TIME_LIMIT=%s: the reviewed minimum is 08:00:00; overrides may only increase it.\n' "$TIME_LIMIT" >&2
  exit 1
}

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

print_failed_submit_recovery() {
  printf '\nNo successful submission receipt was created. Recovery:\n' >&2
  printf '  1. Confirm no job exists: squeue --me --name=rbp-r2-probe\n' >&2
  printf '  2. Only if that shows no job, remove the failed receipt:\n' >&2
  printf '     rm %q\n' "$SUBMISSION_DIR/SUBMIT_FAILED.txt" >&2
  printf '     rmdir %q\n' "$SUBMISSION_DIR" >&2
  printf '  3. Correct the account/partition request and run this submit wrapper once.\n' >&2
}

if [[ -f "$SUBMISSION_DIR/SUBMIT_FAILED.txt" ]]; then
  printf 'A prior scheduler rejection is recorded at %s:\n' "$SUBMISSION_DIR/SUBMIT_FAILED.txt" >&2
  cat "$SUBMISSION_DIR/SUBMIT_FAILED.txt" >&2
  print_failed_submit_recovery
  exit 1
fi

mkdir "$SUBMISSION_DIR" || {
  printf 'Refusing a second submission: receipt directory already exists: %s\n' "$SUBMISSION_DIR" >&2
  exit 1
}
SBATCH_ARGS=(
  --parsable
  --job-name=rbp-r2-probe
  --cpus-per-task=4
  --mem="$MEMORY"
  --time="$TIME_LIMIT"
  --no-requeue
  --signal=B:USR1@600
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

SBATCH_STDERR="$SUBMISSION_DIR/sbatch.stderr.tmp"
set +e
SUBMISSION=$(sbatch "${SBATCH_ARGS[@]}" "$BUNDLE_ROOT/hpc/newton/002c_r2/RUN_R2_PROBE.sbatch" 2>"$SBATCH_STDERR")
SBATCH_STATUS=$?
set -e
if (( SBATCH_STATUS != 0 )); then
  {
    printf 'sbatch exit status: %s\n' "$SBATCH_STATUS"
    printf 'sbatch stderr:\n'
    cat "$SBATCH_STDERR"
    if [[ -n "$SUBMISSION" ]]; then
      printf 'sbatch stdout:\n%s\n' "$SUBMISSION"
    fi
  } > "$SUBMISSION_DIR/SUBMIT_FAILED.txt"
  rm -f "$SBATCH_STDERR"
  cat "$SUBMISSION_DIR/SUBMIT_FAILED.txt" >&2
  print_failed_submit_recovery
  exit "$SBATCH_STATUS"
fi
rm -f "$SBATCH_STDERR"
printf '%s\n' "$SUBMISSION" | tee "$SUBMISSION_DIR/submission.txt"
printf 'Use 03_CHECK_STATUS.sh to monitor the job.\n'
