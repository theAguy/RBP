# Task 001B checkpoint B3 — hg38 preparation plan

**Status:** draft for Claude planning review; no B3 execution authorized
**Parent:** `docs/tasks/001b_coordinate_feasibility_execution.md`
**Branch:** `issue-001b-coordinate-execution`
**Depends on:** B1 accepted at `31c57cd`; B2 accepted at `e62026b`

## Objective

Prepare only the RefSeq GRCh38.p14 study reference (`hg38`), its BWA and
minimap2 indices, and the prespecified B3 feasibility evidence needed to decide
whether full hg38 execution in B4 is operationally safe.

B3 does not run the 10,100 queries through either aligner, does not run SeqKit
against the complete reference, does not produce a per-build scientific
report, does not clean an index, and does not touch hg19.

## Why B3 needs a readiness sub-checkpoint

B1 implemented and tested the generic acquisition/index machinery on tiny
fixtures, but inspection after B2 found three real-source/probe boundaries that
must be corrected before network or genome-scale work:

1. `stage_download` stores the source files as
   `GRCh38.p14_genomic.fna.gz` and `GRCh38.p14_assembly_report.txt`, then looks
   up those local basenames in `md5checksums.txt`. The frozen NCBI URLs and
   checksum listing use the full
   `GCF_000001405.40_GRCh38.p14_...` basenames. The real download would
   therefore be rejected after the transfer even when all authoritative MD5s
   match.
2. The runner has no B3 stage for the tiny real-mapper smoke or the
   largest-contig SeqKit probe. Running those as ad-hoc shell commands would
   bypass accepted-generation selection, restart validity, persistent logs,
   provenance, and disk/output guards.
3. The derived manifest records the contig set and categories but not
   per-contig lengths. B3 therefore cannot select and prove the largest
   included contig from its accepted manifest alone.

B3 is split into B3A (tiny-fixture readiness correction) and B3B (real hg38
preparation). B3B remains unauthorized until B3A is implemented, reviewed, and
accepted.

## Frozen inputs and paths

No scientific constant changes in B3.

- Study label: `hg38`.
- Assembly: GRCh38.p14, RefSeq `GCF_000001405.40`.
- Source URLs, compressed byte size, MD5s, and contig policy remain exactly as
  frozen in `configs/coordinate_execution_sources.toml`.
- Dataset/sample/control/config artifacts remain the B2-selected files and
  hashes in `manifests/coordinate_sampling_b2.json`.
- Sources: `references/sources/GRCh38.p14/`.
- Derived reference: selected generation under `references/derived/hg38/`.
- Disposable indices: selected generation under `indices/hg38/`.
- Persistent B3 logs/evidence: `artifacts/coordinate_feasibility/hg38/`.
- Sanitized checkpoint manifest:
  `manifests/coordinate_preparation_hg38_b3.json`.

The pre-existing `references/derived/hg38/derive.json` and
`indices/hg38/index.json` are B1 dry-run records with `executed: false`. Record
their pre-B3 hashes. Do not delete or manually edit them. A successful guarded
real stage may replace its corresponding non-executed selection record
atomically; otherwise the old record must survive unchanged.

## B3A — readiness correction on tiny fixtures only

### A1 — bind downloads to the actual remote basenames

- Derive the expected FASTA and assembly-report basenames from their frozen
  URLs (or store equivalent explicit frozen remote filenames).
- Use those exact basenames both for local generation files and live checksum
  lookup. Never infer the checksum key from the shorter assembly label.
- Fetch the small `md5checksums.txt` first. Before downloading the large
  FASTA, require the exact intended FASTA and assembly-report entries and
  compare their live MD5s with the frozen values.
- Reject malformed MD5 tokens and duplicate/conflicting basename entries; do
  not silently let a later line overwrite an earlier one.
- Then download the two source files, compare downloaded MD5s with both the
  live listing and frozen values, enforce the authoritative compressed FASTA
  byte size, and record SHA-256/size/URL/listing evidence as already planned.
- Preserve the whole source set as one selected generation; any failure leaves
  prior accepted evidence untouched and discards the candidate.
- Add real-NCBI-style tiny fixtures whose assembly label and `GCF_...`
  filename differ, plus missing/duplicate/conflicting/malformed listing tests.

### A2 — add accepted contig-length evidence

- Add `contig_lengths`, keyed by the accepted FASTA identifiers, to the
  derived reference result and manifest.
