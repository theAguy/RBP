# Task 004A-3C-2 Darwin environment recovery execution handoff

## Boundary

This handoff authorizes no execution by itself. After independent approval and
explicit owner authorization, it permits exactly one CPU-only Darwin recovery
job. The job must reuse the authenticated staging environment from stopped job
`543090`; it must not solve, accept Anaconda terms, access biological data,
request a GPU, build the cache/bundle, train, or begin 3C-3/3D/004A-4.

The old checkout, stopped return, work directory and staging prefix are
immutable evidence. Never delete, edit, enter for development, or reuse them.

## Fixed evidence and source

- recovery source commit: `57c237231c00f41faf9c01e46418f51fec4d52ef`;
- old source commit: `d11dad131d4a964a24bdd0a2dc46f6a76ba7686b`;
- stopped job: `543090`;
- stopped return SHA-256:
  `056d553286ca60b7f23f89781b79ac5bba30bb6600afefe7232dad3a34ab19c4`;
- explicit lock SHA-256:
  `4acbb5a8ebf263a7cfc59975d29620ae03a59416046768b0627ad386cd5a67c8`;
- explicit lock entries: `91`;
- final prefix: `$HOME/.conda/envs/rbpbench-004a3-4acbb5a8ebf2`.

## Darwin preflight

Connect to Darwin and resolve the already-installed general Conda. Do not
install or configure Conda and do not accept any channel terms:

```bash
ssh guy.assa@132.68.38.100

export RBP_004A3_CONDA_EXE="$HOME/.local/rbpbench-miniconda-py311-26.9.3/bin/conda"
export RBP_004A3_STOPPED_ROOT="$HOME/rbp_004a3_env_d11dad1"
export RBP_004A3_STOPPED_JOB_ID=543090
export RBP_004A3_STOPPED_RETURN_SHA256=056d553286ca60b7f23f89781b79ac5bba30bb6600afefe7232dad3a34ab19c4
export RBP_004A3_LOCK_SHA256=4acbb5a8ebf263a7cfc59975d29620ae03a59416046768b0627ad386cd5a67c8
export RBP_004A3_LOCK_ENTRY_COUNT=91
export RBP_004A3_RECOVERY_CHECKOUT="$HOME/rbp_004a3_env_recovery_57c2372"
export RBP_004A3_RECOVERY_EVIDENCE="$HOME/rbp_004a3_env_recovery_57c2372_pre_submission.txt"

DARWIN_HOME=$(cd "$HOME" && pwd -P)
FREE_HOME_KIB=$(df -Pk "$HOME" | awk 'NR==2 {print $4}')
PUBLIC_PARTITION=$(sinfo -h -p public -o '%P|%l|%G|%f')
export DARWIN_HOME FREE_HOME_KIB PUBLIC_PARTITION
```

Verify the preserved evidence without changing it:

```bash
OLD_RETURN="$RBP_004A3_STOPPED_ROOT/environment_return/RBP_004A3_ENVIRONMENT_RETURN.zip"
OLD_LOCK="$RBP_004A3_STOPPED_ROOT/environment_work/job_543090/environment.lock"
OLD_STAGING="$RBP_004A3_STOPPED_ROOT/environment_staging/job_543090/solve_prefix"
FINAL="$HOME/.conda/envs/rbpbench-004a3-4acbb5a8ebf2"
export OLD_RETURN OLD_LOCK OLD_STAGING FINAL

printf 'old_return_sha256=%s\n' "$(sha256sum "$OLD_RETURN" | awk '{print $1}')"
printf 'old_lock_sha256=%s\n' "$(sha256sum "$OLD_LOCK" | awk '{print $1}')"
test -d "$OLD_STAGING" && test ! -L "$OLD_STAGING"
test ! -e "$FINAL"
```

Create one new recovery checkout. It must be absent, and the old checkout is
not modified:

```bash
cd "$HOME"
unset RBP_004A3_RECOVERY_CHECKOUT_WAS_ABSENT
if test ! -e "$RBP_004A3_RECOVERY_CHECKOUT"; then
  if git clone --branch issue-003b-simple-baselines \
    https://github.com/theAguy/RBP.git "$RBP_004A3_RECOVERY_CHECKOUT"; then
    export RBP_004A3_RECOVERY_CHECKOUT_WAS_ABSENT=1
    cd "$RBP_004A3_RECOVERY_CHECKOUT"
    git checkout --detach 57c237231c00f41faf9c01e46418f51fec4d52ef
    test "$(git rev-parse HEAD)" = 57c237231c00f41faf9c01e46418f51fec4d52ef
    test -z "$(git status --porcelain --untracked-files=all)"
  else
    echo 'STOP: recovery clone failed; preserve the partial checkout'
  fi
else
  echo 'STOP: recovery checkout already exists; do not enter, edit or delete it'
fi
```

