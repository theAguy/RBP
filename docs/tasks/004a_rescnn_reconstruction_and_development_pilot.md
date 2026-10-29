# Task 004A — Former ResCNN reconstruction and development pilot

**Status:** proposed; implementation is forbidden until independent planning
review is accepted.

**Phase:** 4, first neural-model task

**Execution hosts:** local project Mac for implementation, synthetic tests and
small CPU smoke tests; Newton GPU for the bounded real-data resource smoke and
development pilot. Darwin is not a training host for this task.

## 1. Objective

Reconstruct the former teammate's joint 122-output ResCNN from
`intRBP ResCNN - for students.ipynb`, prove that the reconstruction is faithful,
and run a validation-only development pilot that separates two unusual parts
of the submitted loss:

1. a 15-fold multiplier on known-positive BCE terms; and
2. a penalty that explicitly pushes every unknown protein/sequence pair toward
   a negative prediction.

The pilot answers engineering and fidelity questions, not the final scientific
comparison:

- Can the original 500-nt model and loss be reproduced exactly?
- Does each loss configuration train stably under the accepted split?
- What GPU time and memory will the controlled comparison require?
- How variable are validation results across three fixed random seeds?

Task 004A never evaluates the held-out test partition, never runs a published
competitor and never declares a winning method or input width.

## 2. Why this task is necessary

The notebook is valuable source evidence, but it is not yet a reproducible or
leakage-safe experiment:

- it creates a new row-level multilabel fold instead of using the accepted
  components-v2 split;
- its stratification matrix, `targets * masks`, contains positives but not
  known negatives;
- it saves the final model after the first of five nominal folds rather than a
  versioned, restart-safe training artifact;
- package versions, random-state handling and generated predictions are not
  fully bound;
- its loss treats absent labels as negatives through a separate term; and
- it is hard-coded to 500 nt.

Task 004A preserves the model and submitted loss while replacing only the
experimental scaffolding: split, provenance, deterministic execution,
checkpoint integrity and reporting.

## 3. Immutable evidence and inputs

Every real-data invocation must re-hash and validate these tracked contracts
before parsing labels or sequences:

| Input | SHA-256 |
|---|---|
| `dataset_K562_multilabel_with_NEGs.csv` | `982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945` |
| `manifests/dataset_audit.json` | `e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c` |
| `configs/proteins.tsv` | `374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9` |
| `manifests/sequence_decode_002b2.json` | `d9826b471ef3f12539eaf51be5c21ba8be20190f3d7c6042143e839d6bb0a7b3` |
| `manifests/sequence_partitions_002c_v2.json` | `b6f6f16fab4e6afc23c16a8dc5b3476130719d579f637cd3cf18002cc7fb7419` |
| accepted membership | `ca527da4f0c0615bcb9d31c6fc705523238e8fb8f4751473ccc2af3ee0aecddb` |
| accepted 500-nt FASTA | `0849d4f8aceaed37c3dc7fec69056f38ae344338aa4adf321a3e11c4a72df0b0` |
| original notebook | `9a04f551ed9e5420c720074bf57f41f1c93ab92acc37c3b8ff44868e6b021b84` |
| former checkpoint, forensic evidence only | `9c036fceab966442d3cea40146a757114d8b23711c41cba227c3dafd24ff27c3` |

The accepted universe contains 361,180 rows and 169,699 components, assigned
as 246,017 train, 57,565 validation and 57,598 test rows. The former fold and
every rejected intermediate split are forbidden inputs.

The former checkpoint must never initialize or score the new experiment: it
was trained under the former split. During 004A-1 it may be opened once on CPU
with PyTorch's restricted `weights_only=True` loader solely to reconcile
state-dictionary keys and tensor shapes. Unsafe pickle fallback is forbidden.
Its contents cannot alter the architecture transcribed from source, and no
metric from it is accepted as evidence.

The Task 003B closure manifest and accepted prediction contract are also
prerequisites. Task 004A must use the same canonical IDs, partitions, protein
IDs and score semantics so its later results can be compared directly with
the accepted prevalence, GC, 3-mer and 6-mer baselines.

## 4. Hard test-blindness boundary

Task 004A may use only **train** for gradient updates and **validation** for
learning-rate scheduling, development metrics and engineering decisions.

The implementation may hash whole accepted files and may stream past records
because the inputs are sequential. For a row assigned to test, however, it
must not:

- parse or count its protein labels;
- decode, one-hot encode, cache or retain its sequence;
- construct a tensor or prediction;
- report a class count or metric; or
- use it in any assertion except canonical-ID/partition membership integrity.

