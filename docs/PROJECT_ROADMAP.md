# RBP validation project roadmap

**Purpose:** provide one plain-language, end-to-end source of truth for the
investigation and comparison of the former teammate's 122-protein RBP model.

**Last updated:** 2026-09-30  
**Current stage:** Task 002C-3, fresh MMseqs2 cross-partition similarity audits
for the accepted component assignment

**Model comparison status:** not started; the benchmark split must be frozen
first

Detailed task specifications, reviews, handoffs, and manifests remain in their
existing directories for reproducibility. This document explains how those
pieces fit together and what each scientific step means.

## 1. Project question

The project asks whether the former teammate's joint residual CNN predicts RNA
binding better than appropriate published methods when every method is trained
and evaluated on the same leakage-safe data.

There are four related questions:

1. Does the submitted joint 122-output model outperform published competitors?
2. Does joint training help compared with training a separate model for each
   protein?
3. How much of the result comes from the submitted loss design, particularly
   the positive weight of 15 and the penalty that pushes unknown labels toward
   zero?
4. How much of the result comes from using a 500-nt input rather than a shorter
   251- or 101-nt window?

The comparison cannot answer these questions reliably until closely related
sequences are prevented from appearing on both sides of the train/test
boundary.

## 2. Dataset and label contract

The frozen dataset contains 361,180 rows. Each row contains:

- one 500-nt RNA sequence stored as 2,000 one-hot bits;
- a sparse set of known labels for 122 RNA-binding proteins; and
- a stable ID, `row_<zero-based row number>`.

The real label serialization is:

- unsigned `k`, for example `7`: known positive for protein `k`;
- `-k`, for example `-18`: known negative for protein `k`; and
- absent `k`: unknown, not a negative.

An explicit `+k` is accepted as a compatibility spelling but is not used by the
frozen CSV. The complete frozen file contains 201,391 known-positive tokens and
173,532 known-negative tokens. Unknown protein/row combinations greatly
outnumber both and must not silently be treated as experimentally verified
negatives.

## 3. End-to-end workflow and current status

| Phase | Purpose | Current status |
|---|---|---|
| 0. Repository and data audit | Freeze inputs, hashes, schemas, and label meanings | Complete |
| 1. Coordinate feasibility | Test whether genomic coordinates can be recovered safely | Deferred; not required for the core comparison |
| 2A. Sequence decoding | Convert bit-encoded sequences to validated nucleotide strings | Complete |
| 2B. Similarity grouping | Identify related sequences at 500, 251, and 101 nt | Complete and accepted |
| 2C. Partition construction | Assign intact groups to train/validation/test and audit leakage | In progress |
| 3. Simple baselines | Establish how far trivial sequence properties can predict binding | Not started |
| 4. Development pilot | Verify model implementations and compute requirements on eight proteins | Not started |
| 5. Controlled comparison | Compare architectures under common data, windows, and loss | Not started |
| 6. Submitted/native settings | Evaluate the submitted recipe and method-specific operating points | Not started |
| 7. Locked analysis | Statistical comparison, uncertainty, resources, and final report | Not started |

## 4. Phase 0 — repository and data audit

### 4.1 Freeze the original materials

- Inventory the original CSV, notebook, checkpoint, cached arrays, and protein
  index.
- Record file sizes and SHA-256 hashes.
- Keep large or private artifacts out of ordinary Git while committing small
  manifests that identify them unambiguously.

### 4.2 Audit the dataset

- Require exactly 361,180 rows and the expected `sequence,labels` columns.
- Validate the 500-nt one-hot encoding.
- Validate protein IDs 1–122 and distinguish positive, known negative, and
  unknown labels.
- Record per-protein positive and negative counts and descriptive GC
  statistics.

### 4.3 Inspect the submitted experiment

- Reconstruct how the notebook loads labels, creates masks, makes folds,
  trains the model, and evaluates predictions.
- Record the submitted architecture, positive weight, unknown-label penalty,
  seed, window length, and checkpoint.
- Treat discrepancies between prose and executable notebook behavior as
  findings to resolve, not assumptions to hide.

**Status:** complete. The recent `+k` versus `k` problem was a new parser and
documentation error; the submitted notebook itself interpreted unsigned
positive labels correctly.

## 5. Phase 1 — coordinate feasibility

Coordinates would help group overlapping genomic windows and enable optional
biological context analyses. They are not inputs to the former teammate's
predictor.

The project implemented guarded reference download, reference derivation,
alignment, exact matching, provenance, and reconciliation. The accepted hg38
reference was derived successfully, but construction of the required
single-part splice-aware index exceeded the available memory on the tested
12.7–16-GiB hosts.

