# Task 001B — Coordinate-feasibility execution

**Status:** second review reconciled; B1 readiness work may begin only from its
bounded executor handoff
**Parent:** `001_coordinate_recovery_feasibility.md`
**Depends on:** accepted Task 001A, merged as `ad36864`
**Branch:** `issue-001b-coordinate-execution`

## Objective

Run the reviewed coordinate-feasibility study on the real 10,000-row sample
and two matched human references, one build at a time, then return the combined
mapping/retention report for a human Phase 1 decision.

This task does not map the full 361,180-row dataset, create model folds, train a
model, or compare competitors. Coordinates remain benchmark metadata rather
than inputs to the submitted model.

## Governance and execution boundary

- Claude reviews this plan before receiving an executor handoff.
- The planning reviewer approves each checkpoint below before the next one.
- Large inputs and generated mapping files remain outside ordinary Git.
- No reference download, genome indexing, or real mapping begins during plan
  review.
- Scientific constants in `configs/coordinate_feasibility.toml` are frozen.
  Any proposed change stops execution and requires a recorded decision.
- The labels `hg38` and `hg19` are pipeline study labels for the RefSeq
  GRCh38.p14 and GRCh37.p13 primary assemblies specified below. They do not
  mean that UCSC hg38/hg19 FASTA content or naming is being used.
- Real work runs only on the approved local Darwin/x86_64 Mac. At planning
  time it had approximately 152 GiB free disk; the real preflight must still
  re-measure RAM and disk immediately before each expensive step.

## Frozen inputs

- Git base: `ad3686414d9bf5b9c305434665f7d65ec9ae20c7`.
- Dataset: `dataset_K562_multilabel_with_NEGs.csv`, expected SHA-256
  `982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945`.
- Dataset audit: `manifests/dataset_audit.json`, expected SHA-256
  `e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c`.
- Protein index: `configs/proteins.tsv`, expected SHA-256
  `374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9`.
- Study configuration: `configs/coordinate_feasibility.toml`, expected SHA-256
  `91c88168225648d16835f0a0d322dcb0317ce9baaa4a4a8bdb4907f917b4ec5c`.
- Tools: BWA 0.7.19, minimap2 2.31, SeqKit 2.13.0, Python 3.11.
- Frozen minimap2 index settings: preset `splice:sr`, `k=15`, `w=5`, HPC
  minimizers disabled, and one-part batch limit `-I 8G`. The required command
  shape is `minimap2 -x splice:sr -I 8G -d INDEX REFERENCE`, with the preset
  before `-d`. The installed 2.31 binary must independently confirm these
  resolved settings before a human reference is indexed.
- Maximum mapping/indexing threads: 4.
- Peak new disk: at most 30 GiB, while leaving at least 80 GiB free.
- Pinned paths, all resolved under the repository filesystem:
  - execution outputs: `artifacts/coordinate_feasibility/`;
  - downloaded sources: `references/sources/<assembly>/`;
  - derived references: `references/derived/<build>/reference.fna`;
  - disposable mapper indices: `indices/<build>/`.

## Proposed official reference sources

Use the NCBI RefSeq assembly releases below as immutable source packages. The
downloaded compressed FASTA and assembly report must first match the upstream
MD5 listing and then receive locally computed SHA-256 hashes.

### hg38 / GRCh38

- Assembly: GRCh38.p14, RefSeq `GCF_000001405.40`.
- Compressed genomic FASTA:
  `https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.40_GRCh38.p14/GCF_000001405.40_GRCh38.p14_genomic.fna.gz`
- Expected compressed size at plan review: 972,898,531 bytes.
- Upstream MD5: `c30471567037b2b2389d43c908c653e1`.
- Assembly report:
  `https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.40_GRCh38.p14/GCF_000001405.40_GRCh38.p14_assembly_report.txt`
- Assembly-report MD5: `21f3ac4aa8245a99eb874082051b9dde`.
- Upstream checksum listing:
  `https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.40_GRCh38.p14/md5checksums.txt`

### hg19 / GRCh37

