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

## 2026-09-17 — Task 001A acceptance-blocker corrections (round two)

- Planning review found seven end-to-end acceptance blockers after the first
  round of corrections: preflight was not a hard, binding prerequisite for
  real alignment/exact-match; `--dry-run` did not guarantee no external
  subprocess could execute and could poison stage-completion state; mapping
  rows were built from IDs present in SAM output rather than the complete
  expected biological-and-control universe (silently dropping queries
  unmapped by both tools); multiple collinear-but-intron-free supplementary
  blocks were misclassified as spliced; reverse-strand split-mapping
  coordinates could serialize with start > end; the two-build combined
  report/output path required before Task 001B did not exist; and
  provenance (binary hashes, elapsed time, peak memory, output hashes,
  reference metadata) was not connected to the runner.
- All seven were fixed as implementation/robustness corrections to the
  already-approved 001A scope: no scientific threshold, contig policy,
  mapper selection, or sampling design changed.
- `stage_align`/`stage_exact_match` now call `run_preflight` fresh,
  immediately before any subprocess, bound to the exact reference/reads
  about to be used; a declared `--host-role=approved_mac` alone is never
  sufficient. `--dry-run` is checked first, before any other authorization
  logic, in both stages.
- The runner now processes `hg38`/`hg19` (or whichever builds `--build`
  names) sequentially into collision-safe `<output-dir>/<build>/`
  subdirectories, followed by a `combined_report` stage
  (`rbpbench.coordinates.summaries` + `report.build_combined_report`) that
  is the one report a human reviewer reads to set the Phase 2
  recommendation — still never computed automatically.
- `CandidateLocus` now distinguishes real `'N'`-op intron evidence
  (`intron_lengths`) from blocks merely merged by collinearity, and supports
  an optional reference-lookup canonical-junction diagnostic
  (`rbpbench.coordinates.reference`).
