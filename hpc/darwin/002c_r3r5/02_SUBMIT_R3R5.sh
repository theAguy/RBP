#!/usr/bin/env bash
set -Eeuo pipefail

# The single operator entrypoint for Task 002C-R3–R5.  Run once on the Darwin
# login node from a freshly extracted, verified bundle.  Nothing heavy runs
# here: the workflow is submitted to Slurm as one CPU-only job (or, only when
# the partition limit is 20–48 h, one dependency-ordered restart chain whose
# capacity totals at least 48 h).

BUNDLE_ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
SUBMISSION_DIR="${BUNDLE_ROOT}.r3r5_submission"
ENV_PREFIX=${RBP_DARWIN_ENV_PREFIX:-"$HOME/.conda/envs/rbpbench-r2-newton"}
PARTITION=${DARWIN_PARTITION:-public}
ACCOUNT=${DARWIN_ACCOUNT:-}
MEMORY=${DARWIN_MEMORY:-96G}
MAIL_USER=${RBP_SLURM_MAIL_USER:-}
MIN_TOTAL_SECONDS=$((48 * 3600))
MIN_CHAIN_JOB_SECONDS=$((20 * 3600))
PY="$ENV_PREFIX/bin/python"

die() { printf '%s\n' "$*" >&2; exit 1; }

