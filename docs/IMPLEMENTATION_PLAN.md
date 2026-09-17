# Authoritative implementation plan

## Objective

Compare the former teammate's joint 122-protein residual CNN with strong
published methods on identical, leakage-safe data. The project must distinguish
predictive performance from the effects of joint training, loss design, and
input-window length.

## What “joint model” means

A joint model has one shared sequence encoder and 122 output scores, one for
each RBP. An example labelled for one protein updates the shared encoder, so
representations learned from data-rich proteins can help data-poor proteins.
The alternative trains 122 independent encoders, which share no information.

## Competitor scope

All relevant methods are logged in [`COMPETITORS.md`](COMPETITORS.md). The first
three published competitors are:

1. **DeepRiPe** — the central multitask comparator.
2. **Multi-resBind** — the closest conceptual comparator: residual and
   multi-label.
3. **PrismNet-seq** — an established per-protein sequence-only comparator.

RNAProt is the first optional addition if the core comparison is stable and the
official environment is inexpensive to run. RBPNet is not a headline method
because its native target is a nucleotide-level count profile, not binary
binding.

## Loss policy

The submitted notebook contains two unusual choices: known positives have loss
weight 15, and unknown entries receive a weak target of zero. They must not be
silently bundled into the architecture comparison.

| ID | Architecture/training | Positive weight | Unknown penalty | Purpose |
|---|---|---:|---:|---|
| `submitted` | joint in-house | 15 | 1 | Reproduce the submitted recipe |
| `submitted_no_unknown` | joint in-house | 15 | 0 | Isolate the unknown penalty |
| `joint_standard` | joint in-house | 1 | 0 | Clean joint-training comparison |
| `single_standard` | per-protein in-house | 1 | 0 | Clean single-task comparison |

The controlled architecture comparison uses the same masked, unweighted binary
cross-entropy (`positive_weight = 1`, `unknown_penalty = 0`) for
`joint_standard`, `single_standard`, DeepRiPe, Multi-resBind, and PrismNet-seq.
Published/native loss recipes may be reported separately, but never described as
an architecture-only comparison.

The development pilot first checks whether changing positive weight from 15 to
1 materially changes results. This adds one inexpensive joint-model run and
prevents an undocumented weight from driving the main conclusion.

## Coordinate policy

Coordinates are not inputs to the submitted predictor. They are benchmark
metadata used to prevent overlapping genomic loci from appearing in training
and testing, and to add optional genomic-context analyses.

Coordinates will be recovered from the 500-nt sequences by testing likely human
reference builds and splice-aware/transcript mappings. The mapping report must
include unique, ambiguous, and unmapped rates; retention by protein and class;
GC/repeat differences in quarantined rows; and handling of splice junctions.

Mapped rows are grouped by overlapping aligned genomic blocks. A group is never
split across train, validation, and test. Sequence-overlap auditing independently
verifies that coordinate grouping removed leakage. If coordinate recovery is
not adequate, sequence clustering is the documented fallback.

## Phases and gates

### Phase 0 — repository and immutable inputs

- Create the reproducible package, configuration, tests, and documentation.
- Record SHA-256 hashes, row counts, encodings, and label conventions.
- Keep raw data and checkpoints out of ordinary Git.

**Gate:** a new collaborator can run tests and reproduce the data audit.

### Phase 1 — coordinate feasibility

- Decode sequences and align a representative subset to hg38 and hg19.
- Test genomic, transcript, and splice-aware alignment where necessary.
- Report mapping quality and estimate full-run resources.

**Gate:** agree on reference build, mapper, quality thresholds, and fallback.

### Phase 2 — full mapping and leakage-safe folds

- Map all sequences and produce the retention report.
- Build locus components from aligned genomic blocks.
- Balance separate positive and known-negative counts across folds.
- Freeze train/validation/test membership before model results are inspected.

**Gate:** no cross-fold locus overlap; sequence audit passes; fold balance and
eligible-protein counts are accepted.

### Phase 3 — trivial baselines

- Random prediction.
- GC-content logistic regression.
- 3-mer logistic regression.
- 6-mer logistic regression.
- A frozen GC-matched-negative sensitivity set per protein and fold.

Every fitted baseline uses training data only. Features are computed on the same
window as the model being evaluated.

**Gate:** baseline code, predictions, and summaries reproduce from one command.

### Phase 4 — development pilot

Development proteins: TARDBP, ELAVL1, U2AF2, PTBP1, HNRNPC, PUM2, QKI, and
RBFOX2. Joint models still train all 122 outputs; only these eight results may
guide implementation decisions.

- Smoke-test every core architecture.
- Verify loss components, output alignment, checkpointing, and early stopping.
- Measure runtime, memory, learning curves, and seed variability.
- Compare positive weights 15 and 1 for the in-house joint model.

**Gate:** fidelity checks and a measured compute budget are accepted.

### Phase 5 — controlled core comparison

At a common sequence window and common masked loss:

- joint versus single-task in-house model;
- in-house joint model versus DeepRiPe;
- in-house joint model versus Multi-resBind;
- in-house single-task model versus PrismNet-seq.

**Gate:** all runs have complete configuration records and sample-aligned
predictions; no test-set tuning occurred.

### Phase 6 — submitted and native operating points

- Evaluate the submitted recipe at 500 nt.
- Evaluate competitors at their declared native or adapted operating points.
- Run the in-house window comparison at 101, 251, and 500 nt.
- Run GC-matched and biological-validity diagnostics.

### Phase 7 — locked analysis and report

- Per-protein AUROC and paired differences.
- Confidence intervals with the correct locus/protein resampling units.
- Calibration analysis for loss ablations.
- Runtime, parameter, storage, and model-count comparisons.
- Explicit qualification that competitors are retrained implementations.

If gains disappear after leakage removal, the report becomes a benchmark and
reproducibility study rather than forcing a positive model claim.

## Execution workflow

For each substantial task:

1. The planning reviewer writes a bounded GitHub issue with inputs, outputs,
   acceptance checks, and stop conditions.
2. A second reviewer critiques the issue before execution.
3. The project owners approve material scientific or resource changes.
4. The executor implements on a feature branch without changing scope silently.
5. A pull request contains code, tests, artifacts, and a short run report.
6. The planning reviewer accepts, requests revision, or stops the phase.
