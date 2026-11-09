#!/usr/bin/env bash
set -Eeuo pipefail

: "${RBP_004A3_DISCOVERY:?accepted discovery JSON required}"
: "${RBP_004A3_LOCK:?accepted explicit lock required}"
: "${RBP_004A3_LOCK_SHA256:?accepted lock SHA-256 required}"

INSTALL_LOCATION=$(python3 - "$RBP_004A3_DISCOVERY" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
where=d.get("site_approved_install_location")
if where not in ("login_node", "cpu_job"):
    raise SystemExit("discovery has no reviewed install location")
print(where)
PY
)
if [[ "$INSTALL_LOCATION" == cpu_job && -z "${SLURM_JOB_ID:-}" ]]; then
  printf 'Discovery requires installation inside a CPU job.\n' >&2; exit 1
fi
if [[ "$INSTALL_LOCATION" == login_node && -n "${SLURM_JOB_ID:-}" ]]; then
  printf 'Discovery requires login-node installation, not this job.\n' >&2; exit 1
fi
printf '%s  %s\n' "$RBP_004A3_LOCK_SHA256" "$RBP_004A3_LOCK" | sha256sum --check --status
PREFIX=${RBP_004A3_ENV_PREFIX:-"$HOME/.conda/envs/rbpbench-004a3-${RBP_004A3_LOCK_SHA256:0:12}"}
[[ ! -e "$PREFIX" ]] || { printf 'Refusing existing unverified prefix: %s\n' "$PREFIX" >&2; exit 1; }
conda create --yes --prefix "$PREFIX" --file "$RBP_004A3_LOCK"
printf 'Environment installed at %s; runtime-manifest construction/review is required before smoke.\n' "$PREFIX"
