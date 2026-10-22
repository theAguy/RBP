#!/usr/bin/env bash
set -Eeuo pipefail

BUNDLE_ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
mapfile -t ZIPS < <(find "$BUNDLE_ROOT/return" -maxdepth 1 -type f -name 'RBP_002C_R2_NEWTON_RETURN_*.zip' -print 2>/dev/null | sort)
if [[ ${#ZIPS[@]} -ne 1 ]]; then
  printf 'Expected exactly one return ZIP; found %d.\n' "${#ZIPS[@]}" >&2
  exit 1
fi
ZIP=${ZIPS[0]}
SIDE="$ZIP.sha256"
[[ -f "$SIDE" ]] || { printf 'Missing checksum: %s\n' "$SIDE" >&2; exit 1; }
(cd "$(dirname "$ZIP")" && sha256sum --check "$(basename "$SIDE")")
"${RBP_NEWTON_ENV_PREFIX:-$HOME/.conda/envs/rbpbench-r2-newton}/bin/python" -m zipfile -t "$ZIP"
printf '\nUpload only these two files back to the project owner:\n  %s\n  %s\n' "$ZIP" "$SIDE"
