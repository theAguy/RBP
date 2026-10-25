#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
ENV_PREFIX=${RBP_DARWIN_ENV_PREFIX:-"$HOME/.conda/envs/rbpbench-r2-newton"}
PARTITION=${DARWIN_PARTITION:-public}
ACCOUNT=${DARWIN_ACCOUNT:-}
MAIL_USER=${RBP_SLURM_MAIL_USER:-}
RECEIPT="${ROOT}.smoke_submission"
die() { printf '%s\n' "$*" >&2; exit 1; }

command -v sbatch >/dev/null 2>&1 || die "sbatch is unavailable; run on the Darwin login node."
[[ -n "$MAIL_USER" && "$MAIL_USER" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] \
  || die "Set RBP_SLURM_MAIL_USER to your email address."
[[ ! -e "$RECEIPT" ]] || die "Submission receipt already exists: $RECEIPT (do not rerun)."
[[ ! -e "$ROOT/runtime" && ! -e "$ROOT/return" ]] || die "This package was already used; extract a fresh copy."
bash "$ROOT/hpc/darwin/002c_r3r5_smoke/01_VERIFY_PACKAGE_AND_ENV.sh" >/dev/null
mkdir "$RECEIPT"
ARGS=(--parsable --job-name=rbp-r3r5-smoke --partition="$PARTITION" --cpus-per-task=4 --mem=24G
      --time=02:00:00 --no-requeue --mail-type=BEGIN,END,FAIL --mail-user="$MAIL_USER"
      --output="$RECEIPT/slurm-%j.out" --error="$RECEIPT/slurm-%j.err"
      --export="ALL,RBP_SMOKE_ROOT=$ROOT,RBP_ENV_PREFIX=$ENV_PREFIX")
[[ -n "$ACCOUNT" ]] && ARGS+=(--account="$ACCOUNT")
set +e
OUT=$(sbatch "${ARGS[@]}" "$ROOT/hpc/darwin/002c_r3r5_smoke/RUN_SMOKE.sbatch" 2>"$RECEIPT/sbatch.stderr")
STATUS=$?
set -e
if (( STATUS != 0 )); then
  { printf 'sbatch failed with status %d:\n' "$STATUS"; cat "$RECEIPT/sbatch.stderr";
    printf 'Confirm no job exists before removing %s and retrying.\n' "$RECEIPT"; } | tee "$RECEIPT/SUBMIT_FAILED.txt" >&2
  exit "$STATUS"
fi
JOB_ID=${OUT%%;*}
[[ "$JOB_ID" =~ ^[0-9]+$ ]] || die "Unexpected sbatch output: $OUT"
printf '%s\n' "$JOB_ID" > "$RECEIPT/job_id.txt"
printf 'Submitted smoke job %s: 4 CPUs, 24 GiB, 2 hours, no GPU.\n' "$JOB_ID"
printf 'Email notifications: %s\n' "$MAIL_USER"
printf 'Monitor with: bash hpc/darwin/002c_r3r5_smoke/03_CHECK_STATUS_AND_RETURN.sh\n'
