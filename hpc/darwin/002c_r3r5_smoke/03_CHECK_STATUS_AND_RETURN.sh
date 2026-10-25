#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
RECEIPT="${ROOT}.smoke_submission"
[[ -f "$RECEIPT/job_id.txt" ]] || { printf 'No successful submission receipt found.\n' >&2; exit 1; }
JOB_ID=$(tr -d '[:space:]' < "$RECEIPT/job_id.txt")
printf 'Job %s\n' "$JOB_ID"
squeue --jobs="$JOB_ID" --format='%.12i %.10P %.18j %.10T %.12M %.12l %.6C %R' 2>/dev/null || true
sacct --jobs="$JOB_ID" --format=JobID,JobName%18,State,ExitCode,Elapsed,MaxRSS,ReqMem,AllocCPUS -X 2>/dev/null || true
shopt -s nullglob
ZIPS=("$ROOT"/return/RBP_002C_R3R5_SMOKE_RETURN_*.zip)
if (( ${#ZIPS[@]} == 0 )); then
  printf '\nNo return yet. The job is still running or return packaging failed. Inspect:\n  %s/slurm-%s.out\n  %s/slurm-%s.err\n' \
    "$RECEIPT" "$JOB_ID" "$RECEIPT" "$JOB_ID"
  exit 0
fi
(( ${#ZIPS[@]} == 1 )) || { printf 'Unexpectedly found multiple returns; stop for review.\n' >&2; exit 1; }
PY=${RBP_DARWIN_ENV_PREFIX:-"$HOME/.conda/envs/rbpbench-r2-newton"}/bin/python
printf '\nReturn verification:\n'
"$PY" "$ROOT/hpc/darwin/002c_r3r5_smoke/verify_smoke_package.py" return "${ZIPS[0]}"
printf '\nDownload exactly these two files:\n  %s\n  %s.sha256\n' "${ZIPS[0]}" "${ZIPS[0]}"
