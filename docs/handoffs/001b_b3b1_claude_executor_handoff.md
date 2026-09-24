# Executor handoff — Task 001B checkpoint B3B-1

Claude, execute **B3B-1 only: verified GRCh38.p14 source acquisition and
deterministic hg38 reference derivation**. B3A is accepted in
`docs/reviews/001b_b3a_acceptance.md`. This checkpoint authorizes the three
frozen NCBI source requests and real hg38 derivation for the first time. It
does not authorize indexing, probe execution, mapping, exact matching,
reporting, cleanup, hg19, or any later checkpoint.

## Required reading and Git boundary

Read, in order:

1. `docs/reviews/001b_b3a_acceptance.md`;
2. `docs/reviews/001b_b3_reconciliation.md`;
3. `docs/tasks/001b_b3_hg38_preparation.md`, especially B3B-1 and all B3
   stop conditions;
4. `docs/tasks/001b_coordinate_feasibility_execution.md`;
5. `docs/reviews/001b_b2_acceptance.md`;
6. `configs/coordinate_execution_sources.toml`;
7. `docs/COORDINATES.md`, `docs/DATA.md`, and `docs/DECISIONS.md`.

Then verify:

- branch `issue-001b-coordinate-execution`;
- origin `https://github.com/theAguy/RBP.git`;
- B2 acceptance `e62026b`, B3 reconciliation `a63a2ba`, B3A implementation
  `a4f0de3`, and this acceptance/handoff commit are ancestors of `HEAD`;
- the worktree is clean and the accepted `rbpbench-coord-001b` environment is
  active with Python 3.11 and the pinned tools first on `PATH`;
- at least 80 GiB is free and every source/derived/output/index path resolves
  to the disk-ledger volume.

Commit locally on this branch. Do not push, merge, rewrite history, or work on
`main`.

## Expected pre-existing ignored state

At handoff preparation time:

- `references/sources/GRCh38.p14/` is absent;
- `artifacts/coordinate_feasibility/hg38/` is absent;
- `references/derived/hg38/derive.json` is a non-executed dry-run record,
  SHA-256
  `0f8f134696a6ecb70f3ca9af27970dd8aa8c7c7bd7e119b21f11e98a08515b86`;
- `indices/hg38/index.json` is a non-executed dry-run record, SHA-256
  `da375f2259a696bc1a2baadbb4010bd2acd6532816be4cb9423a401500f4f37f`.

The two dry-run mtimes may reflect the accepted test suite. Record their
current hashes before B3B-1. Do not delete or edit them. The real derive stage
may atomically replace only the non-executed `derive.json`; B3B-1 must not
touch `indices/hg38/index.json`. If any other source, derived, index, or hg38
artifact file exists, stop and list it before doing anything destructive or
adopting it.

## Strict authorization boundary

B3B-1 authorizes:

- revalidating the four frozen local inputs and the accepted B2 evidence;
- exactly three network requests, all for the frozen GRCh38.p14 source:
  `md5checksums.txt`, the compressed genomic FASTA, and the assembly report;
- the guarded `preflight`, `download`, and `derive` stages, in separate
  checkpointed invocations and in that order;
- reading/hash-validating the selected source and derived-reference evidence;
- one independent repeat derivation into a disposable directory, solely to
  prove byte-identical deterministic output;
- creating and committing the planned small sanitized manifest,
  `manifests/coordinate_preparation_hg38_b3.json`, with checkpoint/status
  explicitly identifying this as B3B-1 evidence; B3B-2 may extend that same
  tracked manifest only after a later handoff.

B3B-1 does **not** authorize:

- any hg19 request or file;
- `index`, `probe`, `align`, `exact_match`, `report`, `combined_report`, or
  cleanup;
- BWA/minimap2 index construction, mapper execution, or SeqKit execution;
- `--force`, `--stage all`, multiple builds, or more than one build-scoped
  stage in an invocation;
- changing source pins, contig policy, commands, tool versions, thresholds,
  budgets, sampling, code, tests, configuration, or documentation;
- deleting an accepted generation or silently retrying a content/checksum/
  policy disagreement.

If execution exposes a code or configuration defect, stop with preserved
evidence. Do not patch it in this execution checkpoint.

## Preflight and persistent logging

Before any network request, record UTC time, commit, host/OS/architecture,
Python and tool versions, RAM, available/reclaimable memory, filesystem
identity, free disk, repository size, current disk-ledger state, the expected
ignored-record hashes above, and the accepted B2 manifest/artifact hashes.

Store command, stdout, stderr, timing, peak-memory, and exit-status evidence
under a new persistent ignored directory below
`artifacts/coordinate_feasibility/hg38/`; no temporary Claude scratch path may
be the only log location.

Run the runner's `preflight` stage alone with:

- the frozen config, dataset, execution-source spec, dataset audit, and
  protein config;
- `--output-dir artifacts/coordinate_feasibility`;
- `--sources-dir references/sources`;
- `--derived-dir references/derived`;
- `--indices-dir indices`;
- `--repo-root .` and `--disk-budget-path .`;
- exactly `--build hg38`, `--host-role approved_mac`, `--allow-mapping`, and
  at most four threads;
