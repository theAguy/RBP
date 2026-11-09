# Task 004A-3 — Newton GPU environment and resource smoke

**Status:** planning only; no Newton job, GPU environment, real-data subset or
training run is authorized by this document.

**Parent:** `docs/tasks/004a_rescnn_reconstruction_and_development_pilot.md`

**Prerequisite:** accepted `manifests/task004a2b_local_smoke.json`

## 1. Purpose

Task 004A-3 answers one engineering question before full training:

> On an identified Newton GPU and a frozen reproducible environment, how much
> time, GPU memory, CPU memory and disk will one epoch of the faithful 500-nt
> ResCNN require?

It is not a performance experiment. It uses development data only, runs one
epoch, selects no loss configuration and never accesses test fields.

## 2. Two remote jobs, no interactive LLM

Only two scripted Newton jobs are planned:

1. **Hardware/environment discovery:** no biological data and no training.
   It records the assigned GPU model, total GPU memory, driver, supported CUDA
   runtime, Slurm limits/modules and installable Python/PyTorch package builds.
2. **GPU resource smoke:** only after discovery review and environment freeze,
   it runs the reviewed development-only subset package once.

Both are submitted through tracked `sbatch` scripts, request one GPU, four
CPUs, explicit RAM/time, no requeue, and email on BEGIN/END/FAIL. The login
node performs no computation. Every job writes a success-or-stopped return ZIP
plus SHA-256 that can be downloaded without an LLM on the cluster.

## 3. Checkpoints

### 004A-3A — local implementation and synthetic validation

Implement, using synthetic fixtures only:

- a development-cache writer/reader using memory-mappable uint8 arrays;
- deterministic coverage-plus-filler selection;
- a one-epoch GPU runner for the accepted model/loss/optimizer/scheduler;
- paired RNG, order, dropped-row, checkpoint and prediction evidence;
- live CPU/GPU memory, disk and timeout supervision;
- atomic generations, immutable selections and sanitized returns;
- Newton discovery, environment-install, submit, status and return scripts;
- portable-bundle inventory and archive verification.

The implementation must not open real inputs or use a GPU. Focused synthetic
tests run twice, followed by independent implementation review.

### 004A-3B — Newton hardware/environment discovery

Run one short, data-free GPU job. It records at minimum:

- Slurm job/allocation request, node, partition/account and scheduler limits;
- GPU model/UUID, total memory and compute capability;
- NVIDIA driver, `nvidia-smi` and exposed CUDA versions;
- OS/architecture, CPU allocation, installed/available RAM and free/quota
  disk evidence;
- available module/Conda channels and exact compatible Python, PyTorch, CUDA,
  NumPy and metric-package builds; and
- a minimal CUDA allocation/kernel/determinism probe.

No version is invented before this return. Discovery failure stops; it does
not trigger an automatic alternative installation.

### 004A-3C — freeze environment and build development-only bundle

After discovery acceptance:

1. Freeze an explicit environment lock and runtime manifest, including every
   resolved file/version needed by the job.
2. Freeze the GPU-model request policy. If Slurm exposes a reliable model
   constraint/GRES name, the smoke must request it and stop on a mismatch. If
   the scheduler cannot guarantee a model, the smoke records its actual model
   as the later 004A-4 reference; any cross-model reproducibility claim then
   requires a separately reviewed numerical tolerance.
3. Pin Adam's GPU-sensitive flags (`foreach`, `fused`, `capturable`,
   `differentiable`, `maximize`). Candidate values must be tested against the
   accepted Adam oracle; no implicit PyTorch default is allowed.
4. Build a local, deterministic subset of exactly **8,193 train and 8,193
   validation rows**. Each partition contains both known classes for every
   protein, then deterministic label-blind filler. `8,193 = 32*256 + 1`, so
   training exercises 32 admitted batches and one recorded dropped row;
   validation retains the singleton tail.
5. Store only the selected train/validation IDs, components, partitions,
   uint8 bases/targets/masks and aggregate evidence. Include no test row or
   original whole-universe CSV/FASTA/membership file.
6. Independently reconcile subset identities, content digests, class
   coverage, shapes and hashes against the accepted 004A-2 contracts.
7. Build and verify one self-contained archive containing frozen source,
   config, environment/runtime evidence, subset, launcher and inventory.

The same cache format and batch loader must be usable unchanged by the later
full-data Task 004A-4 package, so measured throughput is relevant.

### 004A-3D — one reviewed GPU resource-smoke execution

In one allocation on one physical GPU, run seed `20261029` sequentially for
all three configs, then repeat all three once in the same allocation:

- one epoch only;
- enforce the frozen GPU-model request policy before loading the subset;
- batch size 256, train `drop_last=True`, validation `drop_last=False`;
- true float32, no AMP, TF32 or `torch.compile`;
- all accepted deterministic CUDA settings asserted after initialization;
- identical initial state, epoch order, dropped row and model-stochastic
  stream across configs;
- validation on all 8,193 subset rows, 122/122 eligible outputs;
- atomic checkpoint save/reload and finite validation predictions; and
- no full-data or second-seed training in the same job.

## 4. Resource and reproducibility gates

The smoke passes only if:

1. CUDA is genuinely used and the recorded GPU equals the allocated GPU;
2. every config primary/repeat completes without non-finite value or technical
   collapse;
3. paired initial/order/drop hashes match across configs;
4. same-config primary/repeat checkpoint and prediction digests are identical
   on the same GPU/environment;
5. peak GPU reserved memory is at most 80% of physical GPU memory;
6. peak CPU RSS is at most 80% of requested RAM;
7. output growth, free disk and quota remain inside reviewed limits;
8. measured steady-state train/validation batch times support a conservative
   full 30-epoch, three-config, single-seed projection within the reviewed
   Slurm limit, using at least a 1.5x safety factor;
9. every inventory/hash and the development-only/test-absent proof
   independently reconciles; and
10. the return package contains aggregates and hashes only—no sequences,
    row-level predictions or checkpoint payloads.

Failure preserves a sanitized return and stops without retry or parameter
weakening. Scientific underperformance after one epoch is not a failure and
must not be interpreted.

## 5. Explicit non-goals

Task 004A-3 does not:

- train for 30 epochs or use the full train/validation partitions;
- access, score or characterize test rows;
- choose a loss config, epoch, seed, threshold or GPU opportunistically;
- compare against the simple baselines or any competitor;
- run Task 004A-4 automatically; or
- change the accepted architecture, labels, split, loss or batch size.

After 004A-3 acceptance, Task 004A-4 may separately plan the full-data
single-seed, three-config convergence gate using the measured GPU model and
resource budget.
