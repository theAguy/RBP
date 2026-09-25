# Task 001 — Coordinate-recovery feasibility

**Status:** closed after the B3B-2 resource stop; sequence-clustering fallback selected
**Phase:** 1
**Suggested branch:** `issue-001-coordinate-feasibility`

## Objective

Determine whether the 500-nt sequences can be assigned reproducible human
genomic coordinates well enough to support locus-grouped train/validation/test
splits. This task is a bounded feasibility study on a deterministic 10,000-row
sample. It does not map the full dataset and does not create model folds.

Coordinates are benchmark metadata. They are not inputs to the submitted model.

## Execution checkpoints

- **Task 001A — pipeline implementation:** implement configuration, sampling,
  decoding, controls, alignment parsing/classification, provenance, and tests.
  Use only tiny fixtures; do not download human references or map the
  feasibility sample.
- **Planning-review checkpoint:** inspect 001A code, tests, and dry-run output.
- **Task 001B — feasibility execution:** only after 001A acceptance, install the
  locked tools on the approved Mac, download/hash references, generate the
  10,000-row sample, run mapping, and produce the feasibility report.

Approval of this parent task does not waive the checkpoint between 001A and
001B.

## Why this task comes next

The original row-level split can place highly overlapping windows from the same
genomic locus in both training and evaluation data. Coordinate grouping is the
preferred way to prevent that leakage. Before downloading and indexing multiple
full references or mapping 361,180 rows, we need evidence that the sequences can
be mapped uniquely and without class-dependent loss.

## Known local constraints

- Dataset: `dataset_K562_multilabel_with_NEGs.csv`, verified SHA-256
  `982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945`.
- Stable sample ID: `row_<zero-based-row-number>`.
- Execution host: the local macOS x86_64 machine containing this repository,
  not Claude's 3-GiB Linux device VM.
- The selected host has 16 GiB physical RAM, 4 physical/8 logical processors,
  and approximately 156 GiB free at planning time.
- No human reference FASTA or aligner is currently present in the repository.
- `samtools 1.11` is installed globally; minimap2, BWA, Bowtie2, STAR, HISAT2,
  BEDTools, and SeqKit are not.
- A Conda-compatible environment manager is available. Installation and
  reference retrieval must be scripted and recorded, not performed implicitly.

## Inputs

1. The primary CSV above.
2. `manifests/dataset_audit.json`, SHA-256
   `e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c`.
3. `configs/proteins.tsv`, SHA-256
   `374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9`.
4. Two official, pinned human references representing hg38/GRCh38 and
   hg19/GRCh37. The executor must record source URLs, assembly identifiers,
   contig policy, byte sizes, and SHA-256 hashes before indexing.
5. BWA 0.7.19 for primary contiguous mapping, minimap2 2.31 for the
   splice-aware diagnostic, and SeqKit 2.13.0 for exact-substring validation.
   The exact resolved environment and binary hashes must be exported.

Use matched primary-assembly scope for both builds: assembled chromosomes,
mitochondrial sequence, unlocalized scaffolds, and unplaced scaffolds. Exclude
alternate haplotypes, patches, decoys, and separate HLA contigs. Record every
included contig and its category. If an official source cannot provide
comparable scope for both builds, stop for review rather than mixing policies.

## Deterministic sample

Create exactly 10,000 distinct sample IDs with seed `20260916` and record one
of three sampling strata for every row:

1. **Representative stratum:** select 5,000 rows by stable hash rank over all
   dataset rows without inspecting labels, sequence, GC content, or mapping.
   This stratum alone supplies the headline mapping-rate estimates.
2. **Quota supplement:** for each of the 122 proteins, add rows until the
   combined sample contains at least 20 known positives and 20 known negatives.
   Select additions using a stable hash rank of `seed + sample_id + protein_id
   + class`; a row may satisfy several quotas. In the worst case this adds
   4,880 rows, so it cannot overflow the 10,000-row target.
