# Task 004A-2 — local bounded data-contract smoke

**Status:** planning draft for independent review. No implementation or real
data execution is authorized by this document.

**Parent:** `docs/tasks/004a_rescnn_reconstruction_and_development_pilot.md`

**Execution host:** the local project Mac, CPU only. Darwin, Newton, CUDA and
the former teammate checkpoint are outside this checkpoint.

## 1. Purpose

Task 004A-1 established that the clean 500-nt ResCNN, submitted loss and two
loss ablations match the hash-bound notebook source on synthetic inputs.
Task 004A-2 connects that accepted implementation to the real, leakage-safe
development data without performing full training.

It must answer five engineering questions before a GPU package is built:

1. Can the accepted components-v2 membership, CSV and 500-nt FASTA be joined
   exactly while interpreting no held-out test labels or sequences?
2. Can a genuinely compact train/validation cache be built without retaining
   all 303,582 development sequences in Python objects or tensors?
3. Do the frozen loss, Adam and scheduler factories use only the reviewed
   configuration values?
4. On real inputs, do all three paired loss configurations complete one CPU
   update, validation pass and trusted smoke-checkpoint round trip?
5. Is local memory/runtime small enough to justify moving to Task 004A-3?

This is a **contract and execution smoke**, not a training experiment. Its
scores are not estimates of model performance, no configuration is selected,
and no test prediction is made.

## 2. Accepted prerequisites and exact inputs

Task 004A-2 may begin only after Task 004A-1 is accepted. Every invocation
must hash the following before interpreting labels or bases:

| Input | Expected SHA-256 |
|---|---|
| `configs/models/task004a_v1.toml` | `fb3faeee566b1eb799f4c550f143cf05d90358301bd732e21a4928208e2c498f` |
| `dataset_K562_multilabel_with_NEGs.csv` | `982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945` |
| `manifests/dataset_audit.json` | `e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c` |
| `configs/proteins.tsv` | `374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9` |
| `manifests/sequence_decode_002b2.json` | `d9826b471ef3f12539eaf51be5c21ba8be20190f3d7c6042143e839d6bb0a7b3` |
| `manifests/sequence_partitions_002c_v2.json` | `b6f6f16fab4e6afc23c16a8dc5b3476130719d579f637cd3cf18002cc7fb7419` |
| accepted membership | `ca527da4f0c0615bcb9d31c6fc705523238e8fb8f4751473ccc2af3ee0aecddb` |
| accepted 500-nt FASTA | `0849d4f8aceaed37c3dc7fec69056f38ae344338aa4adf321a3e11c4a72df0b0` |

The intended local membership copy is
`artifacts/task003b_simple_baselines/inputs/membership.tsv.gz`. The FASTA path
must be resolved from the accepted decode manifest, not independently
invented. The paths are conveniences; the hashes and manifest relationships
are authoritative.

The membership must reconcile to exactly 361,180 canonical IDs in numeric
`row_<n>` order, 169,699 components and these row counts:

| Partition | Rows | Permitted interpretation in 004A-2 |
|---|---:|---|
| train | 246,017 | labels and 500-nt sequence |
| validation | 57,565 | labels and 500-nt sequence |
| test | 57,598 | ID and partition only |

The rejected v1 membership, former row-level fold, 251/101 FASTAs, original
checkpoint and every test-scoring artifact are forbidden inputs.

## 3. One local invocation, two internal gates

After implementation review, one reviewed command may execute these gates in
order. Failure at either gate stops the invocation; it does not patch or retry.

### Gate A — full-universe streaming audit and sample selection

Gate A reads the accepted membership, CSV and 500-nt FASTA in canonical
lockstep. It may read raw test-row bytes because the files are sequential, but
the membership partition is decided before a field supplier may interpret a
label or sequence.

For all 303,582 train/validation rows it must:

- validate canonical ID and partition;
- parse the signed/unsigned 122-protein label grammar;
- decode the CSV's 2,000-bit sequence into 500 A/C/G/T bases;
- validate the matching FASTA header, length and alphabet;
- require byte-exact equality between the decoded CSV sequence and FASTA;
- aggregate per-partition known-positive, known-negative and unknown counts;
- verify protein ID `k` maps to output column `k-1`; and
- retain only aggregate counts, digests and bounded sampler state.

For all 57,598 test rows it may validate only the canonical row ID,
membership presence and partition. The CSV label/sequence suppliers and FASTA
sequence interpreter must not be called. The raw CSV/FASTA record is consumed
and discarded without label parsing, bit decoding, alphabet counting,
length-based inference or tensor construction.

The audit must record explicit counters:

```text
test_rows_seen = 57598
test_label_supplier_calls = 0
test_csv_sequence_supplier_calls = 0
test_fasta_sequence_interpretations = 0
test_tensor_rows = 0
test_prediction_rows = 0
test_accessed = false
```

Calling any forbidden supplier is an immediate failure. A synthetic test must
plant malformed test labels and bases and prove that they remain
uninterpreted, while the same malformed values in train or validation fail.

#### Deterministic smoke samples

Gate A selects exactly 513 train and 513 validation IDs. The selection is a
coverage fixture, not a representative scientific sample:

1. for every partition, protein and known class, choose the row with the
   smallest SHA-256 rank derived from master seed `20261029`, partition,
   protein ID, class and canonical sample ID;
2. take the union of those quota winners;
3. fill to 513 with the smallest partition-level SHA-256 ranks not already
   selected; and
4. sort the retained IDs canonically before cache materialization.

The accepted split guarantees at least 30 examples of each known class for
every protein in validation/test and substantially more in train, so the 244
per-partition protein/class quotas are feasible within 513 unique rows. The
implementation must nevertheless verify feasibility rather than assume it.

This label-aware sampling is permitted only because it uses train and
validation, and only to exercise all 122 output paths. It must never be used
to report performance, select a configuration or change the split.

The selected IDs remain in the ignored generation only. The tracked manifest
records counts and deterministic set/order digests, not row IDs or labels.

### Gate B — bounded paired CPU smoke and deterministic repeat

Gate B makes a second partition-first streaming pass and materializes only the
1,026 selected rows. The compact cache contains:

- base codes as `uint8`, shape `[1026, 500]`;
- targets and masks as exact binary arrays, converted to float32 only for a
  batch;
- canonical sample/component IDs and partition codes; and
- no unselected sequence or label field.

It must not construct the current full-universe tuple-of-records plus tensor
duplication. Cache bytes, process peak RSS and wall time are measured.

For master seed `20261029`, the smoke runs `submitted`,
`submitted_no_unknown` and `joint_standard` sequentially on CPU. Each config
must independently recompute its own seed streams and epoch order. The three
must have identical:

- initial model-state hash;
- two admitted 256-row training batches;
- one dropped training row (`513 mod 256 = 1`);
- pre-update training-mode logits, including dropout realization; and
- validation order of 256, 256 and 1 rows with no drop.

For each configuration the runner performs exactly:

1. one forward pass on the first admitted training batch;
2. frozen-config loss construction and component reporting;
3. one backward pass and gradient evidence capture;
4. one frozen-config Adam update;
5. an evaluation-mode pass over all 513 validation rows;
6. float32 `sigmoid(logits)` before all score diagnostics and metrics;
7. one frozen-config `ReduceLROnPlateau` call with the 122-output macro AUROC;
8. a smoke-checkpoint save, authenticated reload into a fresh model and exact
   validation-logit/prediction identity check.

The validation coverage fixture must contain both known classes for every
output, so the metric path must report 122/122 eligible outputs. These AUROCs
and APs are labelled `coverage_smoke_only` and are forbidden from scientific
reports or model selection.

The run must prove before the Adam step that every pair of loss configs has a
different total-loss and canonical gradient hash on identical logits. This
separately demonstrates both the unknown penalty and positive multiplier;
post-Adam state differences alone are insufficient because Adam's first step
can obscure gradient-magnitude changes.

The complete bounded smoke is then repeated from a fresh model and fresh
output subdirectory. Initial states, order/tail evidence, loss components,
gradient hashes, checkpoint model hashes and reloaded validation logits must
match exactly between primary and repeat. Runtime and memory may differ.

## 4. Frozen factories and checkpoint roles

Task 004A-2 adds factories that accept the loaded `Task004AConfig` and one of
its exact `LossConfig` objects. Callers cannot override coefficients or
optimizer/scheduler parameters.

The factories must assert these effective values after construction:

- masked BCE coefficients are exactly `(15,1)`, `(15,0)` or `(1,0)` with the
  matching reviewed config ID;
- Adam is `lr=1e-3`, betas `(0.9,0.999)`, epsilon `1e-8`, weight decay 0 and
  AMSGrad false; and
- `ReduceLROnPlateau` is mode max, factor 0.5, patience 2, relative threshold
  `1e-4`, cooldown 0, minimum LR 0 and epsilon `1e-8`.

Validation is unshuffled. Scheduler input and reported scores are computed
from float32 sigmoid probabilities, matching notebook cell 12; logits may not
be substituted even though AUROC is usually rank-invariant, because float32
sigmoid ties and saturation can change the actual observed statistic.

The one-update artifact is not an epoch-30 model. It therefore uses a separate
`task004a_smoke_checkpoint_v1` schema with role
`local_data_contract_after_one_update` and `training_step=1`.

The trusted final-model loader is simultaneously tightened so its expected
epoch comes from the frozen config (`epochs=30`) rather than an arbitrary
caller argument. It accepts only the final-training role. A smoke checkpoint
can never be presented as a final model, and neither loader accepts the former
checkpoint hash.

## 5. Environment and resource boundary

Before any real input is opened, implementation must create and verify a
local CPU environment manifest recording at least:

- Python, PyTorch and NumPy versions;
- OS, architecture and CPU identity;
- exact installed-package lock or complete relevant package inventory;
- executable/interpreter hashes where practical; and
- source/config/environment hashes used in every checkpoint identity.

The existing ad-hoc cached PyTorch overlay is not accepted as undocumented
real-run provenance. The actual available local environment is queried first;
versions are recorded rather than invented. Environment creation and the
source-only suite must complete before real data authorization.

