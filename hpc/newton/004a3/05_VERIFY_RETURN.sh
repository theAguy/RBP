#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd -P)
shopt -s nullglob
zips=("$ROOT"/return/RBP_004A3_RETURN_*.zip)
[[ ${#zips[@]} -eq 1 ]] || { printf 'Expected exactly one return ZIP.\n' >&2; exit 1; }
sha256sum --check "${zips[0]}.sha256"
unzip -t "${zips[0]}"
printf 'Return verified: %s\n' "${zips[0]}"
