# Task 004A-3A — GPU resource-smoke implementation and synthetic validation

**Status:** prepared for implementation; no implementation, real-input read,
Newton query, environment installation, GPU use or remote submission is
authorized by this document alone.

**Parent:** `docs/tasks/004a3_newton_gpu_resource_smoke.md`

**Corrected planning record (independent confirmation pending):**
`docs/reviews/004a3_gpu_resource_smoke_planning_reconciliation.md`

## 1. Objective

Build and validate, with synthetic fixtures only, the software that will later
perform one data-free Newton discovery job and one reviewed development-only
GPU resource smoke. 004A-3A must make the future jobs mechanical: no loss,
optimizer, timing, projection, storage, GPU or retry policy may be chosen on
the cluster.

## 2. Hard boundary

004A-3A may read tracked source, configuration, manifests and synthetic test
fixtures. It must not:

- open/hash the real CSV, accepted membership/FASTA, ignored 004A artifacts or
  any checkpoint;
- query Newton, inspect a remote scheduler, install a GPU environment or run
  CUDA/MMseqs2;
- construct the real 8,193/8,193 subset;
- submit either remote job; or
- start 004A-3B, 3C, 3D or 004A-4.

## 3. Implementation units

The implementation should keep data, runtime, projection and packaging
contracts separable and testable. Exact filenames may be adjusted during
implementation only when the review request maps the replacement one-to-one.
The intended units are:

- `cache_004a3.py`: mmap-compatible uint8 cache schema, bounded deterministic
  coverage-plus-filler sampler and test-blind counters;
- `adam_004a3.py`: frozen GPU Adam construction/effective-field assertion and
  the single-tensor oracle;
- `timing_004a3.py`: synchronized batch timing, four-batch warm-up exclusion,
  quantiles and full-size synthetic metric benchmark;
- `projection_004a3.py`: fixed 961/225/30/3 wall-time equation and measured
  90-checkpoint storage equation;
- `runtime_004a3.py`: strict CUDA/GPU identity, memory/RSS/disk/quota/deadline
  supervision and sanitized stop evidence;
- `runner_004a3.py`: exactly one primary or repeat invocation, never both;
- `portable_004a3.py`: immutable inventory, runtime lock/manifest binding,
  safe return sanitation and archive verification; and
- tracked Newton scripts for discovery, exact-lock install/verification,
  pre-data tests, two-process smoke launch, status and return verification.

No module may accept caller overrides for the frozen scientific or projection
constants.

## 4. Synthetic acceptance tests

Focused tests must prove at least:

1. **Cache and blindness:** exact shapes/dtypes, mmap reopening, deterministic
   coverage/filler selection, label-blind filler, no test-row field supplier,
   and independent content/count reconciliation.
2. **Optimizer:** all five GPU flags and all existing Adam fields are asserted;
   unknown/changed fields fail; `foreach=True` and `foreach=False` start from
   identical state/loss/gradients and finish within `rtol=1e-6`, `atol=1e-7`.
3. **Timing:** injected synchronizers bracket every timed region; exactly four
   warm-up train and validation batches per run are excluded; loader, copy,
   one-hot and model work fall inside the interval; median/p95 use retained
   samples only.
4. **Metrics:** the projection invokes the accepted real metric function on a
   synthetic `[57_565, 122]` shape and exact supplied known-entry count; a
   shortcut based on subset scaling fails.
5. **Wall time:** the equation uses 961 train batches, 225 validation batches,
   30 epochs, three configs, startup and the 1.5 factor exactly; removal or
   replacement of any term fails.
6. **Storage:** 90 measured checkpoint sizes, non-checkpoint epoch growth,
   largest atomic temporary, environment/bundle and return bytes are included;
   absent quota, insufficient free space or insufficient quota fails closed.
7. **Fresh processes:** the allocation launcher invokes primary and repeat as
   two Python processes, pins both to the same visible GPU and compares every
   required digest. A same-process shortcut and a repeat after failed primary
   are refused.
8. **Pre-data gate:** environment verification, both accepted focused suites,
   twice-repeated synthetic CUDA probe and GPU model/UUID binding precede the
   first possible subset open. Failure produces STOPPED evidence and zero data
   opens.
9. **Transactions/restart:** candidate failure preserves prior accepted
   evidence, selection-record failure discards the candidate, pre-existing
   STOPPED/selection evidence prevents silent retry and archives are verified
   after creation.
10. **Return sanitation:** no sequence, row ID, prediction row, checkpoint or
    environment secret enters the portable return; aggregates, hashes and
    bounded error text remain.

Tests must use injected fake commands/devices/resources where required. They
must not weaken production checks merely to run without CUDA.

## 5. Verification and review checkpoint

Run the complete focused 004A-1/004A-2/004A-3A synthetic suite twice in the
accepted local CPU environment. Record test counts, skipped tests, runtime and
the absence of real-input access. Also run `git diff --check` and audit every
committed path for generated/large/row-level content.

Then create a separate implementation-review request for Claude listing the
complete diff and tests. Required verdict: `Approve`, `Approve with bounded
corrections`, or `Stop`. 004A-3B discovery remains forbidden until 004A-3A is
independently accepted and a new execution handoff explicitly authorizes it.

## 6. Required implementation return

Return:

1. commit and changed-file list;
2. module/script map and frozen constants;
3. regression-to-contract mapping for sections 4.1–4.10;
4. two focused-suite results and any non-failing warnings/skips;
5. proof no real input, GPU, Newton or network action occurred;
6. `git diff --check`, staged-file audit and clean status; and
7. remaining gaps before 004A-3B.