The cache builder must decide the partition from accepted membership before it
parses a row's labels or retains its sequence. Selection records must state
`test_accessed: false`. Any test access is a hard failure, not a warning.

## 5. Exact label and input contract

For protein ID `k` in 1 through 122:

- unsigned `k` and explicit `+k` are known positive: target 1, mask 1;
- `-k` is known negative: target 0, mask 1; and
- absent `k` is unknown: target 0, mask 0.

Protein ID `k` maps to output column `k - 1`. The complete mapping must agree
with `configs/proteins.tsv` and the notebook mapping.

The input is the accepted 500-nt sequence in its supplied orientation, encoded
as a float32 matrix of shape `[500, 4]` in A/C/G/T order. One-hot conversion is
performed per batch from a compact retained representation; Task 004A must not
materialize a multi-gigabyte float32 copy of the whole dataset. A frozen set of
train/validation IDs must independently round-trip between FASTA bases and the
notebook's 2,000-bit representation before real training is authorized.

## 6. Exact submitted architecture

The reconstruction must match the notebook's 500-nt network:

1. input `[batch, 500, 4]`, permuted to `[batch, 4, 500]`;
2. residual block 4 to 64 channels, kernel 7, same padding, max-pool 2;
3. residual block 64 to 128 channels, kernel 7, same padding, max-pool 2;
4. residual block 128 to 256 channels, kernel 5, same padding, max-pool 2;
5. flatten `[batch, 256, 62]` to 15,872 values;
6. linear 15,872 to 512, batch norm, ReLU, dropout 0.4;
7. linear 512 to 256, batch norm, ReLU, dropout 0.3; and
8. linear 256 to 122 logits.

Each residual block has two convolution/batch-normalization layers. Its skip
path uses a 1x1 convolution when channel counts differ, addition precedes the
final ReLU, and pooling follows the residual activation.

Convolutions and linear layers retain PyTorch biases. Convolution stride and
dilation are 1; padding is `kernel_size // 2`. Batch normalization uses the
PyTorch defaults `eps=1e-5`, `momentum=0.1`, affine parameters and tracked
running statistics. ReLU is not in-place. Max-pool uses kernel and stride 2
with no padding and floor output sizing. These defaults must be explicit in
the frozen config rather than left to a future package version.

The exact learnable-parameter count is **9,029,562**. Synthetic acceptance
must compare the clean implementation with an independently transcribed
notebook oracle after copying identical weights. Logits and gradients must
agree within a frozen float32 tolerance in both training and evaluation mode,
with identical RNG state when dropout is active;
state-dictionary tensor shapes, dropout rates, batch-normalization settings
and parameter count must also agree.

### 6.1 Width boundary

Task 004A is **500 nt only**. The notebook's `Linear(256 * 62, 512)` is
literally defined only for 500 nt. Replacing 500 by 251 or 101 changes the
post-pooling lengths to 31 or 12 and changes the total parameter count to
4,966,330 or 2,475,962. Padding shorter windows, adaptive pooling and changing
the first dense layer are different scientific models.

The 251/101 comparison remains required, but its architecture rule must be
planned after the faithful 500-nt reconstruction is accepted. No 150-nt input
will be introduced.

## 7. Exact submitted loss and ablations

For logits `z`, targets `y` and known-label mask `m`, the notebook computes
elementwise binary cross entropy `BCE(z, y)` and:

```text
positive_multiplier = 15 for y=1, otherwise 1

known_weighted = sum(positive_multiplier * BCE(z,y) * m) / sum(m)
unknown_negative = sum(BCE(z,0) * (1-m)) / sum(1-m)
total = known_weighted + lambda_unknown * unknown_negative
```

This is a per-batch ratio, exactly as in the notebook. The positive multiplier
does not normalize back by the sum of weights. The unknown term is separately
mean-normalized, so the large number of unknown entries does not multiply its
magnitude directly. At near-zero logits, the observed known-label class mix
makes the submitted known term approximately 8.5 times the unknown term before
their coefficients are combined.

Three joint configurations are frozen for the pilot:

| Config ID | Positive multiplier | Unknown-negative coefficient | Purpose |
|---|---:|---:|---|
| `submitted` | 15 | 1 | reproduce the former recipe |
| `submitted_no_unknown` | 15 | 0 | isolate removal of the unknown penalty |
| `joint_standard` | 1 | 0 | isolate positive weighting relative to the preceding config |

Thus `submitted` versus `submitted_no_unknown` changes only the unknown term,
and `submitted_no_unknown` versus `joint_standard` changes only the positive
multiplier. All three still train one joint model with all 122 outputs.

