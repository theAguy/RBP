# Task 004A-3A synthetic implementation report

## Status and boundary

The corrected C1–C4/D1–D4 contract is implemented with synthetic fixtures
only. No real CSV, membership, FASTA, ignored 004A artifact or checkpoint was
opened. No Newton query, network call, package installation, CUDA execution or
Slurm submission occurred.

004A-3B discovery, 004A-3C environment/subset freeze and 004A-3D GPU execution
remain separately gated.

## Implemented units

- `cache_004a3.py`: deterministic coverage/filler selection plus an immutable,
  inventory-bound mmap uint8 cache with explicit test absence.
- `adam_004a3.py`: explicit Adam flags and a three-step CPU/CUDA-capable oracle
  comparing parameters, moment buffers and exact step counters.
- `timing_004a3.py`: synchronized inclusive batch timing, four-batch warm-up
  exclusion, median/p95 and distinct-score full-validation metric inputs.
- `projection_004a3.py`: frozen 961/225/30/3 time equation, final inventory
  hashing, 90-checkpoint storage equation and quota/free-space/Slurm gates.
- `runtime_004a3.py`: GPU/runtime identity, live 80% GPU/RSS headroom, disk and
  deadline gates, and discovery install-policy validation.
- `environment_004a3.py`: complete exact-lock/runtime-manifest verification.
- `runner_004a3.py`: data-free CUDA probe, full metric benchmark, one-role
  one-epoch runner, cross-process comparison and final projection command.
- `portable_004a3.py` and the bundle builder: immutable package inventory,
  verified archive, a bundle-derived digest of the exact reviewed source
  subset, scientific-digest comparison and sanitized success/stop returns.
- `hpc/newton/004a3/`: discovery, separate policy-directed installation,
  same-allocation fresh-process smoke, status and return-verification scripts.
- `checkpoint.py`: a distinct authenticated one-epoch GPU resource-smoke
  checkpoint role; the accepted one-update and final-epoch roles are unchanged.

## Correction mapping

- **D1:** three distinct deterministic loss/gradient steps; parameter,
  `exp_avg`, `exp_avg_sq` tolerance and exact step-counter comparison; CPU test
  now, same function called by the future CUDA pre-data probe.
- **D2:** `[57_565,122]` arrays use the accepted validation per-protein known
  counts, both classes and one unique float32 score per known entry.
- **D3:** discovery records channel reachability and the approved install
  location; installation is separate; the GPU job performs verification only.
- **D4:** explicit tests cover GPU/RSS/time/disk/quota failure, GPU UUID and
  runtime digest mismatch, pre-Python CUDA/thread variables, and evidence
  hashing outside batch timing.

The package records validation known counts as aggregate evidence, so the
worst-case metric benchmark runs before the cache is opened. Primary and
repeat are separate Python invocations; repeat cannot launch after primary
failure. Runtime-varying timings are not compared bitwise, while checkpoint,
model, prediction, per-step loss/gradient and paired-start digests are.

## Synthetic verification

Focused command:

```text
pytest -q
  tests/test_rescnn_004a_contract.py
  tests/test_rescnn_004a_fidelity.py
  tests/test_rescnn_004a2_data.py
  tests/test_rescnn_004a2_runtime.py
  tests/test_rescnn_004a3.py
```

Run 1: **83 passed, 20 subtests passed** in 64.32 s.

Run 2: **83 passed, 20 subtests passed** in 67.20 s.

Both runs reported the same two non-failing existing warnings: PyTorch's
TypedStorage deprecation and the fidelity test's intra-op thread-setting
warning. The new 004A-3A file alone has 19 passing tests. All Newton shell
files pass `/bin/bash -n`; Python sources pass compilation; `git diff --check`
is clean.

## Remaining gates

GPU-only branches, the real full-size metric runtime, runtime lock resolution,
the 8,193/8,193 real cache and remote scripts have intentionally not executed.
They require independent 004A-3A acceptance followed by separate 004A-3B/3C/3D
handoffs. No automatic next stage is authorized.
