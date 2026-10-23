#!/usr/bin/env bash
set -Eeuo pipefail

: "${RBP_BUNDLE_ROOT:?RBP_BUNDLE_ROOT was not exported by the submit wrapper}"
: "${RBP_ENV_PREFIX:?RBP_ENV_PREFIX was not exported by the submit wrapper}"

cd "$RBP_BUNDLE_ROOT"
export PYTHONPATH="$RBP_BUNDLE_ROOT/src"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=4
unset PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH

exec "$RBP_ENV_PREFIX/bin/python" -m rbpbench.splits.newton_002c_r2 \
  --bundle-root "$RBP_BUNDLE_ROOT" \
  --runtime-receipt "$RBP_ENV_PREFIX/newton_runtime_receipt.json"
