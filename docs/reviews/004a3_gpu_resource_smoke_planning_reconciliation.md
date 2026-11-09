# Task 004A-3 planning-review reconciliation

**Verdict:** `Approve with bounded corrections`; C1–C4 are applied here and
await independent correction confirmation. The 004A-3A synthetic-only task is
prepared but must not begin before that confirmation and separate
authorization. Newton discovery, environment installation, real-data subset
construction and GPU execution remain separately gated.

## Review boundary

The independent reviewer read only the seven tracked planning sources. No
ignored artifact, row-level input, Newton query, package installation or
PyTorch execution occurred. The verdict was `Approve with bounded
corrections`.

## Applied corrections

### C1 — frozen time and storage projection

The plan now requires synchronized CUDA timing, excludes four warm-up train
and validation batches per process/config and records per-run median and p95
times for the real loader, transfer, one-hot and model path. Projection uses
the largest p95, not an average.

The full validation metric path is timed independently on deterministic
synthetic arrays of shape `[57_565, 122]` with the exact accepted validation
known-entry count. Scheduler, checkpoint, startup and evidence overhead are
measured separately. The fixed projection uses 961 train and 225 validation
batches, 30 epochs and three configs, then applies a 1.5 safety factor.

Storage projection includes 90 measured checkpoint payloads, measured
per-epoch output growth, atomic-write temporary space, environment/bundle
bytes where applicable and the return package. It also receives a 1.5 factor
and must fit both machine-readable quota and free space.

### C2 — named environment installation and pre-data node tests

The discovery return freezes the lock. The smoke job installs or verifies it
under `$HOME/.conda/envs/rbpbench-004a3-<lock_sha256_prefix>`. Reuse requires
complete lock/runtime-manifest equality.

Before opening the development subset, the GPU job runs the accepted 004A-1
and 004A-2 focused suites and a twice-repeated synthetic real-CNN/loss/Adam
CUDA probe at batch 256. Any suite, determinism, binary, model/UUID or strict
setting failure produces a sanitized stop and cannot fall through to data
access. This also closes 004A-1's deferred Newton test requirement.

### C3 — fresh-process repeat

Primary and repeat are separate runner invocations inside one allocation on
one GPU. Their fresh CUDA contexts prevent shared allocator/cuBLAS state from
hiding process-level nondeterminism. The launcher compares checkpoint,
prediction, per-step loss and gradient digests.

### C4 — frozen Adam GPU implementation

The accepted GPU Adam flags are `foreach=True`, `fused=False`,
`capturable=False`, `differentiable=False`, `maximize=False`. The one-step
float32 oracle compares against the `foreach=False` single-tensor reference
with `rtol=1e-6` and `atol=1e-7`; pre-update loss and gradients remain bitwise
identical. Effective optimizer fields are asserted, so PyTorch defaults cannot
change the implementation silently.

## Accepted boundary

The 8,193/8,193 development-only subset, coverage-plus-label-blind filler,
same-GPU pairing, GPU-model binding and 20% CPU/GPU memory headroom are
accepted. One-epoch scores remain engineering-only. No test access, model
selection, full training or automatic 004A-4 execution is permitted.
