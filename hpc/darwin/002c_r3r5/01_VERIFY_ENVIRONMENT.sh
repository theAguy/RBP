#!/usr/bin/env bash
set -Eeuo pipefail

# Verifies (never installs or modifies) the accepted Darwin Linux environment
# created for Task 002C-R2.  Its runtime receipt, explicit lock, package list
# and MMseqs2 binary hashes are frozen in the R3–R5 contract; a re-installed
# environment would produce a different receipt and requires review.

BUNDLE_ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
ENV_PREFIX=${RBP_DARWIN_ENV_PREFIX:-"$HOME/.conda/envs/rbpbench-r2-newton"}
if [[ ! -x "$ENV_PREFIX/bin/python" ]]; then
  printf 'The accepted Darwin environment is absent at %s.\n' "$ENV_PREFIX" >&2
  printf 'Set RBP_DARWIN_ENV_PREFIX to its location. Do not reinstall without review: the receipt hash is frozen.\n' >&2
  exit 1
fi
export PYTHONPATH="$BUNDLE_ROOT/src" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
"$ENV_PREFIX/bin/python" -m rbpbench.splits.r3r5.darwin verify-environment \
  --bundle-root "$BUNDLE_ROOT" --runtime-receipt "$ENV_PREFIX/newton_runtime_receipt.json"
printf '\nEnvironment verified. Next: 02_SUBMIT_R3R5.sh\n'