Unit tests must cover hand-calculated logits, positive, known-negative and
unknown entries; coefficient zero; batch-size variation; finite gradients;
zero-denominator refusal; and equality with the notebook formula.

## 8. Frozen training behavior

The fidelity pilot retains the notebook's optimization behavior:

- float32 training; no automatic mixed precision and no `torch.compile`;
- batch size 256, `drop_last=False`;
- Adam with learning rate `1e-3`, betas `(0.9, 0.999)`, epsilon `1e-8`, no
  weight decay and no AMSGrad;
- at most 30 epochs, with all 30 run unless numerical/resource failure occurs;
- `ReduceLROnPlateau`, mode `max`, factor 0.5, patience 2, relative threshold
  `1e-4`, cooldown 0, minimum LR 0 and epsilon `1e-8`;
- scheduler statistic: unweighted macro validation AUROC over every eligible
  one of the 122 outputs, matching the notebook; and
- validation loader unshuffled; training loader shuffled by a recorded seeded
  generator with deterministically seeded workers.

The notebook does **not** implement early stopping or best-checkpoint
restoration. Task 004A must not silently add either. The primary fidelity
artifact is the epoch-30 checkpoint. Every epoch checkpoint may be retained
temporarily for diagnostics, but choosing a better-looking epoch is forbidden.
A later controlled-comparison plan may introduce one common validation-based
checkpoint rule for every method after explicit review.

The three prespecified seeds are `20261029`, `20261030` and `20261031`. They
are replications, never candidates from which to select a favorable result.
Python, NumPy, PyTorch CPU, CUDA, data-loader and CUDA-library determinism
settings must be recorded. If an operation cannot be made deterministic, the
run stops rather than downgrading silently.

## 9. Development proteins and metrics

Joint models train all 122 outputs. Only these frozen proteins guide
implementation decisions:

| Protein | ID |
|---|---:|
| ELAVL1 | 33 |
| HNRNPC | 53 |
| PTBP1 | 82 |
| PUM2 | 84 |
| QKI | 85 |
| RBFOX2 | 86 |
| TARDBP | 107 |
| U2AF2 | 112 |

For each epoch, config, seed and development protein, report validation
known-positive/known-negative counts, AUROC and average precision. Also report
the unweighted eight-protein macro mean, but do not select a config or epoch
from it. F1 threshold optimization is excluded from Task 004A. A score of 0.5
may be used only for descriptive diagnostics.

Training logs separately report the known weighted term, unknown-negative
term, coefficient-weighted total, gradient norm, learning rate, epoch time,
validation time, peak CPU memory and peak GPU allocated/reserved memory.
Non-development output summaries may be recorded for fidelity diagnostics,
but cannot justify an engineering change.

Task 003B validation baseline scores may be shown as fixed context. They are
not refitted, and Task 004A makes no test comparison.

## 10. Checkpointed implementation and execution plan

Each checkpoint requires review before the next. A failure is preserved and
reported; it is not patched inside a real training invocation.

### 004A-1 — forensic specification and synthetic implementation

- Extract the architecture, loss, optimizer, scheduler, label mapping and
  training loop into a tracked source-evidence specification.
- Implement model, loss decomposition, deterministic loader, metric code,
  atomic checkpoint writer and restart validation.
- Add notebook-oracle equivalence and hand-calculated loss tests.
- Add prediction-schema, membership-join and no-test-access tests with only
  synthetic fixtures.
- No real CSV, accepted FASTA, ignored artifact or GPU training is permitted.

**Gate:** focused tests pass twice; parameter count and oracle logits/gradients
match; the full existing repository test suite introduces no new failure.

### 004A-2 — local bounded data-contract smoke

- Revalidate immutable hashes and accepted membership.
- Build a compact train/validation-only index and exercise a small,
  deterministic real-data sample on CPU.
- Reconcile sample IDs, partitions, 500-nt lengths, A/C/G/T alphabet, output
  columns and label/mask counts independently.
- Run forward/backward/update, checkpoint save/reload and prediction identity
  checks on the bounded sample for all three loss configurations.

**Gate:** zero test labels/sequences retained; independent counts and
round-trips match; checkpoint reload reproduces logits exactly; no non-finite
value or identity mismatch.

### 004A-3 — Newton environment and GPU resource smoke

- First query the actual Newton CUDA driver/GPU and available package builds.
- Freeze an installable environment lock containing Python, PyTorch, CUDA
  runtime, NumPy and metric dependencies. Do not invent versions in advance.
- Build a self-contained, hash-bound package with source, config, environment
  evidence and only the permitted train/validation input artifacts.
