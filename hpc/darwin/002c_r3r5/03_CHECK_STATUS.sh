#!/usr/bin/env bash
set -Eeuo pipefail

BUNDLE_ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
mapfile -t RECEIPTS < <(ls -1d "${BUNDLE_ROOT}".r3r5_submission "${BUNDLE_ROOT}".r3r5_resume_* 2>/dev/null || true)
(( ${#RECEIPTS[@]} > 0 )) || { printf 'No submission receipt found.\n' >&2; exit 1; }
for receipt in "${RECEIPTS[@]}"; do
  [[ -f "$receipt/submission.txt" ]] || continue
  while read -r JOB_ID MODE; do
    [[ "$JOB_ID" =~ ^[0-9]+$ ]] || continue
    printf '\nJob %s (%s) from %s\n' "$JOB_ID" "$MODE" "$(basename "$receipt")"
    squeue --jobs="$JOB_ID" --format='%.12i %.10P %.16j %.10T %.12M %.12l %.6C %R' 2>/dev/null || true
    sacct --jobs="$JOB_ID" --format=JobID,JobName%16,State,ExitCode,Elapsed,MaxRSS,ReqMem,AllocCPUS -X 2>/dev/null || true
  done < "$receipt/submission.txt"
done
if compgen -G "$BUNDLE_ROOT/returns/RBP_002C_R3R5_RETURN_*.zip" >/dev/null; then
  printf '\nReturns written so far:\n'
  ls -1 "$BUNDLE_ROOT"/returns/RBP_002C_R3R5_RETURN_*.zip
fi
