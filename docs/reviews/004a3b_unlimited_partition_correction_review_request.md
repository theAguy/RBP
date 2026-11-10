# Task 004A-3B UNLIMITED-partition correction — static review request

**Requested verdict:** Approve, Approve with bounded corrections, or Stop.

Review the bounded correction after parent `63761d7`. This is a static review
only. Do not query Newton, install an environment, build the real cache/bundle,
run CUDA, submit Slurm or authorize 004A-3C/3D/4.

## Required reading

1. `manifests/task004a3b_newton_discovery.json`
2. `docs/reviews/004a3b_newton_discovery_acceptance.md`
3. `docs/tasks/004a3_newton_gpu_resource_smoke.md`
4. `src/rbpbench/discovery_004a3.py`
5. `src/rbpbench/rescnn/projection_004a3.py`
6. `scripts/build_004a3_portable_bundle.py`
7. `hpc/newton/004a3/RUN_004A3_SMOKE.sbatch`
8. the corresponding corrections in `tests/test_rescnn_004a3.py`

## Review questions

1. Does discovery now accept `slurm_limit_seconds=null` only when the exact
   error and raw partition output consistently prove `MaxTime=UNLIMITED` or
   `INFINITE`, while still refusing zero, negative, malformed or contradictory
   evidence?
2. Is the raw scheduler fact kept separate from the finite project-owned
   43,200-second limit, with no rewriting of discovery evidence?
3. Does a finite site partition still stop when it is shorter than the project
   limit?
4. Is `PreemptMode` parsed from bound raw partition evidence, required, and
   propagated into the bundle policy?
5. Is the preemption boundary correct: 004A-3D uses `--no-requeue` and returns
   STOPPED evidence, while 004A-4 remains forbidden until restart safety is
   implemented and reviewed?
6. Does the sanitized manifest accurately bind the returned ZIP/checksum/log
   and extracted member hashes without including biological or row-level data?
7. Do the regressions cover the real UNLIMITED/REQUEUE shape, contradictory
   limit evidence, missing/ambiguous preemption evidence, finite-limit
   conflicts and the smoke's fail-closed no-requeue policy?
8. Has the change avoided environment installation, cache/bundle construction,
   CUDA, Slurm submission and any 004A-3C/3D/4 execution?

If approved, only the correction and the discovery acceptance close. A
separate owner instruction is still required to start 004A-3C.

## Reported verification

The accepted local CPU environment ran the five focused files twice with all
four thread variables set to 4. Each composed run passed **104 tests and 73
subtests**, with no skips. Runtimes were approximately 80.0 s and 77.2 s. The
only warnings were the previously disclosed PyTorch `TypedStorage` deprecation
and the test-only intra-op thread-setting warning.

On a disposable archive of exact parent `63761d7`, the real returned discovery
payload failed with `discovery value must be positive: slurm_limit_seconds`,
and the parent bundle builder had no project-owned scheduler-policy function.
Both conditions pass after this correction. Bash syntax, Python compilation,
JSON validation and `git diff --check` also pass.
