# Task 003B — Simple sequence baselines on the locked split

**Status:** checkpoints 003B-1 and 003B-2 accepted; 003B-3 remains blocked
until explicit authorization to access the test partition

**Phase:** 3B, first predictive experiment after Task 003A

**Default execution host:** local project Mac. The development pilot must
measure actual runtime and memory before deciding whether the full 122-protein
run needs Darwin. No GPU is required.

## 1. Objective

Build a small, deterministic reference pipeline that answers a deliberately
simple question before any neural-network comparison:

> How much protein-binding discrimination is available from prevalence, GC
> content, short 3-mer composition, and longer 6-mer composition when every
> method uses the accepted leakage-safe split?

Task 003B establishes baselines, difficulty estimates and an executable
prediction contract. It does **not** run the former teammate's ResCNN,
DeepRiPe, Multi-resBind or PrismNet-seq. Those models begin only after this
task closes.

## 2. Immutable inputs

| Input | Bytes | SHA-256 |
|---|---:|---|
| `dataset_K562_multilabel_with_NEGs.csv` | 724,425,277 | `982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945` |
| `manifests/dataset_audit.json` | 27,550 | `e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c` |
| `configs/proteins.tsv` | 1,143 | `374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9` |
| `manifests/sequence_decode_002b2.json` | 8,957 | `d9826b471ef3f12539eaf51be5c21ba8be20190f3d7c6042143e839d6bb0a7b3` |
| `manifests/sequence_partitions_002c_v2.json` | 2,868 | `b6f6f16fab4e6afc23c16a8dc5b3476130719d579f637cd3cf18002cc7fb7419` |

The closure manifest binds the accepted production return and final membership:

- 361,180 canonical rows;
- 169,699 connected components;
- 246,017 train, 57,565 validation and 57,598 test rows;
- membership SHA-256
  `ca527da4f0c0615bcb9d31c6fc705523238e8fb8f4751473ccc2af3ee0aecddb`;
- zero detected cross-partition relationship under the frozen rules.

Every invocation must revalidate the files and accepted membership before
reading labels or sequences. The former teammate fold and rejected intermediate
split are forbidden inputs.

## 3. Label contract

For protein `k`:

- unsigned `k` or explicit `+k` is a known positive;
- `-k` is a known negative;
- absence of `k` is unknown and is excluded from fitting and metrics.

Unknown rows must never be silently converted into negatives. Every reported
protein/window/partition cell must reconcile its positive and negative counts
against a fresh CSV stream and the accepted membership.

## 4. Prespecified baselines

### 4.1 Training-prevalence baseline

For each protein, predict the positive fraction in the fitting partition for
every evaluation row. This constant-score baseline is deterministic. With both
classes present, AUROC must be exactly 0.5 and average precision must equal the
evaluation prevalence. It replaces an arbitrary random-score baseline while
testing the same no-sequence-information null.

### 4.2 GC logistic regression

One feature per row: the fraction of nucleotides that are G or C in the exact
window being evaluated. Fit an unweighted, intercept-bearing, L2-regularized
logistic regression independently for each protein.

### 4.3 3-mer logistic regression

Use all `4^3 = 64` ordered A/C/G/T words. A feature is the overlapping count of
that word divided by `window_length - 3 + 1`. The fixed vocabulary is
lexicographic under A, C, G, T. Fit the same independent logistic model.

### 4.4 6-mer logistic regression

Use all `4^6 = 4,096` ordered words and normalize by
`window_length - 6 + 1`. The matrix must remain sparse. Fit the same independent
logistic model.

The k-mer features preserve order inside each k-mer; they are not simple base
counts. Reverse complements are not collapsed because the submitted predictor
also receives the sequence in its supplied orientation. The leakage-safe split
already protects forward and reverse-complement relationships across
partitions.

## 5. Frozen model and tuning rules

- Solver: scikit-learn `LogisticRegression`, `penalty="l2"`,
  `solver="liblinear"`, `fit_intercept=True`, `class_weight=None`,
  `max_iter=2000`, `tol=1e-6`, deterministic seed `20261028`.
- Dedicated environment pins Python 3.12, NumPy 2.0.2, SciPy 1.16.1 and
  scikit-learn 1.6.1. BLAS/OpenMP thread counts are fixed to one and recorded.
- GC is standardized by training mean and standard deviation. K-mer columns
  use training-only `StandardScaler(with_mean=False)` so the representation
  remains sparse. A zero-variance feature remains zero.