3. **Filler stratum:** fill any remaining positions by stable hash rank over all
   unselected rows without using labels or sequence properties.

Report unweighted results for all three strata, but never describe the enriched
10,000-row aggregate as population-representative. The proceed/fallback gate is
computed on the 5,000-row representative stratum. The quota supplement is for
gross per-protein failure screening.

Write the ordered sample IDs, their source row numbers, and all known labels to
`artifacts/coordinate_feasibility/sample_ids.tsv`. Record its SHA-256 hash. Unit
tests must verify determinism, uniqueness, exact size, stratum membership, and
quota coverage on a small fixture.

## Required implementation

### 1. Decode and validate sequences

- Decode each selected 2,000-bit one-hot string into exactly 500 bases in
  A/C/G/T order.
- Reject invalid length, non-binary characters, or positions that are not
  exactly one-hot; never repair them silently.
- Write FASTA headers using only canonical sample IDs.
- Confirm that re-encoding every decoded sequence reproduces the source field.

### 2. Add a tagged negative control

Generate 100 deterministic dinucleotide-preserving shuffles from rows in the
representative stratum. Require each shuffled sequence to differ from its
source; tag headers as controls and keep them outside the 10,000 biological
rows. Controls are excluded from every mapping and retention rate. Any control
classified as usable unique triggers manual inspection for pipeline
misconfiguration; it is not silently discarded.

### 3. Run two mapping modes against each build

Run and preserve all plausible secondary alignments:

- **Primary contiguous mode:** BWA-MEM, starting from `bwa mem -a -Y -t N`.
  BWA-MEM's documented sequence-length range includes 500 nt and `-a` retains
  secondary alignments.
- **Splice-aware diagnostic:** minimap2 `splice:sr`, starting from
  `minimap2 -ax splice:sr --secondary=yes -N 20 --MD --eqx -t N`.

Both strands must be allowed. Commands, thread count, wall time, peak memory,
tool versions, index parameters, and output hashes must be recorded. The mapper
configuration must emit base-level alignment information and enough secondary
hits to identify multimapping; default suppression of secondary hits is not
acceptable for this study.

Use at most four mapping/indexing threads on the 16-GiB host and process one
reference build at a time. Reference FASTAs may coexist, but BWA and minimap2
indices for the two builds must be built and removed sequentially so peak new
disk use remains below 30 GiB. Indices are reproducible caches; their commands
and hashes must be recorded before removal.

The splice-aware result is a rescue/diagnostic result. It must not override a
high-confidence contiguous mapping merely because its alignment score differs
under another algorithm.

### 4. Validate exact uniqueness independently

For every sequence that the primary mapper would call a perfect unique match,
use SeqKit exact substring search with its FM-index mode against the same FASTA,
on both strands. `exact_unique` requires exactly one distinct genomic
occurrence by this independent check. Report discordance between BWA-MEM and
the exact matcher. If checking every candidate exceeds the approved resource
limits, stop for review; do not silently validate only a favorable subset.

### 5. Classify mappings

Compute query coverage and identity from the actual alignment operations, not
from MAPQ alone. Collapse supplementary blocks into one candidate locus only
when they are collinear on the same chromosome and strand.

Classify every sample/build in the primary contiguous mode into exactly one
category:

- `exact_unique`: 100% query coverage and identity at exactly one genomic locus
  according to both BWA-MEM and the independent exact-substring search;
- `high_conf_unique`: best alignment has query coverage at least 98% and
  identity at least 99%, with no plausible distinct secondary locus;
- `ambiguous`: at least one quality-passing alignment exists, but the unique
  criteria fail because of mapping confidence or a near-tied distinct locus;
- `low_quality`: mapped, but below the coverage or identity thresholds;
- `unmapped`: no reported alignment.

For the primary classifier, a **plausible distinct secondary locus** has at
least 90% query coverage and at least 95% identity after collinear blocks are
combined. This definition is shared across tools and does not depend on their
scoring matrices. MAPQ remains a reported diagnostic, not a classification
criterion.

