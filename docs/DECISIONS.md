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

## 2026-09-22 — Task 001A acceptance-blocker corrections (round four)

- Planning review found two narrowly-scoped correctness issues after round
  three: `bwa_perfect_unique` meant only "best BWA locus is 100%
  coverage/identity", so a read with two perfect BWA loci (correctly
  classified `ambiguous`) was still marked perfect-unique and counted as
  BWA-vs-SeqKit discordant; and reference-manifest content was not part of
  restart fingerprints, so a manifest-only edit (the FASTA itself
  unchanged) did not invalidate/revalidate `align`, and a stale manifest
  could be attributed to reports it did not actually produce.
- `alignment.has_plausible_distinct_secondary` is now a shared, public
  helper (factored out of `classify_primary`/`classify_splice`).
  `runner.build_mapping_rows` renamed the diagnostic-only flag to
  `bwa_best_is_perfect` and added the correctly-computed
  `bwa_perfect_unique_candidate` (best perfect AND no plausible distinct
  secondary), which `summaries.exact_match_discordance` now keys off.
- `align_fingerprint`/`preflight_fingerprint` now include each build's
  reference-manifest file hash, so any manifest change (invalid or purely
  descriptive, e.g. `contig_categories`) invalidates and forces
  `align`/`exact_match`/`report`/`combined_report` to revalidate/rerun via
  the existing fingerprint chain. `align.json`/`exact_match.json` now
  persist the exact manifest dict they ran under; `provenance.json` and
  `combined_report`'s contig-category retention read that persisted
  manifest (never the CLI's current `--reference-manifest`) so a build
  whose align stage was not re-attempted this invocation keeps attributing
  its old manifest, never a newer one it was never validated/re-run
  against.

## 2026-09-23 — Task 001B second-review reconciliation

- All twelve required second-review findings were accepted. They concern
  execution safety and provenance at the Task 001A/001B seam; no sampling,
  classification, retention, or Phase 1 scientific threshold changed.
- Real mapping is single-build-only. Mapper indices live under exact
  build-specific disposable directories; minimap2 uses a verified one-part
  `splice:sr` index (`k=15`, `w=5`, non-HPC, `-I 8G`), and external-tool
  stderr is retained and hashed.
- `hg38` and `hg19` are internal study labels for the pinned RefSeq
  GRCh38.p14 and GRCh37.p13 primary assemblies, not UCSC reference packages.
  The GRCh37 mitochondrial difference is an accepted, reportable deviation.
- The 30-GiB ceiling is enforced through a baseline, projected artifact
  ledger, per-step measurements, and output stops. Expected input hashes are
  compared before data access; successful checkpoint evidence is protected
  against destructive planning or failed retries.
- Only checkpoint B1 is authorized next. Human references, the real CSV, and
  real mapping remain prohibited until their later checkpoint gates are
  separately approved.

## 2026-09-24 — B3B-1 NCBI checksum identity

- The first real GRCh38.p14 checksum-listing request exposed an operational
  defect: NCBI legitimately reuses generic basenames in different
  `assembly_structure` subdirectories, while the parser collapsed every
  entry to its basename and falsely reported conflicts.
- Checksum-listing file identity is therefore the normalized relative path,
  not the basename. Duplicate or conflicting entries remain hard failures
  when the same exact normalized path repeats; distinct paths that share a
  basename are valid and remain distinct.
- The two frozen study files must be found at the exact root-relative paths
  derived from their source URLs relative to the checksum-listing directory.
  A nested same-basename entry cannot satisfy that requirement.
- This is an operational correctness correction only. No source URL, frozen
  MD5, byte size, assembly, contig policy, sampling rule, scientific
  threshold, or resource ceiling changes.

## 2026-09-24 — B3B-1 RefSeq derivation universe

- The accepted GRCh38.p14 download is valid. Its assembly report explicitly
  says that the RefSeq and GenBank assemblies are not identical. Three rows
  that otherwise match the primary-assembly role policy have GenBank
  accessions but no RefSeq accession: `KI270721.1` (100,316 bases),
  `KI270734.1` (165,050 bases), and `KI270752.1` (27,745 bases). As expected
  for the pinned `GCF_...` RefSeq genomic package, none appears in its FASTA.
- The study will keep the pinned RefSeq source and will not silently switch
  to the GenBank assembly or construct a hybrid reference. The derived
  reference universe is the configured category policy intersected with the
  configured source accession namespace. For the current RefSeq sources,
  category-eligible rows without a usable RefSeq accession are explicit
  source-unrepresented exclusions.
- For GRCh38.p14 this yields 191 derived contigs: 24 chromosomes, one
  mitochondrion, 40 unlocalized scaffolds, and 126 unplaced scaffolds. The
  three exclusions total 293,111 bases and must be recorded in the reference
  manifest and sanitized checkpoint evidence.
- This is a recorded scientific policy refinement forced by the real primary
  source, not evidence of a corrupt download. Source URLs, checksums, byte
  sizes, assembly identity, role/category rules, mapper parameters, sampling,
  thresholds, and resource ceilings remain unchanged. A selected RefSeq
  accession missing from the RefSeq FASTA is still a hard stop.

## 2026-09-25 — Freeze scope and resume scientific execution

- Correction `5f5308d` is accepted specifically for the checked-in frozen
  production policy: all three Primary Assembly roles are included, the
  mitochondrial assembled molecule is included, and the accession namespace
  is RefSeq-only. Under those exact values, the implementation's fixed
  category behavior and configured values coincide, and the real hg38 output
  is expected to contain the decided 191 contigs.
- General support for changing the role list or mitochondrial flag is
  deferred. Those fields must not be changed for B3-B7 without reopening the
  implementation review. The accepted manifest must record the frozen values
  and the real derivation must satisfy the exact contig/category/exclusion
  checks; otherwise execution stops.
- The CLI validates the policy before production data access. Additional
  validation for direct internal `stage_derive()` calls and a separate derive
  `generation_digest` are useful engineering improvements but are not needed
  to answer this project's scientific question; existing reference/manifest
  hashes, restart fingerprints, and repeat-derivation equality remain the
  required evidence.
- The follow-up handoff at `676dcee` is superseded. Work returns to the
  checkpoint sequence: complete B3B-1 derivation and deterministic repeat,
  review once, then proceed to B3B-2 indexing/probe if accepted.

## 2026-09-25 — Defer coordinates and activate sequence clustering

- The guarded B3B-2 hg38 attempt completed the BWA index, but the operating
  system killed minimap2 during minimizer collection for the required
  single-part `splice:sr` index on the 16-GiB host. The accepted index record
  remained unchanged and no probe or mapping ran.
- A standard Google Colab runtime supplied only 12.7 GiB RAM. A 24-GiB Mac is
  not considered sufficient margin to justify another multi-hour attempt.
- The project will not tune mapper parameters, implement multipart indexing,
  purchase cloud memory, or let this optional metadata analysis delay the
  central model comparison. Task 001B is closed as resource-infeasible on the
  available hosts; this is not a biological mapping result.
- The accepted hg38 source and deterministic derived reference remain valid.
  The unaccepted 5,424,083,332-byte index candidate may be deleted only after
  its file hashes and sizes are committed in the stop manifest.
- The prespecified leakage-control fallback is now active: group highly
  similar sequences before assigning train/validation/test partitions. Model
  predictions and test performance may not influence grouping or assignment.

## 2026-09-25 — Task 002 split design

- Build label-blind similarity components from the union of full 500-nt and
  centered 251/101-nt representations, matching every planned model width.
- Freeze 90% true sequence identity with 80% bidirectional coverage for 500 nt
  and 95% for 251/101 nt. Exact and reverse-complement duplicates at every
  width are always unioned independently of the external clustering output.
- Use MMseqs2 18.8cc5c with an explicit nucleotide database, true identity,
  masking disabled, sensitivity 7.5, single-step connected components, and
  explicit nucleotide/both-strand settings for the later audit search.
- Assign whole components once to locked 70/15/15 train/validation/test
  partitions. Labels may balance already-frozen components but cannot define or
  split them; model results cannot influence either grouping or assignment.
- Execute as three reviewed checkpoints: fixture-only implementation, real
  grouping/component review, then partition assignment and audit.