The coordinate path was therefore stopped safely and retained as optional
future work. No coordinate-derived biological claim is currently made, and
coordinate recovery does not block the core model comparison. Sequence
similarity grouping is the active leakage-control method.

## 6. Phase 2A — sequence decoding

### What decoding means

The CSV does not store ordinary letters. Every nucleotide is represented by a
four-bit one-hot group in A/C/G/T order:

| Bits | Nucleotide |
|---|---|
| `1000` | A |
| `0100` | C |
| `0010` | G |
| `0001` | T |

Decoding converts the 2,000 bits in a row into a 500-letter nucleotide string.
It also creates the centered 251-nt and 101-nt versions needed by planned
models and similarity checks.

This is a deterministic representation conversion, not a learned model and
not a biological inference. The decoder verifies:

- exactly 2,000 bits and 500 valid one-hot groups per row;
- exactly one of A/C/G/T at every position;
- exactly one record for every canonical row ID;
- correct 500-, 251-, and 101-nt lengths; and
- reproducible file hashes.

**Status:** complete for all 361,180 rows at all three widths.

## 7. Phase 2B — sequence-similarity grouping

### 7.1 Why clustering was necessary

A random row-level split assumes that every row is independent. That is unsafe
when two rows are exact copies, reverse complements, overlapping variants, or
highly similar sequences. A model could then see one version during training
and a near-copy during testing, inflating apparent generalization.

### 7.2 What was tested

The label-blind MMseqs2 analysis grouped sequences independently at:

- 500 nt: at least 90% identity and 80% bidirectional coverage;
- centered 251 nt: at least 90% identity and 95% bidirectional coverage; and
- centered 101 nt: at least 90% identity and 95% bidirectional coverage.

Both orientations were considered, low-complexity masking was disabled under
the frozen rule, and exact/reverse-complement duplicates were protected by an
independent code path. Protein labels and model outputs were not used.

### 7.3 Accepted results

| Width | Rows | Clusters | Largest cluster |
|---:|---:|---:|---:|
| 500 nt | 361,180 | 174,190 | 231 |
| 251 nt | 361,180 | 259,288 | 65 |
| 101 nt | 361,180 | 296,182 | 35 |

These are three different similarity views. The lower number of 500-nt
clusters means that the 500-nt rule connected more rows than either shorter,
stricter-coverage rule.

### 7.4 Should these results concern us?

They justify concern about the former row-level split, but they do not make the
dataset unusable:

- The union contains 173,465 final components.
- 119,999 components are singletons.
- 53,466 components contain multiple rows.
- 241,181 rows, or 66.8% of the dataset, belong to a multi-row component.
- The largest component contains 611 rows, only 0.169% of the dataset.
- The largest 20 components together contain 4,174 rows, only 1.156%.
- The prespecified giant-component gates were 5% for one component and 20%
  for the largest 20; neither gate was close to being triggered.

Interpretation:

- A substantial fraction of rows has at least one similarity connection, so a
  naive row split has a real risk of train/test leakage.
- There is no evidence that a few huge repeat families dominate the dataset,
  so a useful component-level 70/15/15 split should remain feasible.
- We have not yet measured how many of these relationships actually cross the
  former teammate's fold. That number will come from the legacy-split
  diagnostic; until then, we must not claim that the former score was inflated
  by a particular amount.

## 8. Phase 2B — component construction

A cluster is the grouping produced at one window width. A final component is
the union of all protected relationships across all three widths plus exact and
reverse-complement duplicate relationships.

For example:

- A is similar to B at 500 nt;
- B is similar to C at 101 nt; therefore
- A, B, and C belong to one indivisible final component, even if A and C were
  not directly reported as a match.

This connected-component rule prevents indirect leakage chains. Every final
component receives a deterministic ID derived from its sorted row IDs. During
partitioning, the component—not the individual row—is the smallest movable
unit. The accepted construction produced 173,465 final components from the
361,180 rows.

## 9. Phase 2B/2C — component evidence

"Component evidence" is the proof that the large clustering run completed as
claimed and that later code is using exactly its accepted output. It is not a
new biological feature.

The evidence includes:

- the three per-width membership tables;
- the final row-to-component membership table;
- the component-size and giant-component report;
- selection records identifying the accepted generation for each stage;
- complete file inventories with sizes and SHA-256 hashes;
- the MMseqs2 version and binary identity;
- commands, environment, host, resource, and runtime records; and
- cross-checks that all 361,180 canonical IDs appear exactly once.

The repository contains a small sanitized manifest that binds this evidence to
the returned high-memory run without committing the large artifacts. Current
verification code re-hashes and re-parses the live evidence before downstream
execution and refuses stale or substituted files.

## 10. Phase 2C — partition software

The partition software turns the accepted components into the final benchmark
split. It performs the following steps:

