#!/usr/bin/env bash
#SBATCH --job-name=rbp-004a3-smoke
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --no-requeue
set -Eeuo pipefail

: "${RBP_004A3_ROOT:?bundle root required}"
: "${RBP_004A3_ENV_PREFIX:?verified environment prefix required}"
cd "$RBP_004A3_ROOT"

export PYTHONPATH="$RBP_004A3_ROOT/src"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 VECLIB_MAXIMUM_THREADS=4

[[ ! -e run/STOPPED.json && ! -e run/accepted ]] || {
  printf 'Refusing a completed or stopped smoke without reviewed recovery.\n' >&2; exit 1;
}
CANDIDATE="run/.candidate-${SLURM_JOB_ID}"
mkdir -p "$CANDIDATE"
on_failure() {
  status=$?
  rm -rf -- "$CANDIDATE"
  printf '{"schema_version":"task004a3_stopped_v1","status":"STOPPED","exit_status":%d,"retry_authorized":false}\n' "$status" > run/STOPPED.json
  mkdir -p return
  "$RBP_004A3_ENV_PREFIX/bin/python" -m rbpbench.rescnn.portable_004a3 package-return \
    --root run --payload run/STOPPED.json \
    --destination "return/RBP_004A3_STOPPED_${SLURM_JOB_ID}.zip" || true
  exit "$status"
}
trap on_failure ERR INT TERM
PHYSICAL_GPU_BYTES=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | awk 'NR==1 {printf "%.0f", $1*1024*1024}')
REQUESTED_RAM_BYTES=$((32 * 1024 * 1024 * 1024))
MINIMUM_FREE_DISK_BYTES=$((20 * 1024 * 1024 * 1024))
DEADLINE_MONOTONIC=$("$RBP_004A3_ENV_PREFIX/bin/python" -c 'import time; print(time.monotonic()+13800)')

"$RBP_004A3_ENV_PREFIX/bin/python" -m rbpbench.rescnn.portable_004a3 \
  verify --bundle "$RBP_004A3_ROOT"
read -r RUNTIME_SHA256 SOURCE_SHA256 < <(
  "$RBP_004A3_ENV_PREFIX/bin/python" -c \
    'import json; c=json.load(open("BUNDLE_CONFIG.json")); print(c["runtime_manifest_sha256"], c["source_sha256"])'
)
"$RBP_004A3_ENV_PREFIX/bin/python" -m rbpbench.rescnn.environment_004a3 \
  --prefix "$RBP_004A3_ENV_PREFIX" --manifest manifests/runtime_manifest.json \
  --lock manifests/environment.lock --bundle-config BUNDLE_CONFIG.json

# The accepted suites and data-free probe are hard pre-data gates.
"$RBP_004A3_ENV_PREFIX/bin/python" -m pytest -q \
  tests/test_rescnn_004a_contract.py tests/test_rescnn_004a_fidelity.py \
  tests/test_rescnn_004a2_data.py tests/test_rescnn_004a2_runtime.py \
  tests/test_rescnn_004a3.py
"$RBP_004A3_ENV_PREFIX/bin/python" -m rbpbench.rescnn.runner_004a3 predata-probe \
  --config configs/models/task004a_v1.toml --output "$CANDIDATE/predata_probe.json"
"$RBP_004A3_ENV_PREFIX/bin/python" -m rbpbench.rescnn.runner_004a3 metric-benchmark \
  --bundle-config BUNDLE_CONFIG.json --output "$CANDIDATE/full_metric_benchmark.json"

# Separate Python processes: a failed primary prevents repeat.
"$RBP_004A3_ENV_PREFIX/bin/python" -m rbpbench.rescnn.runner_004a3 run \
  --role primary --config configs/models/task004a_v1.toml --cache data/cache \
  --runtime-manifest-sha256 "$RUNTIME_SHA256" \
  --source-sha256 "$SOURCE_SHA256" \
  --requested-ram-bytes "$REQUESTED_RAM_BYTES" --physical-gpu-bytes "$PHYSICAL_GPU_BYTES" \
  --minimum-free-disk-bytes "$MINIMUM_FREE_DISK_BYTES" --deadline-monotonic "$DEADLINE_MONOTONIC" \
  --output "$CANDIDATE/primary.json"
"$RBP_004A3_ENV_PREFIX/bin/python" -m rbpbench.rescnn.runner_004a3 run \
  --role repeat --config configs/models/task004a_v1.toml --cache data/cache \
  --runtime-manifest-sha256 "$RUNTIME_SHA256" \
  --source-sha256 "$SOURCE_SHA256" \
  --requested-ram-bytes "$REQUESTED_RAM_BYTES" --physical-gpu-bytes "$PHYSICAL_GPU_BYTES" \
  --minimum-free-disk-bytes "$MINIMUM_FREE_DISK_BYTES" --deadline-monotonic "$DEADLINE_MONOTONIC" \
  --output "$CANDIDATE/repeat.json"
"$RBP_004A3_ENV_PREFIX/bin/python" -m rbpbench.rescnn.runner_004a3 compare \
  --primary "$CANDIDATE/primary.json" --repeat "$CANDIDATE/repeat.json" \
  --output "$CANDIDATE/comparison.json"
"$RBP_004A3_ENV_PREFIX/bin/python" -m rbpbench.rescnn.runner_004a3 project \
  --bundle-root "$RBP_004A3_ROOT" --bundle-config BUNDLE_CONFIG.json \
  --primary "$CANDIDATE/primary.json" --repeat "$CANDIDATE/repeat.json" \
  --metric-benchmark "$CANDIDATE/full_metric_benchmark.json" \
  --comparison "$CANDIDATE/comparison.json" --slurm-limit-seconds 14400 \
  --output "$CANDIDATE/FINAL_REPORT.json"
trap - ERR INT TERM
mv "$CANDIDATE" run/accepted
mkdir -p return
"$RBP_004A3_ENV_PREFIX/bin/python" -m rbpbench.rescnn.portable_004a3 package-return \
  --root run/accepted --payload run/accepted/FINAL_REPORT.json \
  --destination "return/RBP_004A3_RETURN_${SLURM_JOB_ID}.zip"