- Candidate inverse regularization strengths: `C = [0.01, 0.1, 1.0, 10.0]`.
- Select one C for each `(GC/3-mer/6-mer, 500/251/101 nt)` combination by the
  unweighted macro mean validation AUROC across the eight development proteins.
- Ties use the smaller C.
- Do not select C separately for each protein and do not change the grid after
  viewing validation results.
- No class weighting, oversampling, threshold selection or probability
  calibration is used.
- `liblinear` penalizes its synthetic intercept feature. This differs slightly
  from textbook unpenalized-intercept logistic regression but is accepted and
  held identical across proteins, widths and runs.
- Feature formulas and estimator settings are identical across proteins.
  Each protein's scaler and coefficients are fitted only from that protein's
  known fitting labels.

“Fitting rows” always means that protein's known-positive and known-negative
rows in the fitting partition: train during the pilot, and train plus validation
during the final refit. Only those rows determine the prevalence score, scaler
parameters and GC-decile cut points.

Convergence is accepted only when `n_iter_ < max_iter` and no
`ConvergenceWarning` was emitted. During validation, a candidate C is eligible
only if every fit for all eight development proteins converges. Ineligible
candidates remain in the report with their failure evidence. Selection stops
only if no candidate C is fully converged for that baseline/width.

The eight development proteins and IDs are frozen:

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

During the development pilot, models fit on **train only** and score
**validation only**. Because the accepted membership and FASTAs are sequential
whole-universe files, their bytes may be hash-verified or streamed. However,
the pilot must not parse test labels, construct or retain test feature vectors,
count test classes, fit on test rows, or emit test scores.

After the nine C values are frozen (three fitted baselines times three widths),
the final command may be explicitly authorized once. It is internally divided
into two transactions. Phase A fits every train-plus-validation model for all
122 proteins and verifies convergence without parsing a test label or building
a test feature. Phase B may open and score test only when every Phase-A model
has been accepted. A Phase-A failure stops the run before test exposure. The
final command may not revise any implementation or parameter.

## 6. Windows

Run every baseline independently at 500, 251 and 101 nt using the accepted
decoded FASTA bound by `manifests/sequence_decode_002b2.json`. No 150-nt window
is introduced. The three widths are reported as a prespecified input-length
comparison; no width is selected using test performance.

## 7. Metrics and summaries

For every protein, width and baseline report:

- known-positive and known-negative counts;
- AUROC as the primary metric, with exact average-rank treatment of ties;
- average precision (AUPRC) as a secondary metric;
- evaluation prevalence;
- convergence status, iterations, runtime and peak memory where available;
- selected C and configuration hash.

The report also carries the accepted split's per-protein imbalance flag. A
flag is disclosed and stratified; it is never used to remove a protein or
change the split.

Macro summaries are unweighted means over the eligible proteins. The primary
comparison is raw per-protein AUROC; baseline-subtracted AUROC is diagnostic
only. Do not choose a method or width from test results.

All baseline-to-baseline and width-to-width differences in Task 003B are
descriptive point estimates. Task 003B must not claim that one baseline or
window is significantly better. Inferential paired comparisons are deferred to
the later component-aware analysis where every method is resampled identically.

Task 003B reports point estimates and sample counts. Component-aware confidence
intervals and paired model differences belong to the later controlled model
comparison, where all methods can be resampled identically.

## 8. GC-matched sensitivity analysis

This is secondary and cannot alter model selection.

For each protein, width and evaluation partition:

1. derive GC-decile cut points from that protein's known-labelled fitting rows
   only, using `numpy.quantile(..., method="linear")` at probabilities
   0, 0.1, ..., 1;
2. place evaluation positives and negatives into those frozen bins;
3. within each bin retain the same number from each class, using SHA-256 order
   of `(seed, sample_id, protein_id, width)` as the deterministic tie-break;
4. evaluate the already-fitted scores on the union of retained rows;
5. report retained counts and the full-set versus matched-set metric change.

Duplicate quantile edges are collapsed. Bins are right-closed, except the first
bin also includes its left endpoint; equivalently, internal edges are assigned
with `numpy.searchsorted(edges, value, side="left")` after removing the outer
endpoints. The exact resulting edges are recorded and bound into the
configuration hash. Bins lacking one class contribute no rows. No replacement
is used. The matched analysis is invalid unless both classes remain and all
retained IDs are a subset of the primary evaluation set.