1. Revalidate the dataset, component membership, component report, protein
   list, and configuration hashes.
2. Stream the CSV once and aggregate known-positive and known-negative counts
   for each indivisible component.
3. Assign whole components toward 70% train, 15% validation, and 15% test.
4. Balance 244 label dimensions separately: positive and known-negative counts
   for each of 122 proteins.
5. Require at least 30 known positives and 30 known negatives for every protein
   in both validation and test.
6. Use bounded deterministic whole-component moves or swaps if a floor is not
   initially met. It may never split a component or silently weaken a floor.
7. Run the assignment twice and require identical membership and scientific
   summaries.
8. Write transactionally so a failure cannot replace a prior accepted result.

Labels influence balance only after similarity components are frozen. They can
never create, merge, or split a similarity component.

### Accepted Task 002C-2B result

The initial real assignment stopped safely because the new parser incorrectly
required an explicit plus sign. The corrected parser reproduced all 361,180
rows, 201,391 positives, and 173,532 negatives with no invalid labels.

Primary and independent-repeat assignments then produced byte-identical
membership and scientific summaries:

| Partition | Rows | Fraction |
|---|---:|---:|
| Train | 246,465 | 68.2388% |
| Validation | 57,391 | 15.8899% |
| Test | 57,324 | 15.8713% |

All 173,465 components remained intact. Validation and test each retained at
least 101 known positives and 81 known negatives for every protein, comfortably
above the frozen 30/30 floor. No repair move or swap was needed. The assignment
is accepted as the sole candidate for finalization, but it is not yet the
released benchmark split because the independent leakage audits remain.

## 11. The known-negative imbalance problem

The labels are three-state: positive, known negative, or unknown. The former
notebook created:

- `targets`: 1 for a positive and 0 for both a known negative and an unknown;
- `masks`: 1 for a known positive or known negative and 0 for an unknown.

It then stratified folds using `targets * masks`. Because every known negative
already has target 0, multiplication still leaves both known negatives and
unknowns as 0. The stratifier therefore saw and balanced positives, but it
could not distinguish known negatives from unknown entries.

Consequences:

- a validation/test fold can receive uneven known-negative counts for some
  proteins;
- AUROC and other binary metrics may then be based on small or inconsistent
  negative denominators;
- comparisons between proteins or folds can become unnecessarily noisy; and
- the old split may look balanced in positives while still being poorly
  balanced for actual evaluable negative examples.

This does not mean that all negative labels are wrong, nor does it by itself
prove that the former model's score is biased upward. It means the fold-making
procedure did not explicitly protect known-negative balance.

The new partition corrects this by balancing positives and known negatives as
244 separate dimensions and excluding unknowns from both counts.

This split issue is distinct from the submitted loss's unknown-label penalty.
The loss also pushes unknown entries toward zero during training; that is a
separate modeling choice that will be isolated later with controlled ablations.

## 12. Remaining Phase 2C leakage audits

After assignment is accepted:

### 12.1 Former-split diagnostic

- Reproduce the former notebook's first 80/20 fold exactly.
- Measure how many final components and per-width clusters cross that old
  boundary.
- Report train and holdout rows affected by crossing components.
- Use the result only as a diagnostic; never reuse the old split for the new
  comparison.

**Accepted result:** the former fold contains 26,765 final components spanning
both train and holdout, 51.6% of all components represented in holdout. A total
of 45,937 of 72,236 holdout rows (63.6%) and 120,760 of 288,944 training rows
(41.8%) belong to crossing components. The former fold is therefore not
leakage-safe under the frozen grouping definition, although this diagnostic
does not quantify the resulting effect on model performance.

### 12.2 Independent exact/reverse-complement audit

- Rebuild canonical exact/RC identities independently of MMseqs2.
- Require zero exact or reverse-complement relationships across the new
  train/validation/test boundaries at 500, 251, and 101 nt.

**Accepted result:** zero cross-partition violations at every width. The 500-
and 251-nt data contain no exact/RC duplicate group; the two size-two 101-nt
groups are both contained wholly within validation.

### 12.3 Fresh near-similarity audit

- Regenerate partition FASTAs from the frozen assignment.
- Run fresh MMseqs2 searches in both directions for every partition pair and
  every protected width: 18 directed searches in total.
- Use the same frozen identity/coverage definitions but do not reuse the
  original clustering databases.
- Require zero qualifying cross-partition hits.

Assignment, the legacy diagnostic, and exact auditing should fit the local
16-GiB Mac. The fresh MMseqs2 searches are the only potentially high-memory
remaining data-preparation step. The local host did not have enough available
memory for this checkpoint, so Task 002C-3/4 is packaged as a single offline,
native Apple-Silicon handoff for the 64-GiB collaborator Mac. The handoff runs
all three probes and 18 searches sequentially, stops without retry on any
failure or nonzero hit, conditionally finalizes, and creates one small return
ZIP whether it succeeds or stops. It does not repeat any accepted earlier
stage.

