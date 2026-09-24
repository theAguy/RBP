# Task 001B checkpoint B3 — hg38 preparation plan

**Status:** B3A accepted at `768771c`; the checksum path correction `eab0a35`
is accepted; the guarded B3B-1 download is accepted locally, but derivation
stopped safely because the pinned RefSeq FASTA omits three GenBank-only rows
from the broader assembly report. The accession-policy correction in
`docs/handoffs/001b_b3b1_derivation_correction_claude_handoff.md` is the only
authorized next work; B3B-1 has not passed and B3B-2 remains unauthorized
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

The pinned genomic FASTA is the RefSeq (`GCF_...`) package. For derivation,
the source accession namespace therefore controls the representable contig
universe: category-eligible assembly-report rows must also have a usable
RefSeq accession. GenBank-only rows in a non-identical paired GenBank
assembly are excluded explicitly and reported; they are not silently treated
as missing RefSeq FASTA records and are not supplemented from a second
assembly. For GRCh38.p14 this excludes exactly `KI270721.1`, `KI270734.1`,
and `KI270752.1` (293,111 bases total). Any selected RefSeq accession missing
from the pinned RefSeq FASTA remains a hard failure.

## B3A — readiness correction on tiny fixtures only

### A1 — bind downloads to the actual remote basenames

- Derive the expected FASTA and assembly-report basenames from their frozen
  URLs (or store equivalent explicit frozen remote filenames) for the local
  generation filenames. For live checksum lookup, derive each target's exact
  normalized path relative to the directory containing the frozen
  `md5checksums.txt`; never infer either identity from the shorter assembly
  label.
- Fetch the small `md5checksums.txt` first. Before downloading the large
  FASTA, require the exact intended FASTA and assembly-report entries and
  compare their live MD5s with the frozen values.
- Parse listing identity by normalized relative path, not basename. Reject
  malformed MD5 tokens/paths and duplicate/conflicting entries for the same
  exact normalized path; do not silently let a later line overwrite an
  earlier one. Distinct subdirectory paths may legitimately share a basename
  and must remain distinct.
- Make checksum parsing return both the normalized-relative-path-to-MD5
  mapping and explicit parse violations (malformed token/path, duplicate
  exact path, conflicting exact-path duplicate). `stage_download` adds those
  violations to its existing fail-closed violation list. It must never
  silently skip or overwrite them, and it must require the two target entries
  at their exact expected root-relative paths rather than adopting a
  same-basename entry from a nested directory.
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
   evidence. Do not reuse `_prepare_mapping_reads`, which writes a mutable
   fixed-path file and is not transactional.
3. Select the largest included contig from accepted `contig_lengths`, stream
   exactly that contig line-by-line to the candidate probe workspace, and
   verify its ID, length, alphabet/base count, and source-reference binding.
   Do not materialize the approximately 249-Mb contig as one Python string.
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
   `0 <= start < end <= contig_length` on the single selected contig, and
   reject duplicate counting of the same pattern/contig/start/end/strand hit.
   Zero hits is an honest result, not a failure.
8. Produce one immutable probe generation selected by `probe.json` only after
   all checks pass. Restart validity must bind B2 artifacts, reference/
   manifest, exact index generation, binaries, command parameters, and probe
   implementation commit. Add a `probe_fingerprint()` chained from the exact
   B2 sample/control hashes, raw reference/manifest hashes, index fingerprint
   and generation digest, binary identities, command parameters, and clean Git
   commit. Failed/non-executed retries must not overwrite a prior accepted
   probe.
9. Use a temporary candidate workspace for the reproducible pattern FASTA,
   extracted contig, and smoke query. Hash and describe them, but remove them
   before selecting the immutable probe output generation; their authoritative
   sources remain the accepted B2 FASTAs and derived reference. The selected
   generation retains only `probe.json`-named evidence: BWA/minimap2 SAM and
   stderr, SeqKit BED and stderr, and machine-readable validation/resource
   records.
10. Enforce two explicit, non-overlapping budget rules:
    - before the probe, reserve at most 1 GiB of candidate-work space from the
      existing `environment_manifests_logs_margin` and at most 1 GiB of
      retained probe output from the existing 4-GiB build-output allowance;
      call the whole-run projected-peak check with a conservative 2-GiB next
      step allowance, without adding a new category that would make the
      frozen 30-GiB table sum exceed 30 GiB;
    - live-cap the combined retained BWA/minimap2/SeqKit outputs and logs at 1
      GiB. Record their accepted byte total in `probe.json`, seed those bytes
      into the same `BuildOutputBudget` used later by align, exact-match, and
      report, and update `_build_budget_excluding` accordingly. Thus B4 has at
      most 3 GiB left and probe+B4 accepted build outputs can never exceed 4
      GiB.
11. Keep the selected probe output generation and persistent logs through B4
    review. They remain part of the 30-GiB measured ledger and 4-GiB per-build
    counter. No deletion is authorized in B3; any later removal requires a
    separately reviewed, hash-evidenced cleanup decision.
12. Extend cumulative provenance with probe selected paths, hashes, upstream
    bindings, resource data, and accepted bytes, while keeping probe evidence
    distinct from B4 align/exact-match/report evidence.
13. Be fully tested with tiny synthetic references and fake tools plus the
   already pinned real binaries on tiny fixtures. No NCBI URL or human
   reference is touched in B3A.

### A4 — B3 evidence and logging contract

- Store all real B3 command stdout/stderr/time/resource logs below
  `artifacts/coordinate_feasibility/hg38/`; never use an ephemeral scratch
  path as the only copy.
- Extend cumulative provenance with download, derive, index, and probe selected
  paths/hashes without treating dry-run records as real evidence.
- Make FASTA/assembly-report line handling tolerate both LF and CRLF without
  changing emitted reference bytes for ordinary LF inputs.
- Generalize the clean Git-commit provenance helper if needed so derivation
  and probe can bind their implementation commits without cross-module
  coupling.
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

Execution is split by an independent human gate.

### B3B-1 — source acquisition and derivation

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

Then commit/return only a sanitized source/derivation manifest and stop. The
planning reviewer must accept the downloaded-source evidence, repeated
derivation hash, complete derived-reference manifest, contig policy, masking,
disk ledger, and all stop-condition checks before B3B-2 is authorized.

### B3B-2 — indexing and feasibility probe

Only after a second executor handoff:

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

After successful B3B-2 execution, commit only the sanitized
`manifests/coordinate_preparation_hg38_b3.json` plus any already-reviewed B3A
code/tests/docs. Keep source/derived FASTAs, indices, pattern FASTA, largest
contig, SAM/BED outputs, and logs ignored and uncommitted.

Return exact commands/status, hashes/sizes, source/derive/index/probe selected
records, contig/masking summaries, minimap parameter evidence, smoke results,
SeqKit resource/projection results, disk ledger, staged-file audit, and every
anomaly. Stop for planning-reviewer acceptance. B4 remains unauthorized.