- Assembly: GRCh37.p13, RefSeq `GCF_000001405.25`.
- Compressed genomic FASTA:
  `https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.25_GRCh37.p13/GCF_000001405.25_GRCh37.p13_genomic.fna.gz`
- Expected compressed size at plan review: 943,912,841 bytes.
- Upstream MD5: `faf040d8b57cc04f1a4d5b23cccbb5ce`.
- Assembly report:
  `https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.25_GRCh37.p13/GCF_000001405.25_GRCh37.p13_assembly_report.txt`
- Assembly-report MD5: `5ded666a3acfcf7262370b7b4328badd`.
- Upstream checksum listing:
  `https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.25_GRCh37.p13/md5checksums.txt`

These source FASTAs contain alternate and patch sequences and therefore are not
used directly. A deterministic filter must derive matched references from the
assembly reports.

The recorded size and MD5 values are authoritative plan inputs, not advisory
observations. B3/B5 must compare both the downloaded file and the live
`md5checksums.txt` entry with these values. Any disagreement is a hard stop and
requires a recorded decision in `docs/DECISIONS.md`; silent re-pinning is
prohibited.

## Frozen derived-reference policy

Include records whose assembly-report sequence role is one of:

- `assembled-molecule` from `Primary Assembly`;
- `unlocalized-scaffold` from `Primary Assembly`;
- `unplaced-scaffold` from `Primary Assembly`;
- the mitochondrial `assembled-molecule` from the `non-nuclear` unit.

Exclude all alternate loci, fix patches, novel patches, decoys, and separately
packaged HLA contigs. Preserve the source accession as the FASTA identifier:
use the RefSeq accession when present, otherwise the GenBank accession. Do not
rename records to convenience aliases.

**Superseding production clarification (2026-09-24):** the pinned `GCF_...`
packages are RefSeq FASTAs and their paired GenBank assemblies are not always
identical. For these production sources, use the RefSeq namespace only;
category-eligible GenBank-only rows are explicit source-unrepresented
exclusions. See `docs/DECISIONS.md` and the B3 hg38 preparation task. The
original fallback remains relevant only to an explicitly configured GenBank
source, not to the pinned GCF runs.

The derivation must be streaming and deterministic. It must verify that:

1. every selected accession occurs exactly once in the source FASTA;
2. no unselected accession appears in the derived FASTA;
3. every sequence length equals the assembly-report length;
4. the selected contig set and category counts are identical to the generated
   manifest;
5. repeated derivation produces the same FASTA SHA-256;
6. hg38 and hg19 use the same inclusion logic.

Each reference manifest must include at least the fields already enforced by
`rbpbench.coordinates.manifest`, plus source compressed size/SHA-256/upstream
MD5, assembly-report hashes, derivation command and Git commit, a complete
contig list, and `contig_categories` keyed by the actual FASTA identifiers. It
must also contain an accession-to-assembly-chromosome-name table and base counts
by uppercase, lowercase, and ambiguous symbol so masking status is classified
as `soft`, `hard`, or `none`.

Accepted naming/content deviation: the `hg19` study label means the RefSeq
GRCh37.p13 assembly, not the UCSC hg19 package. In particular, RefSeq
GRCh37.p13 uses mitochondrial accession `NC_012920.1` (rCRS), whereas UCSC
hg19's `chrM` is based on `NC_001807.4`. This difference is intentional and
must be repeated in the final report so a build-rate difference is not
misattributed.

## Required readiness work before real downloads

Task 001A intentionally stopped before reference acquisition and mapper-index
preparation. Before downloading a genome, the executor must implement and test
the missing 001B execution layer on tiny fixtures:

1. A checked-in execution-source specification for the two references above
   and the frozen dataset/audit/protein/config hashes. The runner must compare
   expected and observed hashes before opening the real CSV or starting any
   reference work; hashing for a fingerprint without an equality check is not
   sufficient.
2. A restart-safe downloader that writes to a temporary name and atomically
   promotes only after upstream MD5 and local SHA-256 verification.
3. A streaming assembly-report/FASTA filter implementing the frozen contig
   policy and producing the required manifest.
