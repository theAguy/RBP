#!/usr/bin/env bash
#SBATCH --job-name=rbp-004a3-env-recovery
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --no-requeue
#SBATCH --output=slurm-004a3-env-recovery-%j.out
#SBATCH --error=slurm-004a3-env-recovery-%j.err
set -Eeuo pipefail

: "${RBP_004A3_ROOT:?recovery checkout root required}"
: "${RBP_004A3_CONDA_EXE:?validated Conda executable required}"
: "${RBP_004A3_STOPPED_ROOT:?stopped checkout root required}"
: "${RBP_004A3_STOPPED_JOB_ID:?stopped job ID required}"
: "${RBP_004A3_STOPPED_RETURN_SHA256:?stopped-return SHA-256 required}"
: "${RBP_004A3_LOCK_SHA256:?environment-lock SHA-256 required}"
: "${RBP_004A3_LOCK_ENTRY_COUNT:?environment-lock entry count required}"

ROOT=$(cd "$RBP_004A3_ROOT" && pwd -P)
PRIOR_ROOT=$(cd "$RBP_004A3_STOPPED_ROOT" && pwd -P)
CONDA_EXE=$RBP_004A3_CONDA_EXE
PRIOR_JOB_ID=$RBP_004A3_STOPPED_JOB_ID
WORK="$ROOT/environment_recovery_work/job_${SLURM_JOB_ID:-unknown}"
RETURN="$ROOT/environment_recovery_return"
PRIOR_WORK="$PRIOR_ROOT/environment_work/job_${PRIOR_JOB_ID}"
STAGING="$PRIOR_ROOT/environment_staging/job_${PRIOR_JOB_ID}/solve_prefix"
PRIOR_RETURN="$PRIOR_ROOT/environment_return/RBP_004A3_ENVIRONMENT_RETURN.zip"
FINAL="$HOME/.conda/envs/rbpbench-004a3-${RBP_004A3_LOCK_SHA256:0:12}"
START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
STAGE=initialization
mkdir -p "$WORK" "$RETURN"