Frozen execution limits for the local run are:

| Resource | Gate |
|---|---:|
| device | CPU only |
| numerical worker threads | 4 maximum |
| installed RAM | at least 16 GiB, numeric reading required |
| available RAM before Gate A and Gate B | at least 4 GiB |
| free disk before each gate | at least 20 GiB |
| accepted generation size | at most 1 GiB |
| peak RSS | at most 4 GiB |
| total invocation timeout | 2 hours |

No input file is copied into the output generation. A resource-reading
failure is fail-closed. A resource-gate failure is evidence that 004A-2 needs
a revised host plan; it is not authority to weaken the scientific contract.

## 6. Transactional output and provenance

The ignored output root is
`artifacts/task004a_rescnn_pilot/004a2_local_smoke/`. It contains generation
artifacts, checkpoints, bounded validation predictions, logs and the selected
record. A candidate is promoted only after both gates, primary/repeat
reconciliation and complete inventory hashing succeed.

The selection record must bind:

- every immutable input hash and byte size;
- source commit, source-tree digest, semantic config digest and environment
  digest;
- full audit counters and aggregate reconciliation;
- sample counts and ID/order digests;
- compact-cache shape/dtype/byte evidence;
- the three config identities and paired-start/order/tail evidence;
- pre-update loss/gradient evidence;
- checkpoint/prediction inventories and primary/repeat comparison;
- wall time, peak RSS, free disk and thread cap; and
- `test_accessed: false` plus all zero test-field counters.

After independent acceptance, one small tracked manifest may be committed as
`manifests/task004a_local_smoke_004a2.json`. It contains no row-level ID,
label, sequence, logit, gradient tensor or prediction. Large/row-level
artifacts remain ignored.

All writes use a whole-generation transaction. A failed computation, failed
reconciliation or failed selection-record write removes the new candidate and
leaves any prior accepted generation byte-identical. Restart skips require
fresh input/environment hashes and full accepted-inventory validation.

## 7. Implementation and review sequence

This task deliberately uses only two handoffs.

### 004A-2A — implementation without real data

Implement the streaming boundary, deterministic coverage sampler, compact
sample cache, frozen factories, separate smoke checkpoint, local runner,
resource gates and transactional records. Tests use only synthetic fixtures,
including malformed hidden test fields. Do not open or hash real inputs.

Required focused tests include:

- canonical membership/CSV/FASTA lockstep and mismatch failures;
- supplier counters proving malformed test fields remain uninterpreted;
- 513-row quota/fill determinism, uniqueness, class coverage and digest
  stability under input-order changes;
- compact dtype/shape and no full-universe record retention;
- config-only loss/Adam/scheduler construction and unknown override refusal;
- independent per-config order derivation and paired dropout/logits;
- every-pair pre-update loss and gradient distinction;
- float32 sigmoid metric semantics, 122/122 eligibility and unshuffled
  validation tail retention;
- smoke/final checkpoint role separation, pre-load authentication and exact
  reload identity;
- transaction rollback, restart invalidation and resource failures; and
- manifest sanitation and explicit `test_accessed:false`.

Run the focused suite twice. Run the repository suite far enough to establish
that no new failures occur. Then request one independent implementation review.

### 004A-2B — one reviewed local real-data invocation

Only after 004A-2A acceptance, run the single Gate A + Gate B invocation. Do
not patch or retry inside it. If the real data exposes a mismatch, preserve a
sanitized stop record and return to review. If it succeeds, independently
recompute the hashes/counters/reconciliation, commit only the sanitized
manifest, and request acceptance.

## 8. Acceptance gates

Task 004A-2 passes only if all of the following hold:

1. all immutable inputs and manifest relationships match;
2. 361,180 canonical membership rows reconcile exactly;
3. all 303,582 train/validation CSV-to-FASTA sequences match exactly;
4. all test-field interpretation/tensor/prediction counters are zero;
5. train and validation samples contain 513 unique allowed IDs and both known
   classes for every one of 122 outputs;
6. compact cache evidence is within the frozen resource limits;
7. all three configs share initialization, order, dropped row and pre-update
   logits while every config pair has distinct loss/gradient evidence;
8. Adam/scheduler effective settings equal the frozen config;
9. validation keeps its singleton tail and metrics consume float32 sigmoid
   probabilities with 122/122 eligible outputs;
10. every value, gradient and score is finite;
11. smoke checkpoint authentication/reload and exact logits/predictions pass;
12. primary and repeat scientific evidence is identical; and
13. the selected generation inventory and sanitized manifest reproduce.

## 9. Explicit non-goals

Task 004A-2 does not:

- train an epoch or estimate model quality;
- access, score or characterize the test partition;
- select a loss config, seed, epoch or threshold;
- load or evaluate the former checkpoint;
- use 251, 101 or 150 nt inputs;
- compare against Task 003B baselines;
- use a GPU or prepare Newton jobs;
- change the accepted split, labels, architecture or loss; or
- authorize Task 004A-3 automatically.

After acceptance, Task 004A-3 will freeze the Newton CUDA environment and run
a separately reviewed one-epoch GPU resource smoke before any 30-epoch pilot.