4. Explicit mapper-index preparation and provenance:
   - `bwa index -p indices/<build>/<build> ...`, with output files, commands,
     hashes, sizes, elapsed time, and peak memory; add a build-keyed
     `--bwa-index-prefix` runner argument and pass that prefix to `bwa mem`
     instead of the FASTA;
   - one minimap2 `.mmi` produced with the frozen `splice:sr`, `k=15`, `w=5`,
     non-HPC, and `-I 8G` settings, with command, hashes, sizes, elapsed time,
     peak memory, and verified one-part status;
   - runner support for using the prepared minimap2 index while continuing to
     use the matching FASTA for BWA, SeqKit, manifest validation, and junction
     lookup;
   - creation-time index manifests containing SHA-256 and byte size for every
     index file. Restart checks may use unchanged size/mtime to avoid needless
     multi-gigabyte rehashing, but any change forces full hash verification
     against the creation-time manifest.
5. Capture stdout and stderr separately for every external tool invocation and
   hash both. Never send mapper stderr to `DEVNULL`. Treat minimap2's
   `indexing parameters ... overridden` warning, any multi-part-index warning,
   or a resolved `k/w/H` mismatch as a failed run.
6. Restart fingerprints that include the current reference, manifest, BWA
   prefix/index manifest, and minimap2 index manifest. `exact_match` and
   `report` must compare the current reference hash with the one recorded by
   `align` and fail closed on disagreement; `report` must do the same against
   `exact_match`. No stage may silently attach a current reference or manifest
   to older mapping evidence.
7. Preserve accepted checkpoint evidence. If an existing `align.json` or
   `exact_match.json` says `executed: true`, a dry run, failed preflight,
   missing index, or other non-executed attempt must fail without overwriting
   it. Successful replacements remain atomic and fingerprint-bound.
8. Cleanup that removes exactly `indices/<build>/` only after index hashes,
   provenance, successful mapping outputs, and successful reconciliation are
   present. It must refuse symlinks; refuse a target equal to, above, or
   containing the reference or output directory; show the resolved deletion
   list first; and contain nothing irreplaceable in an index directory.
9. A failed reconciliation must make the runner exit nonzero. The review gate
   nevertheless checks `reconciliation.status == "passed"` in `report.json`,
   rather than trusting the process exit code alone.
10. Real mapping authorization must accept exactly one `--build`; the runner
    must reject `--allow-mapping` with zero or multiple explicit builds.
11. A real-binary tiny smoke test confirming the installed SeqKit 2.13.0
    contract: `locate --use-fmi --bed --pattern-file`, BED6 columns, both
    strands in one invocation, no double counting, and `--ignore-case` across
    a lowercase/uppercase boundary in a soft-masked fixture.
12. Focused tests for download interruption, checksum failure, reference
    filtering/masking, missing/foreign/stale/multipart indices, captured
    stderr, reference/report mismatch, protected executed records, single-build
    authorization, failed-reconciliation exit status, restart behavior, disk
    budgeting, and cleanup target safety.

No scientific thresholds or mapper parameters may change during this work.

### Disk-budget ledger

The 30-GiB limit is measured from a recorded B1 baseline across every volume
used by the pinned paths. These are conservative planning allowances, not
claims about final file sizes:

| Material simultaneously present at the B6 peak | Allowance |
|---|---:|
| Two compressed source packages and assembly metadata | 2.0 GiB |
| Two derived references plus FASTA indices | 6.5 GiB |
| Preserved hg38 SAM/BED/report outputs | 4.0 GiB |
| Active-build BWA index | 5.5 GiB |
| Active-build minimap2 index | 7.0 GiB |
| Active hg19 SAM/BED/report outputs | 4.0 GiB |
| Environment, manifests, logs, and temporary-file margin | 1.0 GiB |
| **Projected peak** | **30.0 GiB** |

B1 must implement a fail-closed projected-peak check before every download,
derivation, indexing, or mapping subprocess and record observed new bytes and
free space afterward. Mapper/exact-match output writers must enforce their
combined 4.0-GiB build allowance as a stop, never use a truncated file, and
retain the failure evidence. If observed sizes invalidate a later projection,
stop before the next subprocess. Free space must remain at least 80 GiB.

## Checkpointed execution

