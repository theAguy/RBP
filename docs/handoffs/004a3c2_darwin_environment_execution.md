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
RBP_004A3_CONDA_EXE=${CONDA_EXE:-$(type -P conda || true)}
if [ -z "$RBP_004A3_CONDA_EXE" ]; then
  for candidate in "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" "$HOME/.conda/bin/conda"; do
    if [ -x "$candidate" ]; then RBP_004A3_CONDA_EXE=$candidate; break; fi
  done
fi
export RBP_004A3_CONDA_EXE
```

The final preflight gate below validates this path. If the gate does not print
`PREFLIGHT_OK`, stop and report the output. Do not submit.

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
unset RBP_004A3_CHECKOUT_WAS_ABSENT
if test ! -e "$HOME/rbp_004a3_env_d11dad1"; then
  if git clone --branch issue-003b-simple-baselines https://github.com/theAguy/RBP.git rbp_004a3_env_d11dad1; then
    export RBP_004A3_CHECKOUT_WAS_ABSENT=1
    cd "$HOME/rbp_004a3_env_d11dad1"
    git checkout --detach d11dad131d4a964a24bdd0a2dc46f6a76ba7686b
    test "$(git rev-parse HEAD)" = "d11dad131d4a964a24bdd0a2dc46f6a76ba7686b"
    test -z "$(git status --porcelain --untracked-files=all)"
  else
    echo 'STOP: clone failed; do not reuse the partial checkout'
  fi
else
  echo 'STOP: execution checkout already exists; do not enter or edit it'
fi
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
unset RBP_004A3_NEWTON_CHECKOUT_VISIBLE
if [ "$NEWTON_HOME" = "$DARWIN_HOME" ]; then
  if ssh guy.assa@newton \
    "test -d '$DARWIN_HOME/rbp_004a3_env_d11dad1' && stat '$DARWIN_HOME/rbp_004a3_env_d11dad1'"; then
    export RBP_004A3_NEWTON_CHECKOUT_VISIBLE=1
  fi
else
  echo 'STOP: Darwin and Newton HOME paths differ'
fi
```

If `ssh guy.assa@newton` does not resolve or authenticate, stop and report it.
Do not try another hostname in this checkpoint.

Run the final preflight gate. It saves evidence outside the clean checkout and
prints `PREFLIGHT_OK` only when every prerequisite still passes:

```bash
unset RBP_004A3_PREFLIGHT_OK
if case "$RBP_004A3_CONDA_EXE" in /*) true;; *) false;; esac \
  && test -x "$RBP_004A3_CONDA_EXE" \
  && "$RBP_004A3_CONDA_EXE" --version \
  && python3 --version \
  && test -n "$PUBLIC_PARTITION" \
  && case "$DARWIN_HOME" in /*) true;; *) false;; esac \
  && case "$FREE_HOME_KIB" in ''|*[!0-9]*) false;; *) true;; esac \
  && test "$FREE_HOME_KIB" -ge 52428800 \
  && test "$NEWTON_HOME" = "$DARWIN_HOME" \
  && test "${RBP_004A3_CHECKOUT_WAS_ABSENT:-}" = 1 \
  && test "${RBP_004A3_NEWTON_CHECKOUT_VISIBLE:-}" = 1 \
  && test "$(git rev-parse HEAD)" = "d11dad131d4a964a24bdd0a2dc46f6a76ba7686b" \
  && test -z "$(git status --porcelain --untracked-files=all)" \
  && test ! -e environment_return \
  && test ! -e environment_work \
  && test ! -e environment_staging; then
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
  export RBP_004A3_PREFLIGHT_OK=1
  printf 'darwin_home=%s\n' "$DARWIN_HOME"
  echo PREFLIGHT_OK
else
  echo 'PREFLIGHT_FAILED: stop and report; do not submit'
fi
```

## Submit once

Use the already validated and exported Conda path:

```bash
: "${RBP_004A3_CONDA_EXE:?re-run preflight}" \
  && case "$RBP_004A3_CONDA_EXE" in /*) true;; *) false;; esac \
  && test -x "$RBP_004A3_CONDA_EXE" \
  && test -s "$HOME/rbp_004a3_env_d11dad1_pre_submission.txt" \
  && test "${RBP_004A3_PREFLIGHT_OK:-}" = 1 \
  && export RBP_004A3_CPU_PARTITION=public \
  && unset RBP_004A3_CPU_ACCOUNT \
  && export RBP_SLURM_MAIL_USER=guyassa@gmail.com \
  && bash hpc/newton/004a3/02_SUBMIT_ENVIRONMENT.sh; RBP_004A3_SUBMIT_STATUS=$?; unset RBP_004A3_PREFLIGHT_OK
if test "$RBP_004A3_SUBMIT_STATUS" -eq 0; then
  echo 'SUBMISSION_ACCEPTED: the one-use preflight approval has been consumed'
else
  echo 'SUBMISSION_FAILED: stop and report; do not run the submit block again'
fi
```

If the SSH session drops before the clone is created, log in again and repeat
the full preflight from the Conda-resolution block. If it drops after cloning,
the existing checkout ends this checkpoint: stop and report it. Do not delete,
enter, edit or reuse the checkout, and do not run only the submit block.

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
grep -q "^${JOB_ID}|" "$HOME/rbp_004a3_env_d11dad1/sacct-004a3-env-${JOB_ID}.txt"
```

If the `grep` check fails, wait briefly and run the two accounting commands
again; this is evidence collection, not a job retry. The return reviewer will require that
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