### 12.4 Freeze the final split

Only after every gate passes, publish the deterministic membership containing
`sample_id`, `component_id`, and `partition`, plus a sanitized manifest of all
inputs, counts, diagnostics, hashes, commands, and resources. No model result
may influence this split.

## 13. Phase 3 — simple baselines

Before complex neural networks, establish inexpensive reference points:

1. random or prevalence-only prediction;
2. GC-content logistic regression;
3. 3-mer logistic regression, using counts of every length-three nucleotide
   word as features;
4. 6-mer logistic regression, using counts of every length-six nucleotide
   word as features; and
5. a frozen GC-matched-negative sensitivity analysis so that a method cannot
   appear strong merely by exploiting systematic GC differences between known
   positives and known negatives.

All fitted transformations use training data only and are evaluated on the
same locked samples and window widths as the models.

## 14. Phase 4 — development pilot

Use eight development proteins—TARDBP, ELAVL1, U2AF2, PTBP1, HNRNPC, PUM2,
QKI, and RBFOX2—to validate implementations and estimate compute. Joint models
still train all 122 outputs, but only these eight results may guide engineering
choices.

Substeps:

- reproduce the in-house architecture and checkpoint behavior;
- smoke-test the three core competitor implementations;
- verify sample/output alignment, loss terms, early stopping, and checkpoint
  restoration;
- measure runtime, memory, learning curves, and seed variability; and
- compare positive weights 15 and 1 for the joint in-house model.

The held-out test partition remains untouched during this phase.

## 15. Phase 5 — controlled model comparison

The core published competitors are:

1. DeepRiPe, the central multitask comparator;
2. Multi-resBind, the closest multi-label residual comparator; and
3. PrismNet-seq, an established per-protein sequence-only comparator.

RNAProt is the first optional addition if the core comparison is stable and
its official environment is inexpensive to run.

At a common sequence window and common masked, unweighted loss, compare:

- in-house joint versus in-house single-task models;
- in-house joint versus DeepRiPe;
- in-house joint versus Multi-resBind; and
- in-house single-task versus PrismNet-seq.

This controlled layer separates architecture and joint-training effects from
the submitted loss recipe.

## 16. Phase 6 — submitted and native operating points

After the controlled comparison:

- evaluate the submitted in-house recipe with positive weight 15 and unknown
  penalty 1;
- evaluate an otherwise identical version without the unknown penalty;
- compare 101-, 251-, and 500-nt in-house inputs;
- report published/native competitor settings separately from the controlled
  architecture comparison; and
- run GC-matched and other prespecified biological-validity diagnostics.

Modern ports are described honestly as retrained implementations, never as the
authors' released pretrained models.

## 17. Phase 7 — statistical analysis and report

The final report will include:

- per-protein AUROC on known positive/known-negative pairs;
- paired differences between methods on identical test examples;
- uncertainty intervals using appropriate protein and component/locus units;
- calibration metrics where loss choices are being compared;
- seed variability;
- runtime, peak memory, storage, parameter count, and number of trained models;
- legacy-split leakage diagnostics; and
- explicit limitations, including deferred coordinates and any competitor
  fidelity compromises.

If the former model's advantage disappears after leakage removal or controlled
loss matching, that is a valid result. The project then becomes a benchmark and
reproducibility study rather than forcing a positive model claim.

## 18. Immediate next actions

1. Execute the reviewed one-shot Task 002C-3/4 bundle on the 64-GiB native
   Apple-Silicon host and return its generated ZIP.
2. Independently review the three probes, all 18 directed searches, and the
   conditional finalization evidence.
3. Freeze the final partition only if every search has zero qualifying hits.
4. Begin simple baselines only after the split is locked.

## 19. Claims we can and cannot make today

We can say:

- the data and label counts are reproducibly audited;
- the former notebook interpreted unsigned positives correctly;
- many rows have sequence-similar partners, so leakage-safe grouping is
  justified;
- no giant sequence component makes the dataset obviously unusable; and
- the accepted similarity evidence is reproducible and hash-bound.

We can now also say:

- the former row-level fold is not leakage-safe under the frozen sequence
  relation; and
- the new component assignment contains no exact/reverse-complement leakage at
  the protected widths.

We still cannot say:

- how many performance points the former split's leakage contributed;
- whether, or by how much, the former model's reported performance is inflated;
- whether the former model is better than DeepRiPe, Multi-resBind, or
  PrismNet-seq; or
- which loss/window/architecture choice explains any future advantage.

Those are the questions the remaining workflow is designed to answer.
