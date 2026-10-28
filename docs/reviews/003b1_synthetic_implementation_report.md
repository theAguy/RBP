# Task 003B-1 synthetic implementation report

**Status:** implementation complete; real-data pilot not started

## Implemented

- strict frozen TOML configuration and semantic hash;
- strict unsigned-positive/signed-negative/unknown label handling;
- canonical membership parsing and whole-component validation;
- pilot partition filtering before label interpretation;
- GC, ordered 3-mer and sparse ordered 6-mer features;
- exact tie-aware AUROC and average precision;
- training-prevalence and frozen logistic-regression fits;
- convergence-aware C eligibility and deterministic tie-breaking;
- training-bound deterministic GC matching;
- explicit test-access authorization helper;
- transactional generation selection, artifact revalidation and failure
  recovery;
- a one-command pilot implementation with row-aligned, hash-bound predictions;
- a CLI that performs dry-run/preflight without data access and refuses final
  execution before both authorization and an accepted pilot.

## Synthetic evidence

The focused suite contains 28 tests. It includes a complete miniature pilot at
all three widths and all eight development-protein IDs, followed by a forced
repeat. `summary.json`, `metrics.json` and `predictions.tsv.gz` are byte-for-byte
identical between repeats.

An intentionally malformed label is placed in the synthetic test partition.
The pilot succeeds without parsing it, and no test sample appears in the
predictions. Prevalence AUROC is exactly 0.5 for every protein/window cell.

Other regressions cover unknown-label exclusion, component splitting, FASTA
ID/width reconciliation, reverse-complement-distinct ordered k-mers, sparse
6-mers, average-rank ties, non-converged candidate exclusion, right-closed GC
bins, deterministic matched sampling, unauthorized test scoring, changed
artifact evidence and injected selection-write failure.
It also proves that the production CLI refuses synthetic or drifted input
hashes before starting a pilot.

## Environment

The dedicated local environment is `.venv-003b-baselines` (ignored by Git),
Python 3.12.13 with NumPy 2.0.2, SciPy 1.16.1 and scikit-learn 1.6.1. Exact
resolved packages are recorded in
`manifests/task003b_environment_003b1.lock.txt`.

## Boundary

No real CSV, accepted FASTA, final membership, test label, model or network
resource was accessed by the implementation tests. Task 003B-2 is the next
checkpoint: the eight-protein train-to-validation pilot on accepted real data.
