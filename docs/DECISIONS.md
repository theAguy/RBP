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

## 2026-09-22 — Task 001A acceptance-blocker corrections (round three)

- Planning review found four remaining end-to-end blockers after round two:
  a planning-only run could still permanently block a later, differently-
  authorized real run in the same output directory (and a changed CSV/
  config/reference was not detected either); the canonical-junction
  reference lookup still loaded the whole FASTA into memory; several
  scientific-report tables leaked controls into scientific denominators,
  collapsed mode-specific retention into one rescue-aware number, absolute-
  valued a signed retention gap, never reported BWA-vs-SeqKit discordance,
  and compared raw hg19/hg38 coordinates as if they were equivalent; and
  provenance did not hash several declared inputs/generated artifacts,
  did not require or validate reference manifests, and did not bind itself
  to restart state. All four were fixed as implementation/robustness
  corrections; no scientific threshold, contig policy, mapper selection, or
  sampling design changed.
- Restart-state validity is now fingerprint-based
  (`state.json`'s `stage_fingerprints`): every stage's skip/re-run decision
  compares a fingerprint of its current declared inputs/config/reference/
  authorization against the fingerprint recorded when it last completed,
  rather than trusting "already in completed_stages" alone.
- `rbpbench.coordinates.reference` gained `IndexedFastaReader` and
  `prepare_reference_index` (a samtools-`faidx`-style sequential index
  preparation/checking workflow); `stage_report` uses these for the
  canonical-junction lookup instead of loading the reference whole.
- `rbpbench.coordinates.summaries` now excludes controls from every
  scientific mapping-quality/strand-locus/near-tied/retention/build-
  comparison table (control_alerts remains the one control-including
  table), reports retention separately for combined/primary/splice-only
  "usable" definitions, preserves signed retention gaps, reports BWA-vs-
  SeqKit exact-match discordance, and compares builds by terminal-category
  change rather than raw coordinates (no liftover is performed).
- Reference manifests are now required and validated
  (`rbpbench.coordinates.manifest.validate_reference_manifest`) before real
  mapping/exact-match; `provenance.json` now hashes the dataset audit,
  `configs/proteins.tsv`, and every generated artifact, includes index
  provenance, and is bound to `state["stage_fingerprints"]`.
