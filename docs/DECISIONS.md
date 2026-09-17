# Decision log

## 2026-09-16 — Project governance

- One planning/review owner maintains the authoritative plan.
- A second reviewer is consulted before large or scientifically consequential
  tasks.
- Execution occurs through bounded GitHub issues and reviewed pull requests.
- The project is implemented in phases; the full training grid is not launched
  as one job.

## 2026-09-16 — Competitor scope

- Core published competitors: DeepRiPe, Multi-resBind, PrismNet-seq.
- RNAProt is the first optional addition.
- RBPNet is exploratory because its native supervision is a count profile.
- All other relevant methods remain visible in `docs/COMPETITORS.md`.

## 2026-09-16 — Coordinates

- Recover genomic coordinates even though the submitted predictor does not use
  them.
- Primary purpose: locus-grouped splitting and leakage control.
- Secondary purpose: genomic-context and native-input analyses.

## 2026-09-16 — Loss comparisons

- Preserve the submitted positive weight and unknown penalty as one pipeline.
- Isolate the unknown penalty and positive weight in separate ablations.
- Use a common masked loss for controlled architecture and joint-training
  comparisons.

## 2026-09-16 — Task 001 second-review reconciliation

- Coordinate feasibility executes on the local 16-GiB macOS host, not the
  constrained device VM.
- Headline mapping rates use a 5,000-row label-blind representative stratum;
  quota-enriched rows are used only for gross per-protein diagnostics.
- BWA-MEM is the primary contiguous mapper, minimap2 `splice:sr` is the
  splice-aware diagnostic, and SeqKit exact search verifies exact uniqueness.
- Matched primary-assembly references include chromosomes, mitochondrial,
  unlocalized, and unplaced sequence but exclude alternate haplotypes, patches,
  decoys, and separate HLA contigs.
- Build choice remains label-blind. Low exact matching in both builds with high
  near-exact mapping triggers provenance/third-reference review before the
  sequence-clustering fallback.

## 2026-09-16 — Task 001 resource authorization and execution split

- Project owners approved isolated installation of the pinned mapping tools,
  official hg38/hg19 reference downloads, peak new disk use up to 30 GiB, and
  at most four mapping/indexing threads on the local 16-GiB Mac.
- Task 001 is divided into 001A implementation/fixture testing and 001B real
  feasibility execution, with planning review required between them.
- Claude is authorized as executor for 001A only. The constrained Claude Linux
  environment must not perform human-genome indexing or mapping.

## 2026-09-17 — Task 001A planning-review corrections

- Planning review (see `docs/reviews/001_coordinate_recovery_reconciliation.md`
  history and the requesting message) found the initial 001A implementation
  unfit on: BWA-MEM plain-CIGAR identity, AS/MAPQ/primary-secondary-
  supplementary preservation, real mapping capability, restart persistence,
  fail-closed preflight, SeqKit double-strand counting, reconciliation
  strength, quota-failure handling, and the environment specification.
- The prior "environment lock" documenting an unresolved Python 3.9.17 vs.
  `requires-python >= 3.10` mismatch is superseded by
  `requirements-001a.txt`, verified against Python 3.11.7.
- Corrections are implementation/robustness fixes to the already-approved
  001A scope, not new scientific-scope changes; no threshold, contig policy,
  mapper selection, or sampling design changed.
