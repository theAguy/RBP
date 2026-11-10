# Task 004A-3C planning review request

## Requested verdict

Return **Approve**, **Approve with bounded corrections**, or **Stop** for
`docs/tasks/004a3c_environment_and_bundle.md`.

This is a static review. Do not query Newton, install packages, run Slurm or
CUDA, open real inputs, build the cache/bundle, or authorize 004A-3D.

## Required reading

1. `docs/tasks/004a3_newton_gpu_resource_smoke.md`
2. `docs/tasks/004a3a_gpu_resource_smoke_implementation.md`
3. `docs/tasks/004a3c_environment_and_bundle.md`
4. `docs/reviews/004a3a_acceptance.md`
5. `docs/reviews/004a3b_newton_discovery_acceptance.md`
6. `manifests/task004a3b_newton_discovery.json`
7. `manifests/task004a2b_local_smoke.json`
8. `scripts/build_004a3_portable_bundle.py`
9. `src/rbpbench/rescnn/cache_004a3.py`
10. `src/rbpbench/rescnn/environment_004a3.py`
11. all `hpc/newton/004a3` scripts

## Questions

1. Is PyTorch 2.5.1 + CUDA 12.4 + Python 3.11 + NumPy 1.26.4 a defensible,
   compatible frozen request for the accepted L40S/driver evidence?
2. Does the two-install staging/explicit-lock procedure actually prove that
   the final hash-named prefix is recreated only from the frozen lock?
3. Are the runtime-manifest and symlink rules complete without making a real
   Conda environment impossible to represent?
4. Does the CPU-job return preserve enough evidence to review the environment
   without returning the environment itself?
5. Does the cache plan preserve the accepted test-blind Gate A/Gate B boundary
   and provide enough reconciliation for 8,193/8,193 rows?
6. Is `gpu:L40:1` plus exact runtime-name refusal for `NVIDIA L40S` the right
   fail-closed policy given the scheduler/runtime naming mismatch?
7. Are the 3C-1/3C-2/3C-3 boundaries the minimum unavoidable handoffs, and can
   any be safely combined without selecting software or touching data before
   review?
8. Is any correctness, reproducibility, resource, cleanup or evidence issue
   missing before synthetic implementation begins?