- exactly `--stage preflight`.

Require a zero exit and a passing `preflight.json`. Note that the current
runner revalidates and reads the frozen dataset for every normal invocation;
this is expected behavior for the accepted implementation, not permission to
run sampling again. Confirm that no sample/decode/control output changes.

## Download invocation and checks

After the preflight passes, run a second invocation with the same frozen
paths/host/build/authorization arguments and exactly `--stage download`.
Never add `--force` or another stage.

Require all of the following before continuing:

1. The checksum listing is requested and validated first. If it fails, the
   FASTA and assembly-report URLs are not requested.
2. The exact intended remote basenames are used:
   `GCF_000001405.40_GRCh38.p14_genomic.fna.gz` and
   `GCF_000001405.40_GRCh38.p14_assembly_report.txt`.
3. The two intended listing entries are unique and structurally valid.
4. Live-listing, frozen, and downloaded MD5 values agree exactly.
5. The compressed FASTA is exactly 972,898,531 bytes.
6. The three selected source files have recorded path, URL, SHA-256, MD5 where
   applicable, and byte size; `download.json` selects one complete immutable
   generation.
7. Free disk, volume checks, and the persistent 30-GiB ledger still pass.

An interrupted transport may be retried only through the same guarded
download stage after inspecting the preserved failure and confirming that no
accepted record was replaced. A checksum, size, URL, or content disagreement
is a hard review stop and must not be retried or re-pinned.

## Derive invocation and independent determinism check

After download validation passes, run a third invocation with the same
frozen paths/host/build/authorization arguments and exactly `--stage derive`.
Never add `--force` or another stage.

Require a zero exit, an executed selected `derive.json`, and verify:

- build `hg38` and RefSeq assembly `GCF_000001405.40`;
- exact binding to the selected compressed FASTA, assembly report, and
  source-generation digest;
- the frozen inclusion policy only: primary-assembly assembled molecules,
  unlocalized scaffolds, unplaced scaffolds, plus the non-nuclear
  mitochondrial assembled molecule;
- unique complete selected accessions, allowed categories only, and correct
  accession-to-chromosome-name metadata;
- exact `contigs`/`contig_lengths` key equality, positive per-contig lengths,
  assembly-report agreement, and sum agreement with streamed emitted bases;
- derived FASTA SHA-256/size, uppercase/lowercase/ambiguous counts, and honest
  masking status (`soft` or `none_detected`, never inferred `hard` from N);
- valid selected reference-manifest raw hash and canonical content evidence;
- no hg19 content and no UCSC-file/content comparison.

Then independently invoke the pure streaming derivation against the selected
accepted source files into a fresh disposable directory, without changing
`derive.json` and without `--force`. Require the repeated FASTA SHA-256 and
byte size to match the selected derived FASTA exactly. Record the repeat
command/method, temporary path, hash, size, start/end time, and result in the
sanitized manifest, then remove only that disposable repeat candidate after
its evidence is captured. Do not remove the selected source or derived
generation.

## Sanitized manifest and required return

Only after every check passes, create
`manifests/coordinate_preparation_hg38_b3.json`. It must contain small
non-sequence evidence only:

- checkpoint/status and exact Git ancestry/branch/origin;
- the three exact runner commands, exit statuses, UTC times, elapsed time,
  peak memory, stdout/stderr log paths and hashes;
- host/resource/free-disk/filesystem snapshots and the cumulative disk
  ledger before and after each step;
- all frozen/live/downloaded source URLs, basenames, MD5s, SHA-256s, sizes,
  and selected download-generation evidence;
- selected derive record/generation/manifest paths and hashes;
- assembly/build/policy, contig/category/name/length/base/masking summaries;
- independent repeat-derivation hash/size equality;
- state/provenance confirmation that only B2 plus preflight/download:hg38/
  derive:hg38 are complete and no prohibited stage or binary ran;
- the exact next action: planning-reviewer acceptance before B3B-2.

Do not include sequence content, a complete FASTA, or a complete contig list
when aggregate counts and hashes suffice. Validate the JSON and audit it for
accidental large or sensitive content. Commit only this sanitized manifest;
no source, derived FASTA, selected-stage JSON, log, ledger, provenance,
index, or other generated artifact may be staged.

Return:

1. B3B-1 status and local manifest commit, or `no commit` on failure;
2. exact commands and exits;
3. source checksum/size/hash agreement and selected generation;
4. derivation binding, policy, contig/category/length/base/masking summary;
5. independent repeat-derivation evidence;
6. runtime, peak memory, disk/volume/ledger evidence;
7. state/provenance proof that no prohibited stage or binary ran;
8. `git diff --check`, staged-file audit, and final worktree status;
9. every anomaly or remaining gap without proceeding.

Stop after the one local sanitized-manifest commit. End exactly with:

`Task 001B checkpoint B3B-2 was not started.`
