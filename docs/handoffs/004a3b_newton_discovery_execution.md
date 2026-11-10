# Task 004A-3B — Newton discovery operator runbook

**Status:** executed exactly once and closed. Job `1492772` returned the
reviewed data-free evidence. Do not use this historical runbook to resubmit.

**Exact Newton execution commit:**
`e90a26a9fbfc2ac57a83a3d39753f3b2155a5cea`

The discovery is data-free. It inventories the allocated GPU, scheduler,
operating system, available environment tooling, package-channel reachability
and storage evidence. It must not install an environment, build a bundle,
open biological data or launch the GPU resource smoke.

## 1. Prerequisites

On Newton, put the repository at a known location and enter its root. The
examples use `$HOME/rbpbench`; replace that one path consistently if needed.

```bash
cd "$HOME/rbpbench"
git fetch --all --prune
git checkout --detach e90a26a9fbfc2ac57a83a3d39753f3b2155a5cea
test "$(git rev-parse HEAD)" = "e90a26a9fbfc2ac57a83a3d39753f3b2155a5cea"
test -z "$(git status --porcelain --untracked-files=all)"
printf 'Repository root: %s\n' "$(pwd -P)"
test ! -e discovery
```

Stop if any command fails. Do not delete, rename or adopt an existing
`discovery/` directory; return that fact for review.

## 2. Human decisions required before submission

### 2.1 Reviewed Slurm partition and optional account

From Newton documentation or the administrators, identify the GPU partition
that the later resource smoke and 004A-4 jobs are intended to use. Do not rely
on the account's default partition. Export its exact scheduler name:

```bash
export RBP_SLURM_PARTITION='REPLACE_WITH_REVIEWED_GPU_PARTITION'
```

If Newton requires an account for that partition, export the site-approved
account. Otherwise explicitly leave it unset:

```bash
# If required:
export RBP_SLURM_ACCOUNT='REPLACE_WITH_APPROVED_ACCOUNT'
# If not required, use this instead:
# unset RBP_SLURM_ACCOUNT
```

The wrapper passes these values directly to `sbatch`. Discovery records both
requested and allocated routing and fails validation if they disagree. The
same reviewed routing will later be bound into the bundle; the GPU smoke reuse
is implemented only after 004A-3B review during 004A-3C.

### 2.2 Approved installation location

Ask the Newton administrators/site policy whether the later exact environment
may be installed from the login node or must be installed in a CPU-only job.
Choose exactly one reviewed value:

```bash
export RBP_004A3_INSTALL_LOCATION='login_node'
# OR, never both:
# export RBP_004A3_INSTALL_LOCATION='cpu_job'
```

This field records policy only. This discovery job installs nothing.

### 2.3 Current user quota available in bytes

Use the site-supported user-quota command and retain its raw output. For
example, if Newton supports Lustre quota:

```bash
QUOTA_EVIDENCE_COMMAND='lfs quota -u "$USER" "$HOME"'
printf '%s\n' "$QUOTA_EVIDENCE_COMMAND"
eval "$QUOTA_EVIDENCE_COMMAND"
```

If that command is unavailable, use the exact command supplied by the Newton
administrator. Do not substitute filesystem-wide `df` free space for a user
quota. Record the command and its raw output. Lustre commonly reports KiB, so
convert those values to bytes by multiplying by 1,024. When both soft and hard
limits apply, calculate conservatively as
`min(soft_limit_bytes, hard_limit_bytes) - used_bytes`. Export digits only—no
`G`, commas, decimals or spaces:

```bash
export RBP_004A3_QUOTA_AVAILABLE_BYTES='REPLACE_WITH_POSITIVE_INTEGER_BYTES'
[[ "$RBP_004A3_QUOTA_AVAILABLE_BYTES" =~ ^[1-9][0-9]*$ ]]
```

If no supported user-quota evidence can be obtained, stop before submission.

### 2.4 Notification address

```bash
export RBP_SLURM_MAIL_USER='REPLACE_WITH_YOUR_EMAIL'
```

Confirm all required values without printing sensitive unrelated environment
variables:

```bash
printf 'partition=%s\naccount=%s\ninstall_location=%s\nquota_available_bytes=%s\nmail=%s\n' \
  "$RBP_SLURM_PARTITION" \
  "${RBP_SLURM_ACCOUNT:-<site-default-account>}" \
  "$RBP_004A3_INSTALL_LOCATION" \
  "$RBP_004A3_QUOTA_AVAILABLE_BYTES" \
  "$RBP_SLURM_MAIL_USER"
```

## 3. Submit exactly once

Only after review approval and explicit owner authorization:

```bash
bash hpc/newton/004a3/00_SUBMIT_DISCOVERY.sh
```

Record the job ID printed by `sbatch`. Do not run the submission command a
second time for any reason.

Monitor without modifying the job:

```bash
JOB_ID='REPLACE_WITH_PRINTED_JOB_ID'
squeue -j "$JOB_ID" -o '%.18i %.9P %.24j %.8T %.10M %.10l %.6D %R'
sacct -j "$JOB_ID" --format=JobID,JobName,State,ExitCode,Elapsed,MaxRSS,ReqMem,AllocCPUS
```

The expected retained outputs under the repository root are:

- `discovery/DISCOVERY.json`;
- `discovery/RBP_004A3_DISCOVERY_RETURN.zip`;
- `discovery/RBP_004A3_DISCOVERY_RETURN.zip.sha256`; and
- the Slurm standard-output/error logs for the recorded job ID.

Validation happens only after the JSON, ZIP and checksum are written. A
validation failure can therefore make the Slurm job fail while still leaving
a returnable ZIP. Treat that as evidence, not permission to retry.

## 4. Verify and return evidence

From the Newton repository root:

```bash
sha256sum --check discovery/RBP_004A3_DISCOVERY_RETURN.zip.sha256
unzip -t discovery/RBP_004A3_DISCOVERY_RETURN.zip
```

Download only these files to the project owner:

1. `RBP_004A3_DISCOVERY_RETURN.zip`;
2. `RBP_004A3_DISCOVERY_RETURN.zip.sha256`;
3. the Slurm `.out` log for the recorded job ID; and
4. the Slurm `.err` log if the site emitted a separate one.

Do not return the unpacked JSON separately and do not return any environment,
cache, biological-data or model file.

## 5. Stop rules

- One submission only.
- On any preflight, submission, runtime, validation or verification failure,
  do not resubmit and do not edit scripts on Newton.
- Preserve the ZIP/checksum and Slurm logs exactly as produced and return them
  for review.
- Do not install packages or create an environment.
- Do not build the 004A-3 portable bundle or the 8,193/8,193 cache.
- Do not submit the GPU resource smoke or begin 004A-3C, 004A-3D or 004A-4.

## 6. Return-review checklist

The reviewer will authenticate and inspect:

- GPU model, UUID, total memory and compute capability;
- NVIDIA driver and exposed CUDA information;
- partition `MaxTime`; if it is unbounded, the separately reviewed finite
  project-owned limit and its binding;
- requested versus allocated partition/account identity;
- `sinfo` GRES types/features needed to bind the later GPU model request;
- OS release, kernel and glibc;
- conda, Python and module availability;
- required-channel reachability and the approved install-location decision;
- operator quota versus raw `quota`, `lfs quota` and `df -B1` evidence; and
- the success/failure status without treating a packaged validation failure as
  authorization to retry.

No later task is authorized until this evidence receives a separate review.
