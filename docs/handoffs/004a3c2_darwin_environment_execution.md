# Task 004A-3C-2 Darwin environment execution handoff

## Purpose and boundary

Run exactly one CPU-only Darwin job to create and verify the frozen Linux CUDA
environment needed later by the Newton GPU smoke. This job installs software
only. It does not open biological data, request a GPU, build the development
cache, build the GPU bundle, train a model or authorize 004A-3D/004A-4.

Execution source is commit `d11dad1` on branch
`issue-003b-simple-baselines`. The job is single-shot: submit once, then return
its evidence whether it completes or stops.

## Before submission

Use the Darwin login host, not Newton:

```bash
ssh guy.assa@132.68.38.100
```

Resolve an existing Conda installation to an absolute executable path. Do not
install a new package manager in this checkpoint:

```bash
set -Eeuo pipefail
RBP_004A3_CONDA_EXE=${CONDA_EXE:-$(type -P conda || true)}
if [ -z "$RBP_004A3_CONDA_EXE" ]; then
  for candidate in "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" "$HOME/.conda/bin/conda"; do
    if [ -x "$candidate" ]; then RBP_004A3_CONDA_EXE=$candidate; break; fi
  done
fi
case "$RBP_004A3_CONDA_EXE" in /*) ;; *) echo 'Conda path is not absolute'; false;; esac
test -x "$RBP_004A3_CONDA_EXE"
"$RBP_004A3_CONDA_EXE" --version
python3 --version
export RBP_004A3_CONDA_EXE
```

If this prints no executable path, stop and report that fact. Do not submit.
Save the printed path for `RBP_004A3_CONDA_EXE` below.

Confirm that the CPU partition exists and its listing is non-empty:

```bash
PUBLIC_PARTITION=$(sinfo -h -p public -o '%P|%l|%G|%f')
test -n "$PUBLIC_PARTITION"
printf '%s\n' "$PUBLIC_PARTITION"
scontrol show partition public | head -n 20
```

This is a CPU job. It must not request `--gres` or any GPU.

Record Darwin's real home path and require at least 50 GiB free before cloning:

```bash
DARWIN_HOME=$(cd "$HOME" && pwd -P)
case "$DARWIN_HOME" in /*) ;; *) echo 'Darwin HOME is not absolute'; false;; esac
df -P "$HOME"
FREE_HOME_KIB=$(df -Pk "$HOME" | awk 'NR==2 {print $4}')
case "$FREE_HOME_KIB" in ''|*[!0-9]*) echo 'Cannot read free HOME space'; false;; esac
test "$FREE_HOME_KIB" -ge 52428800
export DARWIN_HOME
```

## Create one clean execution checkout

The directory must not already exist:

```bash
cd "$HOME"
test ! -e "$HOME/rbp_004a3_env_d11dad1"
git clone --branch issue-003b-simple-baselines https://github.com/theAguy/RBP.git rbp_004a3_env_d11dad1
cd "$HOME/rbp_004a3_env_d11dad1"
git checkout --detach d11dad131d4a964a24bdd0a2dc46f6a76ba7686b
test "$(git rev-parse HEAD)" = "d11dad131d4a964a24bdd0a2dc46f6a76ba7686b"
test -z "$(git status --porcelain --untracked-files=all)"
```

Also run the clear check and inspect its single output line:

```bash
git rev-parse HEAD
```

It must print `d11dad131d4a964a24bdd0a2dc46f6a76ba7686b`. If checkout or the
clean-tree check fails, stop without editing the checkout.

From Darwin, prove that Newton sees the same home path and the new checkout.
This is a read-only check and must pass before submission:

```bash
NEWTON_HOME=$(ssh guy.assa@newton 'cd "$HOME" && pwd -P')
test "$NEWTON_HOME" = "$DARWIN_HOME"
ssh guy.assa@newton \
  "test -d '$DARWIN_HOME/rbp_004a3_env_d11dad1' && stat '$DARWIN_HOME/rbp_004a3_env_d11dad1'"
```

Save the pre-submission evidence outside the clean checkout:

```bash
{
  printf 'darwin_home=%s\n' "$DARWIN_HOME"
  printf 'newton_home=%s\n' "$NEWTON_HOME"
  printf 'free_home_kib=%s\n' "$FREE_HOME_KIB"
  df -P "$HOME"
  printf 'conda_executable=%s\n' "$RBP_004A3_CONDA_EXE"
  "$RBP_004A3_CONDA_EXE" --version
  python3 --version
  printf 'public_partition=%s\n' "$PUBLIC_PARTITION"
} > "$HOME/rbp_004a3_env_d11dad1_pre_submission.txt"
```

Confirm all job-owned output roots are absent:

```bash
test ! -e environment_return
test ! -e environment_work
test ! -e environment_staging
```

## Submit once

Use the already validated and exported Conda path:

```bash
export RBP_004A3_CPU_PARTITION=public
unset RBP_004A3_CPU_ACCOUNT
export RBP_SLURM_MAIL_USER=guyassa@gmail.com

bash hpc/newton/004a3/02_SUBMIT_ENVIRONMENT.sh
```

Record the job number printed by `sbatch`:

```bash
export JOB_ID=REPLACE_WITH_PRINTED_JOB_ID
```

Do not run the submit command a second time.

## Monitor

These commands are read-only and may be repeated:

```bash
squeue -j "$JOB_ID" -o '%.18i %.12P %.24j %.10T %.12M %.12l %.6D %R'
sacct -j "$JOB_ID" --format=JobID,JobName,State,ExitCode,Elapsed,MaxRSS,ReqMem,AllocCPUS
tail -n 80 "slurm-004a3-env-${JOB_ID}.out" 2>/dev/null || true
tail -n 80 "slurm-004a3-env-${JOB_ID}.err" 2>/dev/null || true
```

The expected requested resources are four CPUs, 32 GiB RAM, two hours and no
GPU. Email is requested for BEGIN, END and FAIL.

After the job leaves the queue, save the complete scheduler accounting rather
than only printing it:

```bash
sacct -j "$JOB_ID" -P \
  --format=JobID,State,ExitCode,Partition,Account,NodeList,ReqTRES,AllocTRES,AllocCPUS,ReqMem,Elapsed,MaxRSS \
  > "$HOME/rbp_004a3_env_d11dad1/sacct-004a3-env-${JOB_ID}.txt"
```

Do not proceed if this file is empty. The return reviewer will require that
`AllocTRES` contains no `gres/gpu` allocation.

## Verify the return on Darwin

After the job leaves the queue:

```bash
cd "$HOME/rbp_004a3_env_d11dad1/environment_return"
sha256sum -c RBP_004A3_ENVIRONMENT_RETURN.zip.sha256
unzip -t RBP_004A3_ENVIRONMENT_RETURN.zip
unzip -p RBP_004A3_ENVIRONMENT_RETURN.zip \
  'RBP_004A3_ENVIRONMENT_RETURN/STATUS.json'
```

Return `COMPLETED` or `STOPPED` exactly as produced. A stopped run may leave a
large reviewed staging prefix in `environment_staging/`; do not delete it and
do not resubmit. Its path is recorded in `STATUS.json`.

## Download to the local project

Run these commands from the local Mac terminal, not from Darwin:

```bash
cd /Users/guyassa/Desktop/Technion_courses/winter_2026/bioinformatics
mkdir -p artifacts/teammate_run_results/004a3c2_darwin_environment
export JOB_ID=REPLACE_WITH_THE_SAME_JOB_ID
export DARWIN_HOME=REPLACE_WITH_THE_RECORDED_DARWIN_HOME
export REMOTE_ROOT="$DARWIN_HOME/rbp_004a3_env_d11dad1"

scp \
  "guy.assa@132.68.38.100:$REMOTE_ROOT/environment_return/RBP_004A3_ENVIRONMENT_RETURN.zip*" \
  artifacts/teammate_run_results/004a3c2_darwin_environment/

scp \
  "guy.assa@132.68.38.100:$REMOTE_ROOT/slurm-004a3-env-${JOB_ID}.out" \
  "guy.assa@132.68.38.100:$REMOTE_ROOT/slurm-004a3-env-${JOB_ID}.err" \
  "guy.assa@132.68.38.100:$REMOTE_ROOT/sacct-004a3-env-${JOB_ID}.txt" \
  "guy.assa@132.68.38.100:$DARWIN_HOME/rbp_004a3_env_d11dad1_pre_submission.txt" \
  artifacts/teammate_run_results/004a3c2_darwin_environment/

cd artifacts/teammate_run_results/004a3c2_darwin_environment
shasum -a 256 -c RBP_004A3_ENVIRONMENT_RETURN.zip.sha256
unzip -t RBP_004A3_ENVIRONMENT_RETURN.zip
```

If a Slurm log is absent, download the files that exist and report the missing
one; do not create a replacement.

## Stop rules

- Exactly one submission.
- No script edits on Darwin.
- No manual package changes or pip installation.
- No removal of a failed staging or final prefix.
- No retry after STOPPED or scheduler failure.
- No real-data access, cache build, bundle build, GPU request or training.
- Return the ZIP, checksum and Slurm logs for local review before any next step.

## Acceptance review

The return reviewer will independently check the lock and runtime-manifest
hashes, exact packages, Torch/CUDA/NumPy/cuDNN evidence, channel and host
evidence, focused-test results, manifest revalidation, read-only prefix,
resource use, package-cache growth and return sanitation. Only an accepted
`COMPLETED` return can lead to a separate 3C-3 cache/bundle authorization.
