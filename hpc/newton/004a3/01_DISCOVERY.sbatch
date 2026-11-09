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
nvidia-smi --query-gpu=name,uuid,memory.total,compute_cap,driver_version \
  --format=csv,noheader > discovery/gpu.csv 2> discovery/gpu_query.stderr || true
CHANNELS_REACHABLE=true
for url in https://conda.anaconda.org/pytorch/ https://conda.anaconda.org/nvidia/ https://conda.anaconda.org/conda-forge/; do
  curl --fail --head --location --max-time 20 "$url" >/dev/null 2>&1 || CHANNELS_REACHABLE=false
done
export CHANNELS_REACHABLE
PYTHONPATH=src python3 - <<'PY'
import getpass, json, os, platform, re, shutil, subprocess
from pathlib import Path
from rbpbench.discovery_004a3 import parse_slurm_max_time

def command_evidence(argv, *, shell=False, first_line=False):
    executable = argv if shell else argv[0]
    available = True if shell else shutil.which(executable) is not None
    if not available:
        return {"available": False, "returncode": None, "stdout": "", "stderr": ""}
    result = subprocess.run(
        argv, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, check=False,
        executable="/bin/bash" if shell else None,
    )
    stdout = result.stdout
    if first_line:
        stdout = stdout.splitlines()[0] if stdout.splitlines() else ""
    return {
        "available": True, "returncode": result.returncode,
        "stdout": stdout, "stderr": result.stderr,
    }

partition = os.environ["SLURM_JOB_PARTITION"]
requested_partition = os.environ.get("RBP_SLURM_PARTITION")
requested_account = os.environ.get("RBP_SLURM_ACCOUNT") or None
slurm_account = os.environ.get("SLURM_JOB_ACCOUNT") or None
partition_detail = command_evidence(["scontrol", "show", "partition", partition])
match = re.search(r"(?:^|\s)MaxTime=([^\s]+)", partition_detail["stdout"])
raw_limit = None if match is None else match.group(1)
slurm_limit_seconds, slurm_limit_error = parse_slurm_max_time(raw_limit)

mem={}
for line in Path('/proc/meminfo').read_text().splitlines():
    key, value = line.split(':',1); mem[key]=int(value.strip().split()[0])*1024
conda_path = shutil.which("conda")
user_name = os.environ.get("USER") or getpass.getuser()
home_path = os.environ.get("HOME") or str(Path.home())
payload = {
  "schema_version": "task004a3_discovery_v2",
  "host": platform.node(), "system": platform.system(), "machine": platform.machine(),
  "allocated_cpus": int(os.environ.get("SLURM_CPUS_PER_TASK", "0")),
  "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
  "slurm_partition": partition,
  "requested_slurm_partition": requested_partition,
  "slurm_account": slurm_account,
  "requested_slurm_account": requested_account,
  "installed_ram_bytes": mem.get("MemTotal"), "available_ram_bytes": mem.get("MemAvailable"),
  "free_disk_bytes": shutil.disk_usage(".").free,
  "quota_available_bytes": int(os.environ["RBP_004A3_QUOTA_AVAILABLE_BYTES"]),
  "operator_quota_available_bytes": int(os.environ["RBP_004A3_QUOTA_AVAILABLE_BYTES"]),
  "slurm_limit_seconds": slurm_limit_seconds,
  "slurm_limit_error": slurm_limit_error,
  "compute_node_required_channels_reachable": os.environ["CHANNELS_REACHABLE"] == "true",
  "site_approved_install_location": os.environ["RBP_004A3_INSTALL_LOCATION"],
  "gpu_csv": Path("discovery/gpu.csv").read_text().strip(),
  "nvidia_smi": command_evidence(["nvidia-smi"])["stdout"],
  "slurm_partition_detail": partition_detail,
  "sinfo_gpu_inventory": command_evidence(["sinfo", "-h", "-o", "%P|%l|%G|%f"]),
  "os_release": command_evidence(["cat", "/etc/os-release"]),
  "uname_kernel": command_evidence(["uname", "-r"]),
  "glibc_version": command_evidence(["ldd", "--version"], first_line=True),
  "conda_command": {
      "available": conda_path is not None, "returncode": 0 if conda_path else None,
      "stdout": "" if conda_path is None else conda_path + "\n", "stderr": "",
  },
  "conda_version": command_evidence(["conda", "--version"]),
  "conda_info": command_evidence(["conda", "info", "--json"]),
  "module_avail": command_evidence("module avail", shell=True),
  "python3_version": command_evidence(["python3", "--version"]),
  "quota_s": command_evidence(["quota", "-s"]),
  "lfs_quota": command_evidence(["lfs", "quota", "-u", user_name, home_path]),
  "df_home": command_evidence(["df", "-B1", home_path]),
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
PYTHONPATH=src python3 -m rbpbench.discovery_004a3 \
  --validate discovery/DISCOVERY.json
printf 'Discovery requires reviewed channel-reachability and install-location fields.\n'
