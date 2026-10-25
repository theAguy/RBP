#!/usr/bin/env bash
set -Eeuo pipefail

BUNDLE_ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
ENV_PREFIX=${RBP_DARWIN_ENV_PREFIX:-"$HOME/.conda/envs/rbpbench-r2-newton"}
export PYTHONPATH="$BUNDLE_ROOT/src" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
"$ENV_PREFIX/bin/python" -m rbpbench.splits.r3r5.darwin verify-returns --bundle-root "$BUNDLE_ROOT"
printf '\nUpload every listed return ZIP together with its .sha256 sidecar:\n'
ls -1 "$BUNDLE_ROOT"/returns/RBP_002C_R3R5_RETURN_*.zip "$BUNDLE_ROOT"/returns/RBP_002C_R3R5_RETURN_*.zip.sha256