- Validate exact key equality with `contigs`, positive integer lengths,
  agreement with the assembly report, and sum agreement with the emitted
  FASTA base count.
- Make the deterministic largest-contig rule explicit: greatest length, then
  accession lexicographic order only as a tie-break.
- Retain existing accession, category, chromosome-name, masking, source, and
  derivation evidence unchanged.
- Add tiny-fixture manifest/validation tests, including a tied-largest case.

### A3 — add a guarded B3 probe stage

Add one build-scoped `probe` stage (name open to reviewer correction) that is
allowed only as its own authorized checkpoint invocation and never writes
`align.json`, `exact_match.json`, or B4 report state.

The probe must:

1. Require and revalidate the accepted B2 sample/control hashes, selected
   derived hg38 FASTA/manifest, and selected BWA/minimap2 index generation.
2. Build a 10,100-record pattern FASTA transactionally from the accepted
   10,000 biological and 100 control FASTAs, with exact ID-set/count/hash
   evidence.
3. Select the largest included contig from accepted `contig_lengths`, stream
   exactly that contig to the candidate probe generation, and verify its ID,
   length, alphabet/base count, and source-reference binding.
4. Select a deterministic 500-nt A/C/G/T-only window from that contig for a
   one-query mapper smoke. Record accession and zero-based coordinates but not
   the sequence in the sanitized manifest.
5. Run pinned BWA-MEM and minimap2 against their accepted hg38 indices with one
   thread, persistent stdout/stderr, command/binary/output hashes, bounded
   time, and output caps. Require zero exits, parseable SAM, the smoke query
   exactly once as a primary record from each mapper, and a mapped alignment
   to an accepted contig. Multi-mapping is allowed for this operational smoke.
6. Run pinned SeqKit 2.13.0 once against only the extracted largest contig,
   using the exact B4 command semantics: `locate --use-fmi --bed
   --ignore-case --pattern-file` with all 10,100 patterns and both strands in
   the single invocation. Persist and hash BED/stdout, stderr, elapsed time,
   peak RSS, host-memory snapshots, and output size.
7. Validate every nonempty output row as BED6, require a known pattern ID and
   coordinates within the selected contig, and reject duplicate counting of
   the same hit. Zero hits is an honest result, not a failure.
8. Produce one immutable probe generation selected by `probe.json` only after
   all checks pass. Restart validity must bind B2 artifacts, reference/
   manifest, exact index generation, binaries, command parameters, and probe
   implementation commit. Failed/non-executed retries must not overwrite a
   prior accepted probe.
9. Charge probe files/logs to the persistent 30-GiB ledger and apply an
   explicit live cap to SeqKit output. Fixed-path copies, if any, are
   non-authoritative.
10. Be fully tested with tiny synthetic references and fake tools plus the
   already pinned real binaries on tiny fixtures. No NCBI URL or human
   reference is touched in B3A.

### A4 — B3 evidence and logging contract

- Store all real B3 command stdout/stderr/time/resource logs below
  `artifacts/coordinate_feasibility/hg38/`; never use an ephemeral scratch
  path as the only copy.
- Extend cumulative provenance with download, derive, index, and probe selected
  paths/hashes without treating dry-run records as real evidence.
- The B3 sanitized manifest must contain hashes/sizes, commands, timings,
  memory/disk snapshots, contig/category/masking summaries, resolved minimap2
  parameters, and projection results, but no sequences or complete BED/SAM
  content.
- If B3A reveals any need to change frozen source values, contig policy,
  mapper parameters, resource ceilings, or sampling, stop for a recorded
  project-owner decision instead of implementing the change.

## B3A gate

Claude implements B3A only after this plan is reconciled and an executor
handoff is issued. The planning reviewer then reviews the code/tests. No
network or human-scale work is authorized until B3A is accepted.

## B3B — real hg38 preparation sequence

After B3A acceptance, use exactly one explicit `--build hg38` and one
build-scoped stage per authorized runner invocation. Every invocation uses the
accepted environment, execution-source spec, B2 output directory, pinned
source/derived/index roots, `--host-role approved_mac`, at most four threads,
and `--allow-mapping`. Never use `--stage all` or `--force`.

Execute in order, stopping immediately on any failure:

1. **Preflight:** record current host/RAM/disk/volume/tool/input evidence. Free
   disk must remain at least 80 GiB and the 30-GiB projected ledger must pass.
