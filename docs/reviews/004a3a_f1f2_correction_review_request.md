# Task 004A-3A F1–F2 correction — independent review request

**Requested verdict:** Approve, Approve with bounded corrections, or Stop.

Review only the bounded synthetic F1–F2 correction after `e658161`. Inspect
the complete `e658161..HEAD` diff. Do not open/hash real or ignored inputs,
query Newton, install anything, use CUDA, construct the real subset, submit
Slurm or authorize a later checkpoint.

## Required reading

1. `docs/tasks/004a3_newton_gpu_resource_smoke.md`
2. `docs/tasks/004a3a_gpu_resource_smoke_implementation.md`
3. `docs/reviews/004a3a_implementation_report.md`
4. `src/rbpbench/discovery_004a3.py`
5. `src/rbpbench/rescnn/__init__.py`
6. `src/rbpbench/rescnn/runtime_004a3.py`
7. `src/rbpbench/rescnn/runner_004a3.py`
8. `scripts/build_004a3_portable_bundle.py`
9. `hpc/newton/004a3/01_DISCOVERY.sbatch`
10. `hpc/newton/004a3/RUN_004A3_SMOKE.sbatch`
11. `tests/test_rescnn_004a3.py`

## Questions

1. Can `rbpbench.discovery_004a3` import and validate while `torch` is absent
   or explicitly blocked, without entering `rbpbench.rescnn`?
2. Does the discovery job always write `DISCOVERY.json`, the return ZIP and
   its checksum before validation can fail?
3. Are all discovery Python subprocess calls compatible with Python 3.6, and
   can missing, `UNLIMITED`, `INFINITE` or malformed `MaxTime` be preserved as
   evidence rather than aborting evidence creation?
4. Does the validator still fail closed on a null, zero, negative or otherwise
   unusable partition time limit?
5. Is the new standard-library module copied into and hash-bound by the
   portable bundle while the existing runtime and builder imports remain
   compatible?
6. Does GPU UUID normalization accept only whitespace/case/leading `GPU-`
   representation differences, record one canonical value, and reject empty,
   malformed or genuinely different UUIDs?
7. Did F1–F2 change any frozen scientific constant or cross the synthetic-only
   boundary?
8. Is any defect genuinely blocking a separately authorized, data-free
   004A-3B discovery job?

Assess the four reported parent-failing regressions against `e658161`; do not
accept only their names. Do not start or authorize 004A-3B.
