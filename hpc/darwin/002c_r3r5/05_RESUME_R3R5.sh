#!/usr/bin/env bash
set -Eeuo pipefail

# Submits ONE resume job, only when the closed decision table allows it
# (scheduler time, caught signal, corrected external resource condition, or
# an unrecorded interruption whose job has ended).  It refuses after any
# scientific, integrity, frozen-limit or tool stop, and after success.

BUNDLE_ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
ENV_PREFIX=${RBP_DARWIN_ENV_PREFIX:-"$HOME/.conda/envs/rbpbench-r2-newton"}
PARTITION=${DARWIN_PARTITION:-public}
ACCOUNT=${DARWIN_ACCOUNT:-}
MEMORY=${DARWIN_MEMORY:-96G}
MAIL_USER=${RBP_SLURM_MAIL_USER:-}
PY="$ENV_PREFIX/bin/python"
die() { printf '%s\n' "$*" >&2; exit 1; }

source_slurm_seconds() {
  local v=$1
  case "$v" in infinite|UNLIMITED|unlimited) printf '%s\n' $((48 * 3600)); return 0 ;; esac
  if [[ "$v" =~ ^([0-9]+)-([0-9]+):([0-9]+):([0-9]+)$ ]]; then
    printf '%s\n' $((10#${BASH_REMATCH[1]} * 86400 + 10#${BASH_REMATCH[2]} * 3600 + 10#${BASH_REMATCH[3]} * 60 + 10#${BASH_REMATCH[4]}))
  elif [[ "$v" =~ ^([0-9]+):([0-9]+):([0-9]+)$ ]]; then
    printf '%s\n' $((10#${BASH_REMATCH[1]} * 3600 + 10#${BASH_REMATCH[2]} * 60 + 10#${BASH_REMATCH[3]}))
  else
    return 1
  fi
}

[[ -x "$PY" ]] || die "Accepted Darwin environment not found at $ENV_PREFIX."
[[ -n "$MAIL_USER" ]] || die "Set RBP_SLURM_MAIL_USER (email notifications are required)."
export PYTHONPATH="$BUNDLE_ROOT/src" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
"$PY" -m rbpbench.splits.r3r5.darwin resume-check --bundle-root "$BUNDLE_ROOT" || die "Resume is not permitted (see the reason above)."
if squeue --me -h -o '%j' 2>/dev/null | grep -q '^rbp-r3r5'; then
  die "An rbp-r3r5 job is still queued or running; wait for it to finish."
fi
MAX_RAW=$(sinfo -h -p "$PARTITION" -o '%l' | head -n 1 | tr -d ' ')
MAX_SECONDS=$(source_slurm_seconds "$MAX_RAW") || die "Cannot parse partition time limit '$MAX_RAW'."
JOB_SECONDS=$(( MAX_SECONDS < 48 * 3600 ? MAX_SECONDS : 48 * 3600 ))
(( JOB_SECONDS >= 20 * 3600 )) || die "Partition allows less than the reviewed 20-h minimum per job."
N=1
while [[ -e "${BUNDLE_ROOT}.r3r5_resume_$N" ]]; do N=$((N + 1)); done
RESUME_DIR="${BUNDLE_ROOT}.r3r5_resume_$N"
mkdir "$RESUME_DIR"
ATTESTATION=""
[[ -f "${BUNDLE_ROOT}.r3r5_submission/quota_attestation.json" ]] && ATTESTATION="${BUNDLE_ROOT}.r3r5_submission/quota_attestation.json"
# shellcheck disable=SC2054  # commas belong to --mail-type
ARGS=(--parsable --job-name="rbp-r3r5-resume-$N" --partition="$PARTITION" --cpus-per-task=4 --mem="$MEMORY"
      --time="$((JOB_SECONDS / 3600)):00:00" --no-requeue --signal=B:USR1@600
      --mail-type=BEGIN,END,FAIL,TIME_LIMIT_80 --mail-user="$MAIL_USER"
      --output="$RESUME_DIR/slurm-%j.out" --error="$RESUME_DIR/slurm-%j.err"
      --export="ALL,RBP_BUNDLE_ROOT=$BUNDLE_ROOT,RBP_ENV_PREFIX=$ENV_PREFIX,RBP_R3R5_MODE=resume,RBP_JOB_TIME_LIMIT_SECONDS=$(( JOB_SECONDS / 3600 * 3600 )),RBP_QUOTA_ATTESTATION=$ATTESTATION")
[[ -n "$ACCOUNT" ]] && ARGS+=(--account="$ACCOUNT")
OUT=$(sbatch "${ARGS[@]}" "$BUNDLE_ROOT/hpc/darwin/002c_r3r5/RUN_R3R5.sbatch")
printf '%s resume\n' "${OUT%%;*}" | tee "$RESUME_DIR/submission.txt"