`exact_unique` is a subset of usable unique mappings; each row must receive only
one terminal category. Retain best and second-best alignment evidence so the
classification is auditable. Persist strand and every aligned block. Report
spliced mappings separately, including the number of aligned blocks, intron
lengths, and whether junctions use canonical splice motifs.

As a secondary, tool-specific sensitivity analysis, show results when a
secondary is considered near-tied at 2%, 5%, and 10% of the best alignment
score. Never compare raw score gaps across BWA-MEM and minimap2.

Classify the splice-aware diagnostic separately as `spliced_unique`,
`spliced_ambiguous`, `unspliced_unique`, `unspliced_ambiguous`, `low_quality`,
or `unmapped`. A spliced call must contain at least two collinear aligned blocks
separated by an intron operation. The same coverage, identity, and plausible
secondary thresholds apply, but `exact_unique` is not used for a spliced
alignment because it cannot be verified by contiguous substring search.

For gate calculations, a row is **usable unique** if it is `exact_unique` or
`high_conf_unique` in primary contiguous mode, or—only when the primary mode is
not usable—`spliced_unique` in the diagnostic mode.

### 6. Compare builds without outcome leakage

Do not use model performance, protein identity, or positive/negative retention
to choose the reference build. Compare builds first using label-blind mapping
criteria:

1. usable unique rate under the primary-plus-splice-rescue definition above;
2. exact unique rate;
3. ambiguous and unmapped rates;
4. coverage and identity distributions;
5. number of sequences whose chosen locus changes between builds;
6. number of distinct mapped loci and rows per locus;
7. contiguous-only, splice-rescued, and still-unmapped rates;
8. forward/reverse-strand counts and whether sequences appear strand-normalized.

Use protein/class labels only after that comparison to audit differential
retention. If the builds are within one percentage point in usable unique rate
and neither clearly dominates the quality distributions, report the build
choice as unresolved rather than choosing opportunistically.

Prespecified expectation: if the 500-nt windows were extracted verbatim from
one build, that build should have a conspicuously higher exact-unique rate. If
both builds instead have low exact-unique but high near-exact unique rates,
treat that as evidence of an untested patch-level or transcript-derived source,
not immediate evidence that coordinates are infeasible.

### 7. Audit possible selection bias

For each build and mapping mode, report usable retention separately for:

- known positives and known negatives overall;
- every protein and class;
- GC-content deciles;
- low-complexity deciles, using a declared sequence-only measure;
- repeat/contig category when the selected reference supplies the necessary
  metadata.

Because rows may have labels for more than one protein, protein/class retention
is calculated over label observations, not by forcing each row into one class.
Report the overall positive-minus-negative retention gap and the distribution
of per-protein gaps. At 20 observations per class, per-protein estimates are a
gross-failure screen only. Define a severe alert as either class retaining
fewer than 50% of its sampled observations or an absolute positive/negative
retention gap of at least 40 percentage points. Moderate per-protein gaps are
deferred to full mapping. Include binomial confidence intervals, but do not run
comparative inferential tests on the feasibility sample.

## Required outputs

Commit small code, tests, configuration, manifests, and reports. Do not commit
reference FASTAs, indices, SAM/BAM/PAF files, or the decoded 10,000-sequence
FASTA to ordinary Git.

- `src/rbpbench/coordinates/sample.py`
- `src/rbpbench/coordinates/decode.py`
- `src/rbpbench/coordinates/summarize.py`
- focused unit tests and a tiny fixture
- a frozen task configuration with all thresholds and the random seed
- an environment lock/export containing exact versions
- reference and generated-artifact manifests containing hashes and sizes
- `artifacts/coordinate_feasibility/mappings.tsv.gz`, with sample/control ID,
  stratum, build, mode, category, chromosome, 0-based half-open start/end,
  strand, block count, block sizes/starts, coverage, identity, MAPQ, alignment
  score, and best-secondary evidence