Prove the shared-home view from Newton:

```bash
NEWTON_HOME=$(ssh guy.assa@newton 'cd "$HOME" && pwd -P')
unset RBP_004A3_RECOVERY_NEWTON_VISIBLE
if test "$NEWTON_HOME" = "$DARWIN_HOME" && ssh guy.assa@newton \
  "test -d '$DARWIN_HOME/rbp_004a3_env_recovery_57c2372' && stat '$DARWIN_HOME/rbp_004a3_env_recovery_57c2372'"; then
  export RBP_004A3_RECOVERY_NEWTON_VISIBLE=1
else
  echo 'STOP: recovery checkout is not identically visible from Newton'
fi
```

If the Newton hostname does not resolve/authenticate, stop and report it. Do
not try another hostname.

## One-time final gate

Run this block once. It writes a durable evidence file; that file and the new
checkout make the approval non-replayable:

```bash
unset RBP_004A3_RECOVERY_PREFLIGHT_OK
if case "$RBP_004A3_CONDA_EXE" in /*) true;; *) false;; esac \
  && test -x "$RBP_004A3_CONDA_EXE" \
  && "$RBP_004A3_CONDA_EXE" --version \
  && test -n "$PUBLIC_PARTITION" \
  && case "$FREE_HOME_KIB" in ''|*[!0-9]*) false;; *) true;; esac \
  && test "$FREE_HOME_KIB" -ge 52428800 \
  && test "$NEWTON_HOME" = "$DARWIN_HOME" \
  && test "${RBP_004A3_RECOVERY_CHECKOUT_WAS_ABSENT:-}" = 1 \
  && test "${RBP_004A3_RECOVERY_NEWTON_VISIBLE:-}" = 1 \
  && test "$(git rev-parse HEAD)" = 57c237231c00f41faf9c01e46418f51fec4d52ef \
  && test -z "$(git status --porcelain --untracked-files=all)" \
  && test "$(git -C "$RBP_004A3_STOPPED_ROOT" rev-parse HEAD)" = d11dad131d4a964a24bdd0a2dc46f6a76ba7686b \
  && git -C "$RBP_004A3_STOPPED_ROOT" diff --quiet \
  && git -C "$RBP_004A3_STOPPED_ROOT" diff --cached --quiet \
  && test "$(sha256sum "$OLD_RETURN" | awk '{print $1}')" = "$RBP_004A3_STOPPED_RETURN_SHA256" \
  && test "$(sha256sum "$OLD_LOCK" | awk '{print $1}')" = "$RBP_004A3_LOCK_SHA256" \
  && test -d "$OLD_STAGING" && test ! -L "$OLD_STAGING" \
  && test ! -e "$FINAL" \
  && test ! -e "$RBP_004A3_RECOVERY_EVIDENCE" \
  && test ! -e environment_recovery_work \
  && test ! -e environment_recovery_return; then
  {
    printf 'darwin_home=%s\n' "$DARWIN_HOME"
    printf 'newton_home=%s\n' "$NEWTON_HOME"
    printf 'conda_executable=%s\n' "$RBP_004A3_CONDA_EXE"
    printf 'stopped_job_id=%s\n' "$RBP_004A3_STOPPED_JOB_ID"
    printf 'stopped_return_sha256=%s\n' "$RBP_004A3_STOPPED_RETURN_SHA256"
    printf 'environment_lock_sha256=%s\n' "$RBP_004A3_LOCK_SHA256"
    printf 'environment_lock_entry_count=%s\n' "$RBP_004A3_LOCK_ENTRY_COUNT"
    printf 'staging_prefix=%s\n' "$OLD_STAGING"
    printf 'final_prefix=%s\n' "$FINAL"
    printf 'free_home_kib=%s\n' "$FREE_HOME_KIB"
    printf 'public_partition=%s\n' "$PUBLIC_PARTITION"
  } > "$RBP_004A3_RECOVERY_EVIDENCE"
  export RBP_004A3_RECOVERY_PREFLIGHT_OK=1
  echo RECOVERY_PREFLIGHT_OK
else
  echo 'RECOVERY_PREFLIGHT_FAILED: stop and report; do not submit'
fi
```

## Submit once

Only after `RECOVERY_PREFLIGHT_OK`, run once:

```bash
test "${RBP_004A3_RECOVERY_PREFLIGHT_OK:-}" = 1 \
  && test -s "$RBP_004A3_RECOVERY_EVIDENCE" \
  && export RBP_004A3_CPU_PARTITION=public \
  && unset RBP_004A3_CPU_ACCOUNT \
  && export RBP_SLURM_MAIL_USER=guyassa@gmail.com \
  && bash hpc/newton/004a3/02_SUBMIT_ENVIRONMENT_RECOVERY.sh
RBP_004A3_RECOVERY_SUBMIT_STATUS=$?
unset RBP_004A3_RECOVERY_PREFLIGHT_OK RBP_004A3_RECOVERY_CHECKOUT_WAS_ABSENT
if test "$RBP_004A3_RECOVERY_SUBMIT_STATUS" -eq 0; then
  echo 'RECOVERY_SUBMISSION_ACCEPTED: approval consumed'
else
  echo 'RECOVERY_SUBMISSION_FAILED: stop and report; do not resubmit'
fi
```

Record the printed job ID. Never run the submission or final-gate block again.
A disconnect after cloning ends the checkpoint: preserve everything and
report; do not delete or reuse either checkout.

## Monitor and return

Read-only monitoring may be repeated:

```bash
export JOB_ID=REPLACE_WITH_RECOVERY_JOB_ID
squeue -j "$JOB_ID" -o '%.18i %.12P %.28j %.10T %.12M %.12l %.6D %R'
sacct -j "$JOB_ID" --format=JobID,JobName,State,ExitCode,Elapsed,MaxRSS,ReqMem,AllocCPUS
tail -n 100 "slurm-004a3-env-recovery-${JOB_ID}.out" 2>/dev/null || true
tail -n 100 "slurm-004a3-env-recovery-${JOB_ID}.err" 2>/dev/null || true
```

After it leaves the queue, save accounting:

```bash
sacct -j "$JOB_ID" -P \
  --format=JobID,State,ExitCode,Partition,Account,NodeList,ReqTRES,AllocTRES,AllocCPUS,ReqMem,Elapsed,MaxRSS \
  > "$RBP_004A3_RECOVERY_CHECKOUT/sacct-004a3-env-recovery-${JOB_ID}.txt"
grep -q "^${JOB_ID}|" "$RBP_004A3_RECOVERY_CHECKOUT/sacct-004a3-env-recovery-${JOB_ID}.txt"
```

Verify the produced return without changing it:

```bash
cd "$RBP_004A3_RECOVERY_CHECKOUT/environment_recovery_return"
sha256sum -c RBP_004A3_ENVIRONMENT_RECOVERY_RETURN.zip.sha256
unzip -t RBP_004A3_ENVIRONMENT_RECOVERY_RETURN.zip
unzip -p RBP_004A3_ENVIRONMENT_RECOVERY_RETURN.zip \
  'RBP_004A3_ENVIRONMENT_RECOVERY_RETURN/STATUS.json'
```

From the local Mac terminal, download only the recovery evidence into a new
directory:

```bash
cd /Users/guyassa/Desktop/Technion_courses/winter_2026/bioinformatics
export JOB_ID=REPLACE_WITH_RECOVERY_JOB_ID
mkdir -p artifacts/teammate_run_results/004a3c2_darwin_environment_recovery

scp \
  guy.assa@132.68.38.100:/home/guy.assa/rbp_004a3_env_recovery_57c2372/environment_recovery_return/RBP_004A3_ENVIRONMENT_RECOVERY_RETURN.zip \
  guy.assa@132.68.38.100:/home/guy.assa/rbp_004a3_env_recovery_57c2372/environment_recovery_return/RBP_004A3_ENVIRONMENT_RECOVERY_RETURN.zip.sha256 \
  artifacts/teammate_run_results/004a3c2_darwin_environment_recovery/

scp \
  "guy.assa@132.68.38.100:/home/guy.assa/rbp_004a3_env_recovery_57c2372/slurm-004a3-env-recovery-${JOB_ID}.out" \
  "guy.assa@132.68.38.100:/home/guy.assa/rbp_004a3_env_recovery_57c2372/slurm-004a3-env-recovery-${JOB_ID}.err" \
  "guy.assa@132.68.38.100:/home/guy.assa/rbp_004a3_env_recovery_57c2372/sacct-004a3-env-recovery-${JOB_ID}.txt" \
  guy.assa@132.68.38.100:/home/guy.assa/rbp_004a3_env_recovery_57c2372_pre_submission.txt \
  artifacts/teammate_run_results/004a3c2_darwin_environment_recovery/

cd artifacts/teammate_run_results/004a3c2_darwin_environment_recovery
shasum -a 256 -c RBP_004A3_ENVIRONMENT_RECOVERY_RETURN.zip.sha256
unzip -t RBP_004A3_ENVIRONMENT_RECOVERY_RETURN.zip
```

Do not download the staging/final prefix. Do not delete any remote file. If a
listed Slurm file is absent, return the files that exist and report the missing
one; do not create a replacement. Return COMPLETED or STOPPED exactly as
produced; never retry.