2. **Download:** acquire only GRCh38.p14 checksum listing, compressed FASTA,
   and assembly report. Require live/frozen/downloaded MD5 agreement, frozen
   compressed size, local SHA-256, and a selected `download.json` generation.
3. **Derive:** stream the frozen contig policy into the selected hg38 FASTA and
   manifest. Independently repeat derivation into a disposable candidate and
   require the same FASTA SHA-256 before accepting determinism evidence.
4. **Derivation review checks:** exact source/manifest/reference binding;
   complete unique contig set; allowed categories only; sequence lengths and
   total bases; category counts; accession-to-chromosome names; uppercase,
   lowercase, ambiguous counts; masking status; and expected RefSeq
   `GCF_000001405.40` identity. Do not compare with UCSC filenames/content.
5. **Index:** build only hg38's BWA and minimap2 indices. Require fresh
   preflight, the frozen commands, zero exits, separate persistent logs,
   creation-time file hashes/sizes, minimap2 `k=15`, `w=5`, non-HPC,
   single-part evidence, no override/multipart warning, and binding to the
   selected reference and raw/canonical manifest hashes.
6. **Probe:** run only the accepted B3 probe stage. Do not run B4 align,
   exact-match, report, combined-report, or cleanup.

Each successful step records before/after time, peak memory, free disk,
observed new bytes, and current ledger state. A later failure preserves every
earlier accepted generation and its evidence.

## Probe projection and B4-safety decision

Let `Lmax` be the selected largest-contig length and `Ltotal` the total bases
in the filtered reference. Record `scale = Ltotal / Lmax`.

The B3 manifest must report, without silently authorizing B4:

- observed probe wall time, peak RSS, output bytes, and hits;
- a conservative full-reference wall-time projection using at least
  `observed_wall × scale × 1.5`;
- a conservative output projection using at least
  `observed_output_bytes × scale × 2`, while explaining the limitation when
  the observed hit count is zero;
- current available/reclaimable host memory, physical RAM, and probe peak RSS;
- whether the projected exact-match output fits within a provisional 1-GiB
  share, leaving at least 3 GiB of the combined 4-GiB build-output cap for the
  two mapper SAM/log sets and report artifacts;
- whether projected full-reference SeqKit wall time remains below 4.5 hours,
  leaving margin under the runner's six-hour subprocess bound;
- whether probe peak RSS plus a 2-GiB safety margin fits both physical RAM and
  the measured available/reclaimable memory at probe start.

These numerical gates are proposed operational safeguards, not scientific
thresholds. Claude's planning review must explicitly accept or replace them
with a more defensible fail-closed formulation before B3A implementation.

## B3 stop conditions

Stop without proceeding or silently retrying if any of the following occurs:

- frozen/local/live/downloaded hash, MD5, size, URL, assembly, or build
  disagreement;
- unexpected pre-existing executed evidence or any changed B2 artifact;
- source or derived-reference validation failure, nondeterministic derivation,
  disallowed contig, missing selected accession, duplicate accession, or
  length/total mismatch;
- less than 80 GiB free, a failed volume check, or a projected/observed
  30-GiB ledger breach;
- wrong tool/binary version or hash, index file drift, minimap2 override,
  multipart index, or `k/w/H` mismatch;
- smoke command failure, malformed SAM, unmapped smoke query, or foreign
  contig;
- malformed/duplicate/out-of-range SeqKit BED evidence, output-cap breach, or
  any failed memory/time/output projection gate;
- any attempt to invoke hg19, B4 align/exact-match/report, combined report, or
  cleanup.

An interrupted network transfer may be retried only through the same guarded
download stage after inspecting the preserved failure and confirming that no
accepted generation was replaced. Any checksum/content disagreement requires
a recorded decision, not a retry.

## B3 return and gate

After successful B3B execution, commit only the sanitized
`manifests/coordinate_preparation_hg38_b3.json` plus any already-reviewed B3A
code/tests/docs. Keep source/derived FASTAs, indices, pattern FASTA, largest
contig, SAM/BED outputs, and logs ignored and uncommitted.

Return exact commands/status, hashes/sizes, source/derive/index/probe selected
records, contig/masking summaries, minimap parameter evidence, smoke results,
SeqKit resource/projection results, disk ledger, staged-file audit, and every
anomaly. Stop for planning-reviewer acceptance. B4 remains unauthorized.