- `artifacts/coordinate_feasibility/report.json`
- `artifacts/coordinate_feasibility/report.md`
- a one-command, restart-safe runner or documented workflow

The Markdown report must contain a recommendation for Phase 2 with one of:

- `proceed_with_coordinates`;
- `revise_and_repeat_feasibility`;
- `use_sequence_clustering_fallback`.

## Acceptance checks

- The sample contains exactly 10,000 unique canonical IDs and satisfies every
  protein/class quota; the representative stratum contains exactly 5,000 IDs.
- Exactly 100 distinct tagged controls are generated and excluded from rates.
- Sequence decoding passes round-trip validation for all selected rows.
- References, indices, environment, commands, and generated artifacts have
  recorded provenance and hashes.
- All four build/mode combinations complete, or an explicit stop condition is
  documented.
- Every sample has exactly one mapping category per build/mode.
- Every usable mapping has strand and auditable block coordinates, and every
  primary exact-unique call is verified by exact-substring search.
- Summary counts reconcile to 10,000 and label-observation counts reconcile to
  the sampled labels.
- Unique/ambiguous/unmapped rates and mapping-quality distributions are shown
  for both builds.
- Retention is shown overall, by protein/class, and by GC/low-complexity strata.
- Re-running the workflow from the same inputs reproduces sampled IDs and
  summary tables byte-for-byte, apart from explicitly isolated timing fields.
- Existing and new unit tests pass.

## Decision guide for the Phase 1 gate

These are review triggers, not automatic scientific truths:

- **Proceed candidate:** in the 5,000-row representative stratum, at least 80%
  usable unique mappings and overall absolute positive/negative retention gap
  at most 5 percentage points, with no severe per-protein alert under the
  gross-failure definition above.
- **Manual review:** 60–80% usable unique mappings, build disagreement, or a
  class-retention gap above 5 points. A severe per-protein alert also requires
  manual review but cannot by itself estimate a moderate bias precisely.
- **Third-reference review:** both builds have exact-unique rate below 50% but
  usable high-confidence rate at least 80%. Investigate assembly patch level or
  transcript-derived provenance before invoking the clustering fallback.
- **Fallback candidate:** below 60% usable unique mappings for both builds after
  the pre-approved splice-aware diagnostic.

The final decision is made from the full report. It is not encoded as a script
that silently advances the project.

## Stop conditions

Stop and request review if any of the following occurs:

- a reference cannot be identified and hash-verified unambiguously;
- comparable reference scope cannot be obtained for both builds;
- installing the pinned tools requires changing the host environment rather
  than creating an isolated project environment;
- the selected execution host has less than 16 GiB physical RAM, or indexing
  twice terminates because of memory pressure;
- expected new disk use exceeds 30 GiB or free disk would fall below 80 GiB;
- sample quotas cannot be satisfied or sequence validation fails;
- secondary alignments or base-level operations cannot be retained;
- exact-substring validation cannot be completed within the approved resource
  limits;
- a mapping mode fails twice for the same documented reason;
- completing the task would require full-dataset mapping, model training, or a
  scientific threshold not specified here.

Do not upload the dataset or decoded sequences to a web service.

## Out of scope

- Mapping all 361,180 rows.
- Creating or freezing train/validation/test folds.
- Training any predictor or baseline.
- Selecting mapping parameters using downstream AUROC/AUPRC.
- Dropping ambiguous/unmapped rows from the benchmark.
- Adding coordinates as model features.
- Comparing competitor implementations.

## Reviewer decision

- [x] Second reviewer completed review with required changes.
- [x] Planning reviewer reconciled all required changes and documented its
      decisions.
- [x] Project owners approve tool installation, reference downloads, and the
      30 GiB disk ceiling.
- [x] Executor is authorized to start Task 001A once the Git baseline exists.
