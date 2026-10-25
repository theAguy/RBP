#!/usr/bin/env bash
set -Eeuo pipefail

: "${RBP_BUNDLE_ROOT:?RBP_BUNDLE_ROOT was not exported by the submit wrapper}"
: "${RBP_ENV_PREFIX:?RBP_ENV_PREFIX was not exported by the submit wrapper}"
: "${RBP_R3R5_MODE:?RBP_R3R5_MODE was not exported by the submit wrapper}"
: "${RBP_JOB_TIME_LIMIT_SECONDS:?RBP_JOB_TIME_LIMIT_SECONDS was not exported by the submit wrapper}"

cd "$RBP_BUNDLE_ROOT"
export PYTHONPATH="$RBP_BUNDLE_ROOT/src"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=4
unset PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH

ARGS=(run --mode "$RBP_R3R5_MODE" --bundle-root "$RBP_BUNDLE_ROOT"
      --runtime-receipt "$RBP_ENV_PREFIX/newton_runtime_receipt.json")
if [[ -n "${RBP_QUOTA_ATTESTATION:-}" ]]; then
  ARGS+=(--quota-attestation "$RBP_QUOTA_ATTESTATION")
fi

# exec: Slurm's B:USR1 advance signal reaches the Python launcher directly.
exec "$RBP_ENV_PREFIX/bin/python" -m rbpbench.splits.r3r5.darwin "${ARGS[@]}"
