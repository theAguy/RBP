# Task 004A planning-review reconciliation

**Verdict:** accepted after bounded corrections. Implementation may begin at
004A-1 only; real-data and GPU checkpoints remain separately gated.

## Review evidence

The independent reviewer read the eight requested tracked sources, verified
the notebook hash, inspected all notebook source cells without executing them,
and did not open the real CSV, FASTAs, membership, predictions or former
checkpoint.

Independent calculations agreed with the plan:

- 9,029,562 learnable parameters at 500 nt;
- 4,966,330 and 2,475,962 for the materially changed 251/101 variants;
- submitted near-zero-logit known-to-unknown loss ratio approximately 8.52;
- training remainder `246,017 mod 256 = 1`; and
- validation remainder `57,565 mod 256 = 221`.

The verdict was `Approve with bounded corrections`.

## Applied corrections

### C1 — singleton training batch

The accepted training count would send a final `[1, 512]` tensor through
dense `BatchNorm1d` and fail. Training now freezes `drop_last=True`; validation
retains `drop_last=False`. The one seed-determined omitted row is disclosed,
hashed per epoch and identical across paired configs. Synthetic and bounded
real-data smoke tests must exercise an `N mod 256 = 1` tail.

### C2 — true float32 and strict GPU determinism

TF32 is explicitly disabled for cuDNN and CUDA matmul. Highest float32 matmul
precision, strict deterministic algorithms, deterministic cuDNN, disabled
benchmarking and pre-CUDA `CUBLAS_WORKSPACE_CONFIG=:4096:8` are asserted and
logged. A warning-only downgrade is forbidden.

### C3 — paired loss ablations

Within each seed all three configs now share byte-identical initialization,
every epoch's sample order, the omitted tail row and dropout random stream.
Initialization, loader and model-stochastic streams are separately labelled
and recorded. Loss configuration cannot enter seed derivation. Initial-state,
order and dropped-row hashes are acceptance gates.

### C4 — direct notebook oracle

The model and loss oracle are extracted programmatically from hash-checked
notebook cells 8 and 11 rather than retyped. Their exact cell-source hashes are
frozen. The submitted hyperparameters are independently bound to cell 22.
Same-seed default initialization, state tensors, logits and gradients are
compared; weight copying alone is not considered sufficient.

### C5 — GPU-model and environment binding

The resource smoke records the GPU model. Each seed's paired configs run in
one allocation on one GPU. Later jobs request the same model when supported;
otherwise exact reproducibility is claimed only within a GPU model and an
accepted cross-model numerical tolerance is required. All nine accepted runs
must share one source, config and environment hash.

## Additional required clarifications incorporated

- Every epoch requires 122/122 validation outputs eligible for the scheduler.
- The notebook's flattened AP, if retained, is labelled pooled known-entry AP,
  not macro AP.
- Mid-run resume is forbidden; an interrupted candidate restarts from epoch 0.
- Any source change after seed 1 invalidates and repeats seed 1.
- Collapse diagnostics now include score standard deviation, unique count,
  modal-score fraction and saturation fraction.
- Every train/validation FASTA sequence is compared with its CSV bit encoding
  during cache construction; test fields remain uninterpreted.
- `docs/IMPLEMENTATION_PLAN.md` and `docs/PROJECT_ROADMAP.md` now distinguish
  Task 004A's faithful final-epoch behavior from later competitor and common
  early-stopping work.

## Accepted boundary

Task 004A remains 500 nt only, trains all 122 outputs and evaluates engineering
decisions on the eight frozen development proteins. The three loss configs,
three seeds, final epoch, test blindness and staged local/Newton execution are
accepted. Competitors, 251/101 adaptation, test scoring, calibration and final
operating-point comparisons remain deferred.