- Request one GPU, four CPUs and sufficient RAM; record the actual GPU model,
  driver, CUDA/PyTorch versions and scheduler request.
- Run one deterministic bounded subset through one epoch for each config.
- Estimate full-run wall time and peak resources conservatively. No full pilot
  may start in the same job.

**Gate:** CUDA is genuinely used; all three runs finish; peak memory fits with
at least 20% headroom; projected job time fits the reviewed allocation; repeat
on the same seed gives identical sample order, checkpoint digest and
predictions, or a documented numerical tolerance accepted before proceeding.

### 004A-4 — full-data single-seed convergence gate

- Run all three configurations on the full train partition using seed
  `20261029`.
- Evaluate validation after each epoch, never test.
- Stop the package after these three runs and return sanitized evidence.

**Gate:** 30 epochs complete for every config; loss and gradients remain
finite; all validation identities/counts reconcile; epoch-30 checkpoints
reload; runtime/memory remain within the measured budget; no config shows
unresolved collapse or execution defect.

Scientific underperformance is reported, not treated as a code failure.
Collapse means a technical pathology such as constant/non-finite scores,
not merely a low AUROC.

### 004A-5 — two additional seeds and closure

- Only after 004A-4 acceptance, repeat unchanged with seeds `20261030` and
  `20261031`.
- Aggregate mean, standard deviation and range across the three seeds for each
  development protein/config.
- Write a sanitized closure manifest binding all configs, environments,
  checkpoints, logs, predictions, counts and resource evidence.

**Gate:** all nine runs reconcile, no seed is omitted, and no test access or
post-hoc hyperparameter change occurred.

## 11. Artifact and provenance contract

Expected ignored output root:

```text
artifacts/task004a_rescnn_pilot/
```

Expected tracked closure record only after acceptance:

```text
manifests/task004a_rescnn_pilot.json
```

Validation predictions follow the existing contract:

```text
sample_id,component_id,protein_id,fold,partition,seed,window,
config_id,config_hash,label,score
```

For Task 004A, `fold` is `components_v2_pilot`, `partition` is always
`validation`, and `window` is always 500. Predictions must be unique
by `(sample_id, protein_id, seed, config_id)`. Unknown label pairs do not enter
metrics, though their model scores may exist only in ignored diagnostic
artifacts if required to reproduce the joint output.

Every accepted stage uses an immutable generation directory and an atomic
selection record. Its inventory binds path, byte size and SHA-256 for configs,
source, environment, input evidence, model checkpoints, optimizer/scheduler
state, logs, predictions and summaries. Resume decisions revalidate live
upstream evidence rather than trusting a completed-stage flag.

Tracked manifests contain no sequences, row-level labels, row-level scores or
model weights.

## 12. Stop conditions

Stop before further execution if any of the following occurs:

- an immutable hash, row count, sample ID, partition or protein mapping differs;
- a test label or test sequence is parsed, cached, counted or scored;
- the 500-nt architecture differs from the notebook oracle or 9,029,562
  learnable parameters;
- a loss microtest or coefficient-isolation test fails;
- a denominator is zero, or any loss, gradient, weight or score is non-finite;
- checkpoint save/reload, optimizer/scheduler resume or artifact inventory
  differs;
- CUDA is absent from a GPU-authorized run;
- deterministic sample order or accepted numerical reproducibility fails;
- memory/disk/time limits are crossed or projected with inadequate headroom;
- a real run exposes a code defect; or
- the implementation attempts 251, 101 or 150 nt, a competitor, test scoring,
  best-epoch selection, early stopping, AMP or a changed scientific setting.

## 13. Acceptance and interpretation

Task 004A is accepted only when:

1. the model and loss have independent synthetic fidelity evidence;
2. all real-data train/validation joins and counts reconcile;
3. all three configs complete all three seeds with valid epoch-30 artifacts;
4. resource usage is measured rather than estimated from the old notebook;
5. the submitted-versus-ablation contrasts change exactly one loss choice at
   a time; and
6. the held-out test remains untouched.

Acceptance means the former model is ready for a controlled comparison. It
does **not** mean its scientific claims are validated and does not authorize a
test run.

## 14. Work deliberately deferred

- 251/101 architecture adaptation and window-length comparison;
- the in-house single-task model;
- DeepRiPe, Multi-resBind, PrismNet-seq and optional RNAProt;
- a common controlled loss across architectures;
- test evaluation, confidence intervals and paired significance tests;
- calibration, threshold selection, motif recovery and shuffle controls; and
- the final submitted/native operating-point comparison.

Those require new reviewed tasks after this fidelity and resource gate closes.
