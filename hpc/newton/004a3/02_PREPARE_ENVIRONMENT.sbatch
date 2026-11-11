#!/usr/bin/env bash
#SBATCH --job-name=rbp-004a3-env
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --no-requeue
#SBATCH --output=slurm-004a3-env-%j.out
#SBATCH --error=slurm-004a3-env-%j.err
set -Eeuo pipefail

: "${RBP_004A3_ROOT:?bundle/repository root required}"
ROOT=$(cd "$RBP_004A3_ROOT" && pwd -P)
cd "$ROOT"
WORK="$ROOT/environment_work/job_${SLURM_JOB_ID:-unknown}"
RETURN="$ROOT/environment_return"
STAGING="$ROOT/environment_staging/job_${SLURM_JOB_ID:-unknown}/solve_prefix"
FINAL=""
START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
mkdir -p "$WORK" "$RETURN" "$(dirname "$STAGING")"

package_return() {
  local status=$1
  python3 - "$WORK" "$RETURN" "$status" "$START" "$STAGING" "$FINAL" <<'PY'
import hashlib, json, pathlib, sys, zipfile
work = pathlib.Path(sys.argv[1]); returned = pathlib.Path(sys.argv[2])
status, started, staging, final = sys.argv[3:7]
summary={"status":status,"started_utc":started,"staging_prefix":staging,"final_prefix":final}
(work/"STATUS.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
archive=returned/"RBP_004A3_ENVIRONMENT_RETURN.zip"
with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
    for path in sorted(work.rglob("*")):
        if path.is_file(): z.write(path, pathlib.Path("RBP_004A3_ENVIRONMENT_RETURN")/path.relative_to(work))
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
(pathlib.Path(str(archive)+".sha256")).write_text(f"{digest}  {archive.name}\n")
PY
}
on_failure() {
  code=$?
  set +e
  package_return STOPPED
  exit "$code"
}
trap on_failure ERR INT TERM

CONDA_EXE=${RBP_004A3_CONDA_EXE:-$(command -v conda || true)}
if [[ -z "$CONDA_EXE" ]]; then
  for candidate in "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" "$HOME/.conda/bin/conda"; do
    if [[ -x "$candidate" ]]; then CONDA_EXE=$candidate; break; fi
  done
fi
[[ -n "$CONDA_EXE" && -x "$CONDA_EXE" ]] || { echo "Conda executable unavailable" >&2; false; }
"$CONDA_EXE" info --json > "$WORK/conda_info_before.json"
python3 - "$WORK/conda_info_before.json" "$WORK/package_cache_before.json" <<'PY'
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

python3 - <<'PY'
import urllib.request
for url in (
    'https://conda.anaconda.org/pytorch/linux-64/repodata.json',
    'https://conda.anaconda.org/nvidia/linux-64/repodata.json',
    'https://conda.anaconda.org/conda-forge/linux-64/repodata.json',
):
    request=urllib.request.Request(url, headers={'Range':'bytes=0-0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status not in (200, 206): raise SystemExit('channel unreachable: '+url)
PY

python3 - "$WORK/host.json" <<'PY'
import json, pathlib, platform, re, subprocess, sys
os_release={}
for line in pathlib.Path('/etc/os-release').read_text().splitlines():
    if '=' in line:
        k,v=line.split('=',1); os_release[k]=v.strip('"')
glibc=platform.libc_ver()[1]
parts=tuple(int(x) for x in re.findall(r'\d+',glibc)[:2])
if os_release.get('ID') != 'ubuntu' or parts > (2,35):
    raise SystemExit('install host is incompatible with accepted Ubuntu/glibc GPU host')
payload={"os_release":os_release,"kernel":platform.release(),"glibc":glibc}
pathlib.Path(sys.argv[1]).write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY

"$CONDA_EXE" create --yes --prefix "$STAGING" --override-channels --strict-channel-priority \
  -c pytorch -c nvidia -c conda-forge \
  pytorch::pytorch=2.5.1 pytorch::pytorch-cuda=12.4 python=3.11 numpy=1.26.4 'mkl<2024.1' pytest=8
"$CONDA_EXE" list --explicit --md5 --prefix "$STAGING" > "$WORK/environment.lock"
LOCK_SHA=$(sha256sum "$WORK/environment.lock" | awk '{print $1}')
FINAL="$HOME/.conda/envs/rbpbench-004a3-${LOCK_SHA:0:12}"
[[ ! -e "$FINAL" ]] || { echo "Refusing existing final prefix: $FINAL" >&2; false; }
"$CONDA_EXE" create --yes --copy --offline --override-channels --strict-channel-priority \
  -c pytorch -c nvidia -c conda-forge \
  --prefix "$FINAL" --file "$WORK/environment.lock"
"$CONDA_EXE" list --json --prefix "$STAGING" > "$WORK/staging_packages.json"
"$CONDA_EXE" list --json --prefix "$FINAL" > "$WORK/final_packages.json"
cmp "$WORK/staging_packages.json" "$WORK/final_packages.json"

export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 VECLIB_MAXIMUM_THREADS=4
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
"$CONDA_EXE" config --show channels > "$WORK/conda_channels.txt"
printf '%s\n' 'pytorch' 'nvidia' 'conda-forge' > "$WORK/effective_channel_order.txt"

PYTHONPATH=src "$FINAL/bin/python" scripts/build_004a3_runtime_manifest.py \
  --prefix "$FINAL" --output "$WORK/runtime_manifest.json"
RUNTIME_SHA=$(sha256sum "$WORK/runtime_manifest.json" | awk '{print $1}')
printf '{"runtime_manifest_sha256":"%s","environment_lock_sha256":"%s"}\n' "$RUNTIME_SHA" "$LOCK_SHA" > "$WORK/verify_config.json"

PYTHONPATH=src "$FINAL/bin/python" -m pytest -q \
  tests/test_rescnn_004a_contract.py tests/test_rescnn_004a_fidelity.py \
  tests/test_rescnn_004a2_data.py tests/test_rescnn_004a2_runtime.py tests/test_rescnn_004a3.py \
  > "$WORK/focused_tests.log"
PYTHONPATH=src "$FINAL/bin/python" -m rbpbench.rescnn.environment_004a3 \
  --prefix "$FINAL" --manifest "$WORK/runtime_manifest.json" --lock "$WORK/environment.lock" \
  --bundle-config "$WORK/verify_config.json" > "$WORK/runtime_verification.json"
chmod -R a-w "$FINAL"
PYTHONPATH=src "$FINAL/bin/python" -m rbpbench.rescnn.environment_004a3 \
  --prefix "$FINAL" --manifest "$WORK/runtime_manifest.json" --lock "$WORK/environment.lock" \
  --bundle-config "$WORK/verify_config.json" > "$WORK/runtime_readonly_verification.json"

"$CONDA_EXE" info --json > "$WORK/conda_info_after.json"
python3 - "$WORK/conda_info_after.json" "$WORK/package_cache_after.json" <<'PY'
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

rm -rf "$STAGING"
rmdir "$(dirname "$STAGING")"
package_return COMPLETED
trap - ERR INT TERM