For the real run, invoke only the stages named by the active checkpoint. Do
not use `--stage all`: that convenience path would cross review gates and
could start the second build before the first build has been inspected.

### B0 — second review of this plan

Claude acts as reviewer only. No edits, installs, downloads, or mapping.
Resolve review findings in writing before producing the executor handoff.

**Gate:** planning reviewer and project owner approve the reconciled 001B task.

### B1 — environment and readiness implementation

- Create an isolated project environment; never install globally.
- Before other environment work, confirm that `osx-64` packages exist for all
  three pinned tool versions; inability to resolve one is an immediate stop.
- Resolve the three pinned tool versions and export an explicit environment
  file plus resolved package/build and binary hashes. Confirm minimap2 2.31's
  installed `splice:sr` index settings are `k=15`, `w=5`, and non-HPC.
- Implement the readiness work above using only tiny synthetic references.
- Run the complete existing suite plus new tests and real-binary tiny smoke
  tests.
- Pin the runtime paths to `artifacts/coordinate_feasibility/`, `references/`,
  and `indices/<build>/`; add `.gitignore` coverage for `*.fa`, `*.fasta`,
  `*.fna`, `*.fna.gz`, `*.bed`, and `*.tsv.gz` outside already ignored
  directories.
- Record machine-readable host, RAM, CPU, `df`, volume identity, baseline disk
  usage, environment, tool evidence, and the resolved minimap2 index settings.

**Gate:** code review confirms index/reference provenance and destructive
cleanup safety. No human reference may have been downloaded.

### B2 — real dataset sampling only

- Run only the explicitly named `sample`, `decode`, and `controls` stages with
  `--output-dir artifacts/coordinate_feasibility/`; do not use `--stage all`.
- Fail-closed verification must compare all four frozen dataset/audit/protein/
  config hashes before reading the dataset.
- Reconcile exactly 10,000 biological IDs, 5,000 representative IDs, all
  quotas, strict 500-nt round trips, and 100 distinct controls.
- Record artifact hashes; do not commit the decoded FASTA.

**Gate:** reviewer accepts the sample/control manifest and count reconciliation.

### B3 — prepare hg38

- Every runner command must name exactly `--build hg38`; the runner must reject
  accidental multi-build real execution.
- Re-run resource preflight.
- Download and verify only the GRCh38.p14 source FASTA/report/checksum listing.
- Derive and validate the filtered hg38 reference and manifest.
- Prepare BWA and minimap2 indices in the hg38-specific index directory.
- Run a tiny real-tool smoke mapping against the prepared hg38 reference.
- Run SeqKit against the largest hg38 contig with the complete realistic
  pattern set (10,000 biological queries plus 100 controls). Record wall time,
  peak RSS, baseline host memory, and output size; stop if projected full-run
  memory plus host baseline would exceed the physical 16 GiB or the disk/time
  evidence makes B4 unsafe.

**Gate:** reviewer accepts source/derived hashes, contig policy, index
provenance, smoke outputs, and observed disk/RAM. Do not yet run the 10,100
queries against the full reference and do not run either aligner on them.

### B4 — execute and review hg38

- Every runner command must name exactly `--build hg38`; do not use
  `--stage all` or include hg19.
- Run hg38 BWA mapping, minimap2 splice mapping, SeqKit exact matching,
  per-build report, and reconciliation through the guarded runner.
- Require both a zero process exit and `reconciliation.status == "passed"`
  before cleanup.
- Hash all outputs, then remove only reproducible hg38 mapper-index caches.
- Preserve the filtered hg38 FASTA, reference manifest, reports, and raw
  mapping outputs until the combined review is complete.

**Gate:** reviewer inspects reconciliation, control alerts, mapping categories,
exact-match discordance, runtime/memory, and disk before hg19 starts.

### B5 — prepare hg19

Repeat B3 for GRCh37.p13 only after the hg38 index cleanup is verified.
Every runner command must name exactly `--build hg19`.

**Gate:** same preparation review as B3.

### B6 — execute hg19 and build the combined report

