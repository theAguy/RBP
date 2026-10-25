#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
ENV_PREFIX=${RBP_DARWIN_ENV_PREFIX:-"$HOME/.conda/envs/rbpbench-r2-newton"}
PY="$ENV_PREFIX/bin/python"
[[ -x "$PY" ]] || { printf 'Accepted environment is absent at %s\n' "$ENV_PREFIX" >&2; exit 1; }
"$PY" "$ROOT/hpc/darwin/002c_r3r5_smoke/verify_smoke_package.py" package "$ROOT"
export PYTHONPATH="$ROOT/src" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
"$PY" -m rbpbench.splits.r3r5.darwin verify-environment \
  --bundle-root "$ROOT" --runtime-receipt "$ENV_PREFIX/newton_runtime_receipt.json"
printf '\nPackage and accepted environment verified. No test was launched.\n'
