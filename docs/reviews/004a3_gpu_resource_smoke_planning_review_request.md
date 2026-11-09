# Task 004A-3 GPU resource smoke — planning review request

**Requested verdict:** Approve, Approve with bounded corrections, or Stop.
Review planning only. Do not implement, query Newton, build real data, install
an environment, submit Slurm or run a GPU.

## Required reading

1. `docs/tasks/004a_rescnn_reconstruction_and_development_pilot.md`
2. `docs/tasks/004a2_local_data_contract_smoke.md`
3. `docs/reviews/004a2b_execution_acceptance.md`
4. `manifests/task004a2b_local_smoke.json`
5. `docs/tasks/004a3_newton_gpu_resource_smoke.md`
6. `configs/models/task004a_v1.toml`
7. `docs/reviews/004a_rescnn_reconstruction_planning_reconciliation.md`

Do not open ignored artifacts, real inputs, row-level outputs, checkpoints or
raw logs.

## Decisions to review

- two remote jobs only: data-free discovery, then one GPU smoke;
- no invented CUDA/PyTorch versions before discovery;
- local synthetic implementation review before either remote job;
- development-only 8,193/8,193 subset, giving 32 admitted training batches
  plus one dropped row and a retained validation singleton;
- all three configs primary/repeat in one same-GPU allocation;
- explicit same-model Slurm binding when supported, with a reviewed
  cross-model-tolerance requirement otherwise;
- explicit Adam GPU implementation flags and strict float32 determinism;
- 20% GPU/CPU memory headroom and a 1.5x conservative runtime projection;
- portable, inventory-bound, one-shot Slurm execution with sanitized returns;
  and
- no test access, model selection, performance conclusion or automatic 004A-4.

## Questions

1. Is 8,193 rows per partition large enough for stable per-batch throughput
   measurement while remaining a bounded resource smoke?
2. Does coverage-plus-label-blind-filler preserve 122/122 validation
   eligibility without turning the subset into a performance sample?
3. Are the discovery/environment boundaries sufficient to avoid inventing an
   incompatible PyTorch/CUDA lock?
4. Are paired primary/repeat same-GPU gates strong enough for deterministic
   CUDA evidence?
5. Are the memory, disk and conservative runtime gates sufficient before a
   full 30-epoch Task 004A-4 allocation?
6. Should any Adam implementation flag or GPU-model binding rule be frozen
   differently before implementation?
7. Is anything else genuinely blocking before 004A-3A synthetic
   implementation?
