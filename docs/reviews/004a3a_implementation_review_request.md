# Task 004A-3A implementation — independent review request

**Requested verdict:** Approve, Approve with bounded corrections, or Stop.

Review the synthetic-only implementation and reported evidence. Do not open
real/ignored inputs, query Newton, install packages, run CUDA, construct the
real subset, submit Slurm or authorize 004A-3B/3C/3D.

## Required reading

1. `docs/tasks/004a3_newton_gpu_resource_smoke.md`
2. `docs/tasks/004a3a_gpu_resource_smoke_implementation.md`
3. `docs/reviews/004a3_gpu_resource_smoke_planning_reconciliation.md`
4. `docs/reviews/004a3a_implementation_report.md`
5. `src/rbpbench/rescnn/adam_004a3.py`
6. `src/rbpbench/rescnn/cache_004a3.py`
7. `src/rbpbench/rescnn/timing_004a3.py`
8. `src/rbpbench/rescnn/projection_004a3.py`
9. `src/rbpbench/rescnn/runtime_004a3.py`
10. `src/rbpbench/rescnn/environment_004a3.py`
11. `src/rbpbench/rescnn/portable_004a3.py`
12. `src/rbpbench/rescnn/runner_004a3.py`
13. the bounded additions to `src/rbpbench/rescnn/checkpoint.py`
14. `scripts/build_004a3_portable_bundle.py`
15. every file under `hpc/newton/004a3/`
16. `tests/test_rescnn_004a3.py`

Inspect the complete implementation diff from its parent. Treat the two
reported test runs as execution evidence, but independently verify that the
tests prove their claims.

## Review questions

1. Is the cache truly mmap-compatible, inventory-bound, development-only and
   fail-closed on identity/content drift?
2. Does the three-step Adam oracle cover parameters, both moment buffers and
   exact step counts under the frozen flags/tolerance?
3. Are timed regions correctly synchronized and inclusive, with warm-up and
   evidence hashing separated as reviewed?
4. Does the worst-case metric fixture enforce exact per-protein counts, both
   classes and distinct float32 known scores at full shape?
5. Are the time/storage equations and GPU/RSS/disk/quota/deadline gates exact
   and connected to the runner rather than test-only helpers?
6. Can the GPU job open the subset before bundle/runtime/tests/CUDA-probe/
   metric gates pass, or silently install/select another environment?
7. Are primary and repeat guaranteed to be fresh processes on the same GPU
   UUID/runtime, with the correct scientific digest comparison?
8. Are checkpoint role, transactional stop/restart behavior, package/archive
   verification and sanitized returns fail-closed?
9. Do the discovery/install/submit/status scripts preserve the two-job design,
   exact-lock policy, four threads, deterministic CUDA variables and email
   notifications without performing login-node computation?
10. Is any issue genuinely blocking a separately reviewed, data-free 004A-3B
    discovery job?

Keep real-data/GPU outcomes out of this review. If a correction is needed,
name the smallest regression that fails on the implementation parent.