package_return() {
  local status=$1 code=$2
  python3 - "$WORK" "$RETURN" "$status" "$code" "$START" "$STAGE" \
    "$STAGING" "$FINAL" "$PRIOR_JOB_ID" <<'PY'
import hashlib, json, pathlib, sys, zipfile
work=pathlib.Path(sys.argv[1]); returned=pathlib.Path(sys.argv[2])
status, code, started, stage, staging, final, prior_job = sys.argv[3:10]
summary={"status":status,"exit_code":int(code),"started_utc":started,
 "stage":stage,"staging_prefix":staging,"final_prefix":final,
 "prior_stopped_job_id":prior_job}
(work/"STATUS.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
archive=returned/"RBP_004A3_ENVIRONMENT_RECOVERY_RETURN.zip"
with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as handle:
    for path in sorted(work.rglob("*")):
        if path.is_file():
            handle.write(path,pathlib.Path("RBP_004A3_ENVIRONMENT_RECOVERY_RETURN")/path.relative_to(work))
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
pathlib.Path(str(archive)+".sha256").write_text(f"{digest}  {archive.name}\n")
PY
}
on_failure() {
  local code=$?
  set +e
  package_return STOPPED "$code"
  exit "$code"
}
trap on_failure ERR INT TERM

STAGE=authenticate_prior_evidence
[[ "$CONDA_EXE" = /* && -x "$CONDA_EXE" ]]
[[ "$PRIOR_JOB_ID" =~ ^[1-9][0-9]*$ ]]
[[ "$RBP_004A3_STOPPED_RETURN_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$RBP_004A3_LOCK_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$RBP_004A3_LOCK_ENTRY_COUNT" =~ ^[1-9][0-9]*$ ]]
[[ -d "$STAGING" && ! -L "$STAGING" ]]
[[ -f "$PRIOR_WORK/environment.lock" && ! -L "$PRIOR_WORK/environment.lock" ]]
[[ -f "$PRIOR_RETURN" && ! -L "$PRIOR_RETURN" ]]
[[ ! -e "$FINAL" ]]
cp "$PRIOR_WORK/environment.lock" "$WORK/environment.lock"
PYTHONPATH=src python3 -m rbpbench.environment_recovery_004a3 \
  --stopped-return "$PRIOR_RETURN" \
  --stopped-return-sha256 "$RBP_004A3_STOPPED_RETURN_SHA256" \
  --staging-prefix "$STAGING" --final-prefix "$FINAL" \
  --lock "$WORK/environment.lock" --lock-sha256 "$RBP_004A3_LOCK_SHA256" \
  --lock-entry-count "$RBP_004A3_LOCK_ENTRY_COUNT" \
  --output "$WORK/recovery_input_validation.json"
"$CONDA_EXE" info --json > "$WORK/conda_info_recovery_before.json"
"$CONDA_EXE" config --show channels > "$WORK/conda_configured_channels.txt"
python3 - "$WORK/conda_info_recovery_before.json" "$WORK/package_cache_before.json" <<'PY'
import json, os, pathlib, sys
d=json.load(open(sys.argv[1])); rows=[]
for raw in d.get('pkgs_dirs',[]):
    path=pathlib.Path(raw); size=0
    if path.exists():
        for root, _, files in os.walk(path):
            for name in files:
                try: size += (pathlib.Path(root)/name).stat().st_size
                except OSError: pass
    rows.append({'path':str(path),'bytes':size})
pathlib.Path(sys.argv[2]).write_text(json.dumps(rows,indent=2,sort_keys=True)+'\n')
PY
python3 - "$WORK/host.json" <<'PY'
import json, pathlib, platform, re, sys
os_release={}
for line in pathlib.Path('/etc/os-release').read_text().splitlines():
    if '=' in line:
        key,value=line.split('=',1); os_release[key]=value.strip('"')
glibc=platform.libc_ver()[1]
parts=tuple(int(value) for value in re.findall(r'\d+',glibc)[:2])
if os_release.get('ID') != 'ubuntu' or parts > (2,35):
    raise SystemExit('recovery host is incompatible with accepted Ubuntu/glibc GPU host')
payload={'os_release':os_release,'kernel':platform.release(),'glibc':glibc}
pathlib.Path(sys.argv[1]).write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY

STAGE=verify_preserved_staging
"$CONDA_EXE" list --explicit --md5 --prefix "$STAGING" > "$WORK/staging_environment.lock"
cmp "$WORK/environment.lock" "$WORK/staging_environment.lock"
"$CONDA_EXE" list --json --prefix "$STAGING" > "$WORK/staging_packages.json"

STAGE=recreate_final_prefix_offline
"$CONDA_EXE" create --yes --copy --offline --override-channels --strict-channel-priority \
  -c pytorch -c nvidia -c conda-forge \
  --prefix "$FINAL" --file "$WORK/environment.lock"

STAGE=verify_final_packages
"$CONDA_EXE" list --json --prefix "$FINAL" > "$WORK/final_packages.json"
cmp "$WORK/staging_packages.json" "$WORK/final_packages.json"

export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 VECLIB_MAXIMUM_THREADS=4
STAGE=verify_runtime_versions
"$FINAL/bin/python" - "$WORK/runtime.json" <<'PY'
import json, numpy, pathlib, torch, sys
if not torch.__version__.startswith('2.5.1'): raise SystemExit('wrong PyTorch version')
if torch.version.cuda != '12.4': raise SystemExit('wrong CUDA runtime')
if numpy.__version__ != '1.26.4': raise SystemExit('wrong NumPy version')
payload={"python":sys.version,"torch":torch.__version__,"torch_cuda":torch.version.cuda,
 "numpy":numpy.__version__,"cudnn":torch.backends.cudnn.version(),"torch_config":torch.__config__.show()}
pathlib.Path(sys.argv[1]).write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY
python3 - "$WORK/final_packages.json" <<'PY'
import json, sys
rows=json.load(open(sys.argv[1])); by_name={row['name']:row for row in rows}
torch=by_name.get('pytorch')
if not torch or torch.get('channel') != 'pytorch': raise SystemExit('PyTorch is not from pytorch channel')
if any(row.get('channel') == 'pypi' for row in rows): raise SystemExit('pypi package is forbidden')
PY
"$CONDA_EXE" --version > "$WORK/conda_version.txt"
printf '%s\n' 'pytorch' 'nvidia' 'conda-forge' > "$WORK/effective_channel_order.txt"

STAGE=build_runtime_manifest
PYTHONPATH=src "$FINAL/bin/python" scripts/build_004a3_runtime_manifest.py \
  --prefix "$FINAL" --output "$WORK/runtime_manifest.json"
RUNTIME_SHA=$(sha256sum "$WORK/runtime_manifest.json" | awk '{print $1}')
printf '{"runtime_manifest_sha256":"%s","environment_lock_sha256":"%s"}\n' \
  "$RUNTIME_SHA" "$RBP_004A3_LOCK_SHA256" > "$WORK/verify_config.json"
python3 - "$WORK/runtime_manifest.json" "$WORK/prefix_summary.json" <<'PY'
import json, pathlib, sys
manifest=json.load(open(sys.argv[1])); entries=manifest['entries']
payload={
 'entry_count':len(entries),
 'file_count':sum(row.get('type') == 'file' for row in entries),
 'symlink_count':sum(row.get('type') == 'symlink' for row in entries),
 'file_bytes':sum(int(row.get('byte_size',0)) for row in entries if row.get('type') == 'file'),
}
pathlib.Path(sys.argv[2]).write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY

STAGE=focused_tests
PYTHONPATH=src "$FINAL/bin/python" -m pytest -q \
  tests/test_rescnn_004a_contract.py tests/test_rescnn_004a_fidelity.py \
  tests/test_rescnn_004a2_data.py tests/test_rescnn_004a2_runtime.py tests/test_rescnn_004a3.py \
  > "$WORK/focused_tests.log"

STAGE=verify_runtime_manifest
PYTHONPATH=src "$FINAL/bin/python" -m rbpbench.rescnn.environment_004a3 \
  --prefix "$FINAL" --manifest "$WORK/runtime_manifest.json" --lock "$WORK/environment.lock" \
  --bundle-config "$WORK/verify_config.json" > "$WORK/runtime_verification.json"
chmod -R a-w "$FINAL"
PYTHONPATH=src "$FINAL/bin/python" -m rbpbench.rescnn.environment_004a3 \
  --prefix "$FINAL" --manifest "$WORK/runtime_manifest.json" --lock "$WORK/environment.lock" \
  --bundle-config "$WORK/verify_config.json" > "$WORK/runtime_readonly_verification.json"

STAGE=record_post_recovery_evidence
"$CONDA_EXE" info --json > "$WORK/conda_info_recovery_after.json"
python3 - "$WORK/conda_info_recovery_after.json" "$WORK/package_cache_after.json" <<'PY'
import json, os, pathlib, sys
d=json.load(open(sys.argv[1])); rows=[]
for raw in d.get('pkgs_dirs',[]):
    path=pathlib.Path(raw); size=0
    if path.exists():
        for root, _, files in os.walk(path):
            for name in files:
                try: size += (pathlib.Path(root)/name).stat().st_size
                except OSError: pass
    rows.append({'path':str(path),'bytes':size})
pathlib.Path(sys.argv[2]).write_text(json.dumps(rows,indent=2,sort_keys=True)+'\n')
PY

STAGE=complete
package_return COMPLETED 0
trap - ERR INT TERM
