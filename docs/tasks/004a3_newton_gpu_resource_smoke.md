# Task 004A-3 — Newton GPU environment and resource smoke

**Status:** 004A-3A and the single data-free 004A-3B discovery are accepted and
closed, including the UNLIMITED-partition correction. Task 004A-3C environment
and bundle preparation is planned in `004a3c_environment_and_bundle.md` and
awaits independent planning review. No environment install, real-data subset,
CUDA smoke or training run is authorized by this document.

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
- synchronized warm-up-excluded timing and full-run time/storage projection;
- atomic generations, immutable selections and sanitized returns;
- Newton discovery, environment-install, submit, status and return scripts;
- portable-bundle inventory and archive verification.

The implementation must not open real inputs or use a GPU. Focused synthetic
tests run twice, followed by independent implementation review. The precise
implementation boundary and required regressions are frozen in
`docs/tasks/004a3a_gpu_resource_smoke_implementation.md`.

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

The accepted return is recorded in
`manifests/task004a3b_newton_discovery.json`. Newton's `public` partition
reported `MaxTime=UNLIMITED` and `PreemptMode=REQUEUE`. The raw scheduler value
remains unchanged in the evidence. Because an unbounded scheduler setting is
not an experiment limit, this project uses a separate finite 12-hour
(43,200-second) ceiling for the later single-seed 004A-4 projection and job.
If a future finite partition limit is smaller, the bundle must stop rather
than exceed it.

### 004A-3C — freeze environment and build development-only bundle

After discovery acceptance:

1. Freeze an explicit environment lock and runtime manifest, including every
   resolved file/version needed by the job.
2. Freeze the GPU-model request policy. If Slurm exposes a reliable model
   constraint/GRES name, the smoke must request it and stop on a mismatch. If
   the scheduler cannot guarantee a model, the smoke records its actual model
   as the later 004A-4 reference; any cross-model reproducibility claim then
   requires a separately reviewed numerical tolerance.
3. Pin Adam's GPU-sensitive flags now, rather than selecting them after GPU
   evidence exists: `foreach=True`, `fused=False`, `capturable=False`,
   `differentiable=False`, and `maximize=False`. The implementation must
   assert these effective values together with the already-frozen learning
   rate, betas, epsilon, weight decay and AMSGrad values. A synthetic one-step
   oracle compares this optimizer with the `foreach=False` single-tensor
   reference for three consecutive steps with distinct deterministic
   gradients. Parameters, `exp_avg` and `exp_avg_sq` use float32 `rtol=1e-6`
   and `atol=1e-7`; step counters are exactly equal, while each step's
   pre-update loss and gradients are bitwise identical. The oracle runs on CPU
   in 3A and CUDA in the pre-data probe. No implicit PyTorch default or fused
   implementation is allowed.
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

The discovery return determines the exact lock and records whether compute
nodes can reach every required package channel. A separate tracked install
script installs that exact lock, according to the recorded site policy, on the
login node or in a CPU-only job at
`$HOME/.conda/envs/rbpbench-004a3-<lock_sha256_prefix>`. The GPU smoke job
never installs packages; it only verifies the frozen lock and complete runtime
manifest. A pre-existing prefix is reusable only when both match; otherwise
the job stops. Before the subset path is opened, the GPU job must:

1. run the accepted 004A-1/004A-2 focused suites in that environment;
2. run the real CNN, each accepted loss and one Adam step at batch size 256 on
   synthetic data under every strict CUDA setting twice; and
3. require bitwise-identical repeat evidence, the frozen Adam oracle tolerance
   and the requested-versus-actual GPU model/UUID checks.

Any failure writes a sanitized stop return. It must not open the subset or
continue to a different environment. This pre-data stage closes the deferred
Newton-suite requirement from 004A-1.

The same cache format and batch loader must be usable unchanged by the later
full-data Task 004A-4 package, so measured throughput is relevant.

### 004A-3D — one reviewed GPU resource-smoke execution

In one allocation on one physical GPU, run seed `20261029` sequentially for
all three configs. The allocation script launches a **primary process** and,
only after it succeeds, a separate **repeat process** for all three configs.
Each process therefore receives a fresh CUDA context, allocator and cuBLAS
state while remaining bound to the same allocated GPU:

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

The launcher compares same-config checkpoint, prediction, per-step loss and
gradient digests across the two processes. It never imports the runner once
and calls it twice in one Python process.

The accepted public partition is preemptible. This bounded smoke keeps
`--no-requeue`: interruption produces sanitized STOPPED evidence and never
silently resumes or repeats. The later 30-epoch Task 004A-4 must implement and
independently review epoch-checkpoint restart safety before it can run on this
partition.

### 004A-3D.1 — frozen measurement method

Every train and validation batch timing must include loader access,
host-to-device transfer, one-hot conversion and model work. Call
`torch.cuda.synchronize()` immediately before starting and after ending each
timed region. Exclude the first four train batches and first four validation
batches from each process/config as warm-up. Retain median and p95 timing for
each run and use the largest p95 across the six process/config runs for
projection.

Do not extrapolate the subset metric time linearly. Before the subset is
opened, benchmark the accepted metric implementation on deterministic
synthetic arrays with the full validation shape `[57_565, 122]` and the exact
accepted per-protein validation known counts recorded by the reviewed cache
builder. Every known entry receives a distinct float32 score, and every
protein contains both classes. Record median and p95 across repeated metric
calls after warm-up. Also measure and record the scheduler step, atomic
checkpoint write/reload, process startup and hash/inventory overhead.

The conservative single-seed 004A-4 wall-time projection is:

```text
startup
+ 3 configs * 30 epochs * (
    961 * maximum_train_batch_p95
  + 225 * maximum_validation_batch_p95
  + full_validation_metrics_p95
  + scheduler_p95
  + checkpoint_p95
  )
+ final_inventory_hashing
```

The complete sum is multiplied by `1.5`. The constants are fixed by the
accepted split and loaders: `floor(246_017 / 256) = 961` admitted train
batches and `ceil(57_565 / 256) = 225` validation batches.

The storage projection includes the verified environment and bundle when they
share the quota, all 90 retained epoch checkpoints, 90 epochs of measured
non-checkpoint output growth, the largest observed atomic-write temporary and
return-package overhead. It uses measured checkpoint bytes rather than an
estimate (the expected order is about 108 MB each, or about 9.7 GB for 90),
and includes the measured time required to hash that projected final
inventory. Startup is counted once per runner process in the reviewed 004A-4
topology. The same `1.5` safety factor applies. Storage must fit both free
space and the machine-readable user quota returned by discovery; missing quota
evidence is a stop, not permission to rely on filesystem-wide free space.

## 4. Resource and reproducibility gates

The smoke passes only if:

1. CUDA is genuinely used and the recorded GPU equals the allocated GPU;
2. every config primary/repeat completes without non-finite value or technical
   collapse;
3. paired initial/order/drop hashes match across configs;
4. same-config primary/repeat checkpoint, prediction, per-step loss and
   gradient digests are identical across separate processes on the same
   GPU/environment;
5. peak GPU reserved memory is at most 80% of physical GPU memory;
6. peak CPU RSS is at most 80% of requested RAM;
7. output growth, free disk and quota remain inside reviewed limits;
8. the synchronized, warm-up-excluded measurement and full-size synthetic
   metric benchmark support the frozen 30-epoch, three-config, single-seed
   projection within the reviewed Slurm limit after the 1.5x factor, and the
   measured 90-checkpoint storage projection fits both quota and free space;
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