## 9. Prediction and artifact contract

Ignored row-level prediction files must contain at least:

```text
sample_id,component_id,protein_id,fold,partition,seed,window,config_id,config_hash,label,score
```

Tracked evidence contains no sequences, row-level labels or row-level scores.
It contains configurations, environment lock, input/output hashes, aggregate
metrics, counts, selected C values, runtimes and the explicit boundary showing
whether test authorization occurred.

Expected local output root:

```text
artifacts/task003b_simple_baselines/
```

Expected tracked closure record after the final run:

```text
manifests/task003b_simple_baselines.json
```

## 10. Implementation checkpoints

### 003B-1 — implementation and synthetic proof

- create a dedicated baseline environment specification;
- implement strict label/membership/FASTA reconciliation;
- implement deterministic GC and k-mer features;
- implement prevalence and logistic baselines;
- implement AUROC, average precision and GC matching;
- implement transactional, restart-safe outputs and a hard test-access gate;
- prove behavior on small synthetic fixtures, including unknown-label
  exclusion, ties, reverse-complement-distinct k-mers, sparse 6-mers and
  intentional failures.

No real CSV, accepted FASTA, membership or test row may be opened here.

### 003B-2 — eight-protein validation pilot

- revalidate all accepted inputs;
- extract only train/validation rows for the eight frozen proteins;
- run all four baselines at all three widths;
- select and freeze nine C values from validation AUROC;
- record runtime, peak memory and feature-cache size;
- stop before any test access.

This checkpoint determines whether the full run stays local or needs Darwin.

### 003B-3 — frozen full execution

Requires explicit owner authorization after reviewing the pilot manifest.

- verify that code/config/input hashes equal the accepted pilot;
- refit on train plus validation for all 122 proteins;
- score test once for all four baselines and all three widths;
- run the secondary GC-matched sensitivity analysis;
- reconcile every prediction/count and write the sanitized closure manifest.

## 11. Resource design

- Build one width at a time and release it before the next width.
- 6-mer features must be sparse; never materialize a
  `361,180 × 4,096` dense matrix.
- Feature caches are content-addressed and bound to the FASTA/config hash.
- The pilot records measured disk, memory and runtime; no heavy host is assumed
  in advance.
- A failed or interrupted generation cannot replace prior accepted evidence.

## 12. Stop conditions

Stop without silently changing scope if:

- an input, membership, FASTA or count fails reconciliation;
- any pilot code parses a test label, constructs a test feature vector, counts
  test classes or emits a test score;
- an unknown label is treated as negative;
- the prevalence sanity checks fail;
- the 6-mer representation becomes dense or exceeds the local resource gate;
- no candidate C fully converges for a pilot baseline/width;
- any final Phase-A fit fails to converge (Phase B must remain unstarted);
- primary/repeat pilot scientific decisions or identities differ, or numerical
  differences exceed the frozen reproducibility tolerances below;
- the final command differs from the frozen pilot code/config;
- the full run would exceed measured local resources.

Resource failure authorizes a clean Darwin handoff, not a scientific shortcut.

## 13. Acceptance criteria

Task 003B closes only when:

1. all synthetic tests pass;
2. the pilot is deterministic and test-blind;
3. nine C values are frozen from validation only;
4. the final run uses the accepted components-v2 membership and all 122
   proteins;
5. every known-label count reconciles;
6. prevalence AUROC is exactly 0.5 wherever defined;
7. all prediction rows have stable IDs and configuration hashes;
8. aggregate and per-protein tables reproduce from predictions;
9. the GC-matched set is deterministic and contains only rows from the primary
   evaluation set;
10. the report distinguishes baseline performance from the still-unrun former
    model and competitors.

### Numerical reproducibility clarification

The pinned `liblinear` implementation may stop one iteration earlier or later
and can differ in the final probability digits despite a fixed seed and one
numerical thread. Therefore repeat acceptance does not require byte-identical
floating-point files. It requires exact selected C values, convergence states,
row identities, labels, partitions, components, configuration hashes and test
boundary; metric differences must be at most `5e-6`, and per-row probability
differences at most `1e-4`. Iteration-count differences are reported. These
limits are an acceptance check only: scores are not rounded or changed.

## 14. What comes afterward

Task 004 uses these baselines as reference points while reproducing the former
joint ResCNN and the three core competitors on the same split. Only then can we
make the direct performance comparison requested by the project objective.
