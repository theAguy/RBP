#!/usr/bin/env bash
#SBATCH --job-name=rbp-004a3-discovery
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:20:00
#SBATCH --no-requeue
set -Eeuo pipefail

: "${RBP_004A3_ROOT:?bundle root required}"
: "${RBP_004A3_INSTALL_LOCATION:?set login_node or cpu_job after site-policy confirmation}"
: "${RBP_004A3_QUOTA_AVAILABLE_BYTES:?machine-readable user quota availability required}"
[[ "$RBP_004A3_INSTALL_LOCATION" == login_node || "$RBP_004A3_INSTALL_LOCATION" == cpu_job ]] || exit 2
cd "$RBP_004A3_ROOT"
mkdir -p discovery
command -v nvidia-smi >/dev/null
nvidia-smi --query-gpu=name,uuid,memory.total,compute_cap,driver_version --format=csv,noheader > discovery/gpu.csv
CHANNELS_REACHABLE=true
for url in https://conda.anaconda.org/pytorch/ https://conda.anaconda.org/nvidia/ https://conda.anaconda.org/conda-forge/; do
  curl --fail --head --location --max-time 20 "$url" >/dev/null 2>&1 || CHANNELS_REACHABLE=false
done
export CHANNELS_REACHABLE
python3 - <<'PY'
import json, os, platform, shutil, subprocess
from pathlib import Path
mem={}
for line in Path('/proc/meminfo').read_text().splitlines():
    key, value = line.split(':',1); mem[key]=int(value.strip().split()[0])*1024
payload = {
  "schema_version": "task004a3_discovery_v1",
  "host": platform.node(), "system": platform.system(), "machine": platform.machine(),
  "allocated_cpus": int(os.environ.get("SLURM_CPUS_PER_TASK", "0")),
  "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
  "slurm_partition": os.environ.get("SLURM_JOB_PARTITION"),
  "installed_ram_bytes": mem.get("MemTotal"), "available_ram_bytes": mem.get("MemAvailable"),
  "free_disk_bytes": shutil.disk_usage(".").free,
  "quota_available_bytes": int(os.environ["RBP_004A3_QUOTA_AVAILABLE_BYTES"]),
  "compute_node_required_channels_reachable": os.environ["CHANNELS_REACHABLE"] == "true",
  "site_approved_install_location": os.environ["RBP_004A3_INSTALL_LOCATION"],
  "gpu_csv": Path("discovery/gpu.csv").read_text().strip(),
  "nvidia_smi": subprocess.run(["nvidia-smi"], text=True, capture_output=True, check=True).stdout,
  "requires_owner_review_before_lock": True,
}
Path("discovery/DISCOVERY.json").write_text(json.dumps(payload, indent=2, sort_keys=True)+"\n")
PY
python3 - <<'PY'
import hashlib, zipfile
from pathlib import Path
destination=Path('discovery/RBP_004A3_DISCOVERY_RETURN.zip')
with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as z:
    z.write('discovery/DISCOVERY.json','RBP_004A3_DISCOVERY_RETURN/DISCOVERY.json')
    z.write('discovery/gpu.csv','RBP_004A3_DISCOVERY_RETURN/gpu.csv')
digest=hashlib.sha256(destination.read_bytes()).hexdigest()
Path(str(destination)+'.sha256').write_text(f'{digest}  {destination.name}\n')
PY
printf 'Discovery requires reviewed channel-reachability and install-location fields.\n'
