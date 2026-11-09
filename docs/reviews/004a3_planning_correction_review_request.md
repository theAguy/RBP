# Task 004A-3 bounded planning-correction review request

**Requested verdict:** Approve, Approve with bounded corrections, or Stop.

Review the C1–C4 planning corrections only. Do not implement 004A-3A, open
real/ignored inputs, query Newton, install an environment, build a real subset,
run PyTorch/CUDA or authorize either remote job.

## Required reading

1. `docs/tasks/004a3_newton_gpu_resource_smoke.md`
2. `docs/reviews/004a3_gpu_resource_smoke_planning_review_request.md`
3. `docs/reviews/004a3_gpu_resource_smoke_planning_reconciliation.md`
4. `docs/tasks/004a3a_gpu_resource_smoke_implementation.md`
5. `docs/tasks/004a_rescnn_reconstruction_and_development_pilot.md`
6. `src/rbpbench/rescnn/factories_004a2.py`
7. `src/rbpbench/rescnn/metrics.py`
8. `src/rbpbench/baselines/metrics.py`

## Corrections to confirm

### C1 — measurement/projection

Confirm that four excluded warm-up batches, synchronized inclusive batch
timing, maximum p95 across six process/config runs, full-shape synthetic metric
timing, measured scheduler/checkpoint/startup costs and the fixed
961/225/30/3 equation prevent the identified runtime underestimate.

Confirm that 90 measured checkpoints, non-checkpoint epoch growth,
atomic-write temporary space, environment/bundle and return bytes, a 1.5
factor and both quota/free-space gates prevent the identified storage
underestimate.

### C2 — environment and pre-data tests

Confirm that the hash-named environment prefix, exact lock/runtime-manifest
verification, accepted 004A-1/004A-2 focused suites and twice-repeated
synthetic CUDA real-model/loss/Adam probe all run before the subset can open,
and that failures stop rather than select another environment.

### C3 — separate-process repeat

Confirm that one allocation launching primary and repeat as separate runner
processes creates fresh CUDA context/allocator/cuBLAS state while preserving
the same physical GPU, and that the required cross-process digest set is
complete.

### C4 — Adam flags and oracle

Confirm the frozen values `foreach=True`, `fused=False`,
`capturable=False`, `differentiable=False`, `maximize=False`. Specifically
review the newly frozen float32 comparison tolerance (`rtol=1e-6`,
`atol=1e-7`) against a `foreach=False` single-tensor reference, with bitwise
pre-update loss/gradient equality. If this tolerance is not defensible, name
the exact replacement now, before implementation.

## Boundary questions

1. Do the corrected task and prepared 004A-3A implementation contract fully
   resolve C1–C4 without introducing a new scientific choice?
2. Are any implementation regressions missing from sections 4.1–4.10 of the
   004A-3A task?
3. Is anything genuinely blocking synthetic-only 004A-3A implementation?

Do not request refinements that belong only to discovery, real subset
construction, GPU execution or full training unless the 004A-3A design would
make them impossible to enforce later.
