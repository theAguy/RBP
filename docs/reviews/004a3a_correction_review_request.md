# Task 004A-3A E1–E6 correction — independent review request

**Requested verdict:** Approve, Approve with bounded corrections, or Stop.

Review only the bounded synthetic correction after commit `d13179a`. Do not
open or hash real/ignored inputs, query Newton, install anything, run CUDA,
construct the real subset, submit Slurm or authorize a later checkpoint.

## Required reading

1. `docs/tasks/004a3_newton_gpu_resource_smoke.md`
2. `docs/tasks/004a3a_gpu_resource_smoke_implementation.md`
3. `docs/reviews/004a3_gpu_resource_smoke_planning_reconciliation.md`
4. `docs/reviews/004a3a_implementation_report.md`
5. `src/rbpbench/rescnn/cache_004a3.py`
6. `src/rbpbench/rescnn/runtime_004a3.py`
7. `src/rbpbench/rescnn/projection_004a3.py`
8. `src/rbpbench/rescnn/runner_004a3.py`
9. `scripts/build_004a3_portable_bundle.py`
10. every file under `hpc/newton/004a3/`
11. `tests/test_rescnn_004a3.py`

Inspect the complete correction diff against `d13179a` and the parent-failure
evidence recorded in the executor return.

## Questions

1. Does E1 capture and validate every raw scheduler, OS/runtime, environment
   availability and quota field needed to freeze 3C without installing?
2. Does E2 authenticate the accepted 004A-2 summary, derive all 122 full
   validation known counts and reject subset-derived counts? Does the new
   production builder preserve the accepted two-pass test-blind boundary?
3. Do E3's reviewed scheduler request and process-level GPU name/UUID checks
   happen before the first cache access in both probe and run paths?
4. Does the portable bundle contain every tracked ROOT-relative dependency of
   the five focused suites, with inventory binding?
5. Do E5's role directories make primary/repeat checkpoint basenames—and
   therefore deterministic archive roots—identical while projection still
   finds exactly six checkpoints?
6. Does E6 use only a positive discovery-derived reviewed 004A-4 Slurm limit,
   never the four-hour smoke allocation limit or a caller override?
7. Did any correction change a frozen scientific constant or cross the
   synthetic-only boundary?
8. Is any defect genuinely blocking a separately authorized, data-free
   004A-3B discovery job?

If proposing another correction, identify the smallest regression that fails
on the correction commit. Do not start or authorize 004A-3B.