Repeat B4 with exactly `--build hg19`. Then run `combined_report` as a separate
non-mapping invocation over the two already accepted per-build reports. Confirm
that every scientific table excludes controls except `control_alerts`, all four
build/mode combinations reconcile, and the report remains
recommendation-neutral.

**Gate:** technical execution accepted; no automatic Phase 2 decision.

### B7 — human scientific decision and Git handoff

The planning reviewer evaluates the full report against the parent task's
prespecified guide and records exactly one recommendation:

- `proceed_with_coordinates`;
- `revise_and_repeat_feasibility`; or
- `use_sequence_clustering_fallback`.

Commit only small code, tests, source specifications, environment export,
manifests, and sanitized reports. Keep source/derived FASTAs, indexes, decoded
sequences, SAM/PAF/BED outputs, and other large artifacts out of ordinary Git.
Commit their hashes and local/shared artifact locations instead. The PR must
state which artifacts another collaborator must obtain to reproduce the run.
The final report must state the RefSeq-versus-UCSC label/mitochondrial
difference above and note that pseudoautosomal chrY windows may correctly be
classified as multi-locus rather than being a mapper defect.

## Acceptance checks

- Every parent Task 001 acceptance check is satisfied or explicitly marked as
  a documented stop.
- Tool and binary versions/hashes match the frozen versions.
- The runner compares all frozen input hashes before reading the CSV.
- Source files match NCBI upstream MD5 and recorded local SHA-256 hashes.
- Derived references exactly implement the matched contig policy.
- BWA/minimap2 indices are tied to the exact derived FASTA and parameters.
- Minimap2 uses a single-part `splice:sr` index with `k=15`, `w=5`, non-HPC,
  and `-I 8G`; tool stderr is preserved and hashed.
- Peak observed new disk stays at or below 30 GiB and free disk never falls
  below 80 GiB.
- Mapping/indexing uses at most four threads and one genome build at a time.
- A failed or planning-only retry cannot overwrite a previously executed
  checkpoint record, and report/reference mismatches fail closed.
- Sample and report reconciliation passes without missing biological/control
  IDs or unknown categories.
- Every BWA exact-unique result has independent SeqKit confirmation.
- Re-running from the same inputs reproduces sampled IDs and scientific tables
  byte-for-byte, excluding isolated runtime fields and compressed-container
  timestamps where decompressed content is identical.
- The full test suite passes before and after real execution.

## Stop conditions

Stop immediately and return evidence if:

- any frozen input, source MD5, or recorded SHA-256 mismatches;
- a live NCBI checksum listing disagrees with the authoritative plan values;
- the real host is not Darwin/x86_64 with at least 16 GiB RAM;
- fewer than 80 GiB are free or projected peak new disk exceeds 30 GiB;
- an exact pinned tool version cannot be resolved in an isolated environment;
- the two assemblies cannot be filtered under the same contig-role policy;
- a derived contig is missing, duplicated, unexpected, or has the wrong length;
- an index cannot be proven to derive from the exact reference and parameters;
- minimap2 reports an overridden indexing parameter, a multipart index, or
  settings other than `k=15`, `w=5`, and non-HPC;
- SeqKit's installed behavior disagrees with the tiny both-strand/BED6 smoke
  contract;
- the largest-contig SeqKit probe plus measured host baseline projects RAM
  demand above 16 GiB or makes the full exact-match run unsafe;
- sampling, decoding, control, or report reconciliation fails;
- the same mapping/indexing mode fails twice for the same documented reason;
- cleanup cannot identify a narrow, explicit index-only target;
- real mapping is requested without exactly one explicit `--build`;
- the next action would map the full dataset, construct folds, train a model,
  change a scientific threshold, or upload sequences to a service.

## Executor return at every checkpoint

Return:

1. checkpoint name and status;
2. commit hash and branch, if code changed;
3. exact commands and exit status;
4. hashes and byte sizes of every input/output touched;
5. elapsed time, peak memory, machine-readable `df`/memory snapshots, baseline
   and observed new-disk bytes, and free disk before/after expensive work;
6. tests and reconciliation results;
7. resolved minimap2 index parameters and hashed stdout/stderr logs;
8. stop-condition audit and the exact next action awaiting approval.
