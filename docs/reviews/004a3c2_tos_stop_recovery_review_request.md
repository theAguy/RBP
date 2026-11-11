# Task 004A-3C-2 ToS stop and bounded recovery review request

## Verdict requested

Return **Approve**, **Approve with bounded corrections**, or **Stop** for the
synthetic-only recovery implementation. Do not run or authorize it.

## Preserved stop evidence

The one authorized CPU job, `543090`, ran for 7 minutes 31 seconds on Darwin
node `galileo3` with four CPUs, 32 GiB requested RAM and no GPU. It returned a
valid sanitized `STOPPED` archive:

- stopped-return SHA-256:
  `056d553286ca60b7f23f89781b79ac5bba30bb6600afefe7232dad3a34ab19c4`;
- explicit-lock SHA-256:
  `4acbb5a8ebf263a7cfc59975d29620ae03a59416046768b0627ad386cd5a67c8`;
- lock entries: exactly 91 unique MD5-bound HTTPS URLs;
- channels: exactly `pytorch`, `nvidia`, and `conda-forge` under
  `conda.anaconda.org`; no `repo.anaconda.com`/`defaults` entry;
- preserved staging prefix:
  `/home/guy.assa/rbp_004a3_env_d11dad1/environment_staging/job_543090/solve_prefix`;
- intended final prefix:
  `/home/guy.assa/.conda/envs/rbpbench-004a3-4acbb5a8ebf2`.

The solve and staging installation completed. The next command recreated the
final prefix from the explicit lock without `--override-channels`. Conda
26.9.3 therefore inspected the user's configured `defaults` channels and
raised `CondaToSNonInteractiveError`. No biological input, cache, GPU or model
operation occurred.

## Correction and recovery contract

Review:

1. `src/rbpbench/environment_recovery_004a3.py`:
   - stdlib-only authentication of the stopped ZIP, exact STOPPED status and
     staging/final path bindings;
   - strict explicit-lock SHA, count, URL, MD5-fragment and exact-channel-set
     validation.
2. `hpc/newton/004a3/02_PREPARE_ENVIRONMENT.sbatch`:
   - future final-prefix recreation is offline and uses explicit channel
     override; no scientific package specification changes.
3. `hpc/newton/004a3/02_RECOVER_ENVIRONMENT.sbatch`:
   - authenticates the prior return/lock before final-prefix creation;
   - re-exports the live staging lock and requires byte equality;
   - does not solve, modify or remove the preserved staging prefix;
   - recreates the final prefix offline from cached explicit packages with
     `--copy`, `--override-channels`, and the same three channels;
   - compares staging/final package JSON, verifies frozen runtime versions,
     builds the complete runtime manifest, runs all five focused suites,
     verifies again after making the prefix read-only, and writes separate
     COMPLETED/STOPPED recovery evidence.
4. `hpc/newton/004a3/02_SUBMIT_ENVIRONMENT_RECOVERY.sh`:
   - CPU-only, fail-closed typed inputs, absent final prefix, and entirely new
     recovery work/return roots.
5. `tests/test_rescnn_004a3.py`:
   - valid and adversarial lock/return validation;
   - static prevention of a new solve, online recreation, staging deletion,
     evidence reuse, final-prefix overwrite or GPU request.
6. `docs/handoffs/004a3c2_darwin_environment_recovery_execution.md`:
   - exact source/evidence bindings, fresh checkout, single-use gate and
     submission token, shared-home proof, separate accounting/return paths,
     and explicit no-delete/no-retry rules.

## Review questions

1. Does the evidence prove this was only an unnecessary configured-channel
   ToS failure after a successful solve?
2. Does the recovery authenticate and reuse the exact preserved staging state
   without solving or silently selecting new packages?
3. Is `--offline --override-channels -c pytorch -c nvidia -c conda-forge`
   appropriate for final-prefix creation from the MD5-bound explicit lock?
4. Are failure residues and all old evidence preserved, with no automatic
   retry or deletion?
5. Are the runtime, focused-suite, immutability and return gates sufficient to
   accept the recovered environment for later 3C-3 planning?
6. Is any additional issue genuinely blocking before a separate recovery
   execution handoff is prepared?

## Hard boundary

Static review only. Do not connect to Darwin/Newton, accept Anaconda terms,
install packages, submit Slurm, access biological data, use CUDA, build the
cache/bundle, or authorize 3C-3/3D/004A-4.

## Reported synthetic verification

- corrected `test_rescnn_004a3.py`: 48 passed, 53 subtests, one pre-existing
  warning;
- complete focused run 1: 112 passed, 73 subtests, two pre-existing warnings,
  97.13 seconds;
- complete focused run 2: 112 passed, 73 subtests, two pre-existing warnings,
  89.96 seconds;
- the corrected test module fails during collection on parent `a9c6475`
  because the authenticated recovery module does not exist there;
- every `hpc/newton/004a3` shell script passes `/bin/bash -n`, the new module
  compiles, and `git diff --check` is clean.
