#!/usr/bin/env bash
set -Eeuo pipefail

BUNDLE_ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
SUBMISSION="${BUNDLE_ROOT}.slurm_submission/submission.txt"
[[ -f "$SUBMISSION" ]] || { printf 'No submission receipt found.\n' >&2; exit 1; }
JOB_ID=$(grep -Eo '[0-9]+' "$SUBMISSION" | tail -1)
[[ -n "$JOB_ID" ]] || { printf 'Could not parse job ID from %s\n' "$SUBMISSION" >&2; exit 1; }

printf 'Job %s\n' "$JOB_ID"
squeue --jobs="$JOB_ID" --format='%.18i %.12P %.24j %.10T %.12M %.12l %.8C %R' || true
sacct --jobs="$JOB_ID" --format=JobID,JobName%24,State,ExitCode,Elapsed,MaxRSS,ReqMem,AllocCPUS -X || true

if compgen -G "$BUNDLE_ROOT/return/RBP_002C_R2_NEWTON_RETURN_*.zip" >/dev/null; then
  printf '\nReturn is ready:\n'
  find "$BUNDLE_ROOT/return" -maxdepth 1 -type f -name 'RBP_002C_R2_NEWTON_RETURN_*.zip*' -print
fi