slurm_seconds() {
  # D-HH:MM:SS | HH:MM:SS | MM:SS | MM | infinite/UNLIMITED -> seconds (or "inf")
  local v=$1 d=0 h=0 m=0 s=0
  case "$v" in infinite|UNLIMITED|unlimited) printf 'inf\n'; return 0 ;; esac
  if [[ "$v" =~ ^([0-9]+)-([0-9]+):([0-9]+):([0-9]+)$ ]]; then
    d=$((10#${BASH_REMATCH[1]})); h=$((10#${BASH_REMATCH[2]})); m=$((10#${BASH_REMATCH[3]})); s=$((10#${BASH_REMATCH[4]}))
  elif [[ "$v" =~ ^([0-9]+)-([0-9]+)$ ]]; then
    d=$((10#${BASH_REMATCH[1]})); h=$((10#${BASH_REMATCH[2]}))
  elif [[ "$v" =~ ^([0-9]+):([0-9]+):([0-9]+)$ ]]; then
    h=$((10#${BASH_REMATCH[1]})); m=$((10#${BASH_REMATCH[2]})); s=$((10#${BASH_REMATCH[3]}))
  elif [[ "$v" =~ ^([0-9]+):([0-9]+)$ ]]; then
    m=$((10#${BASH_REMATCH[1]})); s=$((10#${BASH_REMATCH[2]}))
  elif [[ "$v" =~ ^([0-9]+)$ ]]; then
    m=$((10#${BASH_REMATCH[1]}))
  else
    return 1
  fi
  printf '%s\n' "$((d * 86400 + h * 3600 + m * 60 + s))"
}

hms() { local t=$1; printf '%d-%02d:%02d:%02d\n' $((t / 86400)) $((t % 86400 / 3600)) $((t % 3600 / 60)) $((t % 60)); }

memory_mib() {
  local value
  value=$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')
  [[ "$value" =~ ^([0-9]+)([MGT]?)$ ]] || return 1
  local n=$((10#${BASH_REMATCH[1]}))
  case "${BASH_REMATCH[2]}" in ''|M) printf '%s\n' "$n" ;; G) printf '%s\n' "$((n * 1024))" ;; T) printf '%s\n' "$((n * 1048576))" ;; esac
}

command -v sbatch >/dev/null 2>&1 || die "sbatch is unavailable; run this on the Darwin login node."
command -v sinfo >/dev/null 2>&1 || die "sinfo is unavailable; cannot verify the partition time limit."
[[ "$BUNDLE_ROOT" != *,* && "$ENV_PREFIX" != *,* ]] || die "Bundle and environment paths must not contain commas (Slurm --export)."
[[ -x "$PY" ]] || die "Accepted Darwin environment not found at $ENV_PREFIX (see 01_VERIFY_ENVIRONMENT.sh)."
MEMORY_MIB=$(memory_mib "$MEMORY") || die "Invalid DARWIN_MEMORY=$MEMORY (use e.g. 96G)."
(( MEMORY_MIB >= 96 * 1024 )) || die "Refusing DARWIN_MEMORY=$MEMORY: the reviewed request is at least 96G."
[[ -n "$MAIL_USER" && "$MAIL_USER" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] \
  || die "Set RBP_SLURM_MAIL_USER to your email address (the reviewed plan requires email notifications)."

for runtime_dir in r3r5_work returns; do
  [[ ! -e "$BUNDLE_ROOT/$runtime_dir" ]] || die "Refusing a reused bundle: $runtime_dir exists. Use 05_RESUME_R3R5.sh or extract a fresh copy."
done
if [[ -e "$SUBMISSION_DIR" ]]; then
  [[ -f "$SUBMISSION_DIR/SUBMIT_FAILED.txt" ]] && cat "$SUBMISSION_DIR/SUBMIT_FAILED.txt" >&2
  die "Refusing a second submission: $SUBMISSION_DIR already exists."
fi

export PYTHONPATH="$BUNDLE_ROOT/src" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
"$PY" -m rbpbench.splits.r3r5.darwin verify-environment --bundle-root "$BUNDLE_ROOT" \
  --runtime-receipt "$ENV_PREFIX/newton_runtime_receipt.json" >/dev/null \
  || die "The accepted Darwin environment does not verify; do not submit."

MAX_RAW=$(sinfo -h -p "$PARTITION" -o '%l' | head -n 1 | tr -d ' ')
[[ -n "$MAX_RAW" ]] || die "Partition $PARTITION was not found."
MAX_SECONDS=$(slurm_seconds "$MAX_RAW") || die "Cannot parse the partition time limit '$MAX_RAW'."

if [[ "$MAX_SECONDS" == inf ]] || (( MAX_SECONDS >= MIN_TOTAL_SECONDS )); then
  JOB_SECONDS=$MIN_TOTAL_SECONDS
  JOBS=1
elif (( MAX_SECONDS >= MIN_CHAIN_JOB_SECONDS )); then
  JOB_SECONDS=$MAX_SECONDS
  JOBS=$(( (MIN_TOTAL_SECONDS + MAX_SECONDS - 1) / MAX_SECONDS ))
else
  die "Partition $PARTITION allows only $MAX_RAW; the reviewed minimum per job is 20 h. Not submitting."
fi
CHAIN_TOTAL=$((JOB_SECONDS * JOBS))

mkdir "$SUBMISSION_DIR" || die "Refusing a second submission: cannot create $SUBMISSION_DIR."

ATTESTATION=""
set +e
"$PY" -m rbpbench.splits.r3r5.darwin quota-probe --path "$BUNDLE_ROOT" > "$SUBMISSION_DIR/quota_probe.json"
QUOTA_STATUS=$?
set -e
if (( QUOTA_STATUS == 4 )); then
  if [[ "${RBP_CONFIRM_NO_QUOTA_BELOW_80GIB:-}" != "yes" ]]; then
    rm -f "$SUBMISSION_DIR/quota_probe.json"; rmdir "$SUBMISSION_DIR"
    die "Quota is not machine-readable here. After confirming that no quota smaller than 80 GiB applies, rerun with RBP_CONFIRM_NO_QUOTA_BELOW_80GIB=yes."
  fi
  ATTESTATION="$SUBMISSION_DIR/quota_attestation.json"
  "$PY" -m rbpbench.splits.r3r5.darwin attest-quota --bundle-root "$BUNDLE_ROOT" --output "$ATTESTATION" >/dev/null
elif (( QUOTA_STATUS != 0 )); then
  rm -f "$SUBMISSION_DIR/quota_probe.json"; rmdir "$SUBMISSION_DIR"
  die "Quota probe failed unexpectedly (status $QUOTA_STATUS)."
fi

printf '{"partition":"%s","partition_max":"%s","jobs":%d,"job_seconds":%d,"chain_total_seconds":%d,"memory":"%s"}\n' \
  "$PARTITION" "$MAX_RAW" "$JOBS" "$JOB_SECONDS" "$CHAIN_TOTAL" "$MEMORY" > "$SUBMISSION_DIR/plan.json"

PREVIOUS=""
: > "$SUBMISSION_DIR/submission.txt"
for (( k = 1; k <= JOBS; k++ )); do
  MODE=execute; (( k > 1 )) && MODE=resume
  EXPORTS="ALL,RBP_BUNDLE_ROOT=$BUNDLE_ROOT,RBP_ENV_PREFIX=$ENV_PREFIX,RBP_R3R5_MODE=$MODE,RBP_JOB_TIME_LIMIT_SECONDS=$JOB_SECONDS,RBP_QUOTA_ATTESTATION=$ATTESTATION"
  (( JOBS > 1 )) && EXPORTS="$EXPORTS,RBP_CHAIN_TOTAL_SECONDS=$CHAIN_TOTAL"
  # shellcheck disable=SC2054  # commas belong to --mail-type
  ARGS=(--parsable --job-name="rbp-r3r5-$k" --partition="$PARTITION" --cpus-per-task=4 --mem="$MEMORY"
        --time="$(hms "$JOB_SECONDS")" --no-requeue --signal=B:USR1@600
        --mail-type=BEGIN,END,FAIL,TIME_LIMIT_80 --mail-user="$MAIL_USER"
        --output="$SUBMISSION_DIR/slurm-%j.out" --error="$SUBMISSION_DIR/slurm-%j.err" --export="$EXPORTS")
  [[ -n "$ACCOUNT" ]] && ARGS+=(--account="$ACCOUNT")
  [[ -n "$PREVIOUS" ]] && ARGS+=(--dependency="afterany:$PREVIOUS")
  set +e
  OUT=$(sbatch "${ARGS[@]}" "$BUNDLE_ROOT/hpc/darwin/002c_r3r5/RUN_R3R5.sbatch" 2>"$SUBMISSION_DIR/sbatch_$k.stderr")
  STATUS=$?
  set -e
  if (( STATUS != 0 )); then
    { printf 'sbatch for job %d of %d failed (status %d):\n' "$k" "$JOBS" "$STATUS"; cat "$SUBMISSION_DIR/sbatch_$k.stderr"
      printf 'Already submitted (cancel with scancel before any retry): %s\n' "$(tr '\n' ' ' < "$SUBMISSION_DIR/submission.txt")"
      printf 'Recovery: confirm with "squeue --me" that none of those jobs exist, then remove %s and rerun.\n' "$SUBMISSION_DIR"
    } > "$SUBMISSION_DIR/SUBMIT_FAILED.txt"
    cat "$SUBMISSION_DIR/SUBMIT_FAILED.txt" >&2
    exit "$STATUS"
  fi
  JOB_ID=${OUT%%;*}
  [[ "$JOB_ID" =~ ^[0-9]+$ ]] || die "Unexpected sbatch output: $OUT"
  printf '%s %s\n' "$JOB_ID" "$MODE" >> "$SUBMISSION_DIR/submission.txt"
  PREVIOUS=$JOB_ID
done

printf 'Submitted %d CPU-only job(s) (4 CPUs, %s, %s each, no GPU, no requeue):\n' "$JOBS" "$MEMORY" "$(hms "$JOB_SECONDS")"
cat "$SUBMISSION_DIR/submission.txt"
printf 'Monitor with 03_CHECK_STATUS.sh; e-mail notifications go to %s.\n' "$MAIL_USER"
