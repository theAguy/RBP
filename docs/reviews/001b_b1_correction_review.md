# Review of Task 001B checkpoint B1 correction

## Verdict

**Do not accept B1 yet; a second, narrower correction round is required.**

Commit `11738d8` fixes the central reference-binding, index-binding,
failed-record, persistent-ledger, report-state, masking, and cumulative-
provenance defects from the first review. The complete suite also passes with
the pinned real binaries. However, several executable guarantees requested in
the correction handoff are still absent or only partially implemented. These
are operational safety defects; they do not change the scientific design.

B2 remains blocked. This review did not open or hash the real dataset, request
an NCBI URL, download a human reference, create a human-genome index, or run
real mapping.

## Independent verification

- Reviewed correction commit `11738d8` against
  `docs/handoffs/001b_b1_corrections_claude_handoff.md` and the reconciled
  Task 001B plan.
- Ran the complete suite with the isolated environment and the pinned real
  binaries on `PATH`: **270 passed in 54.80s**.
- `git diff --check` is clean and the worktree was clean before this review.
- Reproduced that a completed cleanup receipt contains `sha256: null` and
  `byte_size: null` for a file that existed before deletion.
- Reproduced that the literal minimap2 warning
  `For a multi-part index, no @SQ lines will be outputted` returns no
  violation from `check_minimap2_mapping_stderr`.
- Confirmed the parser accepts one `--allow-mapping` invocation listing
  `download`, `derive`, `index`, `align`, `exact_match`, and `report`, thereby
  crossing the B3/B4 review gate despite rejecting omitted/`all` stages.

## Corrections that are now satisfactory

- Exact-match and report compare their active reference/manifest with upstream
  accepted records.
- Index manifests bind build, reference content, index paths/files, commands,
  settings, and resolved binary evidence; split-directory overrides are
  checked separately.
- Non-executed attempts are routed through the protected-record writer and
  rejected attempts have a sidecar log.
- The disk ledger uses a persistent baseline and a maximum cumulative delta,
  rather than summing cumulative snapshots.
- Failed reconciliation remains retryable, and masking no longer infers hard
  masking from ambiguous bases.
- Actual index tool versions and cumulative build provenance are recorded.

## Remaining blockers

### B1-C1 — Source acquisition does not verify the live checksum listing

`ReferenceSourceSpec.md5checksums_url` is loaded but never used. The download
stage fetches only the FASTA and assembly report, then compares their bytes to
the frozen MD5 values. It therefore cannot implement the frozen requirement
that B3/B5 compare the downloaded file **and the live `md5checksums.txt`
entry** with the authoritative plan value.

The acquisition restart boundary is also incomplete:

- FASTA and assembly report are promoted independently, not as one accepted
  source set;
- derivation trusts paths and `executed: true` from `download.json` without
  re-hashing the current source files against that record;
- the download/derive fingerprints do not include current output hashes, so a
  changed source or derived artifact can be skipped as completed;
- `reference.fna` is promoted before its manifest is successfully built and
  persisted, so failure can leave a new FASTA paired with an old manifest.

Required:

- fetch the checksum listing with the same injected-transport interface;
- parse and require exactly the intended entries, compare the live entries,
  frozen MD5s, downloaded MD5s, and authoritative FASTA size, and preserve the
  checksum-list hash/content evidence;
- revalidate accepted source and derived outputs before a restart skip and
  immediately before derivation;
- promote the source set and the derived FASTA+manifest as transactional
  generations, so a failure preserves the previously accepted set;
- add actual-CLI regressions for live-list mismatch, altered accepted source,
  altered derived output, and failure between the members of each artifact
  set.

### B1-C2 — Multi-file replacement is per-file atomic, not set-atomic

Index, align, and exact-match stages write to attempt directories, which is a
good first half of the fix. They then call `os.replace` sequentially for each
final file and only afterward write the manifest/record. A failure during the
replacement loop or final manifest/record write can therefore leave a mixture
of old and new files while the previous accepted record remains. This is the
same accepted-evidence failure the transactional requirement was intended to
prevent.

Required:

- store each successful multi-file output as an immutable/versioned
  generation and atomically switch one manifest/pointer, or implement an
  equivalently transactional directory swap with rollback;
- bind the accepted JSON record to that generation before it becomes visible;
- cover failures at every promotion position and during manifest/record
  persistence for index, align, exact-match, and derived-reference sets.

### B1-C3 — Disk/output enforcement is not a combined 4-GiB cap

`stage_align` passes a 4-GiB limit independently to BWA and minimap2, then
`stage_exact_match` grants SeqKit another 4 GiB. Stderr, report generation,
the compressed mappings table, and already-retained build outputs are not
part of a shared live counter. The implementation can therefore accept much
more than the intended combined 4 GiB for one build.

The cross-volume check includes output, indices, and explicitly supplied
references, but omits `--sources-dir` and `--derived-dir`. During B3 those are
the paths that receive the downloaded and derived references; measuring them
against a baseline from another volume would be meaningless.

Required:

- enforce one shared live per-build allowance across BWA SAM/logs, minimap2
  SAM/logs, SeqKit BED/logs, mappings/report outputs, and retained files;
- account for bytes already accepted before granting the remaining allowance;
- include source and derived roots in the same-volume proof (or maintain a
  separate persisted ledger for each explicitly allowed volume);
- add a regression in which individually sub-limit writers exceed the cap in
  combination, plus cross-volume source/derived tests.

### B1-C4 — Cleanup is not yet pinned or durably auditable

Cleanup validates only the shape `*/indices/<build>`, explicitly not the
pinned repository root, while the CLI accepts an arbitrary `--indices-dir`.
Its symlink walk stops at the immediate `indices` parent, so a symlinked
ancestor above that parent is not rejected. The reference guard is a hardcoded
relative `references/derived/<build>/reference.fna`, not the actual accepted
reference recorded by the run. Mapping SAM/BED hashes are checked, but the
report is authorized by status alone rather than its recorded artifact hash.

The receipt is written once before deletion and then overwritten after
deletion. The second write re-hashes paths that no longer exist, replacing the
valid preview evidence with null hashes and sizes. This was reproduced
directly.

Required:

- pin CLI cleanup to the configured repository `indices/<build>` root and the
  actual accepted reference path; reject every symlinked path component;
- verify the accepted report and provenance hashes as well as mapping and
  index evidence;
- preserve the pre-deletion file list, hashes, sizes, and full index manifest
  in the final receipt, adding completion fields without recomputing deleted
  paths; write the receipt atomically;
- add CLI-level arbitrary-root, ancestor-symlink, wrong-reference, altered-
  report, and final-receipt-hash regressions.

### B1-C5 — Explicit stage lists can still cross review checkpoints

The runner rejects an omitted stage list and `--stage all`, but accepts any
explicit list. One authorized invocation may still list all of `download`,
`derive`, `index`, `align`, `exact_match`, and `report`, crossing directly
from B3 preparation into B4 full execution without a review stop.

Required: make checkpoint compatibility executable. The simplest safe rule is
exactly one real build-scoped stage per `--allow-mapping` invocation; an
equally acceptable alternative is an explicit checkpoint argument with fixed
B3/B4/B5/B6 stage allowlists. Add a regression proving a mixed B3+B4 list is
rejected before data access or subprocess execution.

### B1-C6 — Restart/index-warning validation still has two holes

`align_fingerprint` includes the previously recorded index-stage fingerprint
and an `executed` boolean, but not the **current** index record/manifest/file
evidence. `index_fingerprint` likewise does not validate current generated
index artifacts before skipping. An altered or missing index manifest/file
can therefore leave index/align marked complete without re-running the
verification path; `index_manifest_is_current` is not wired into the runner.
Override manifests need the same current-content binding.

Separately, mapping-time warning detection infers multipart use only from two
or more `mm_idx_stat` lines. It does not match minimap2's literal multi-part
warning, which was reproduced as returning an empty violation tuple.

Required:

- include current index-record, manifest, expected paths, and file evidence in
  index/align restart validity, forcing full hash verification on drift;
- store and compare the raw reference-manifest file SHA-256 promised by the
  review, in addition to any canonical parsed-content hash;
- reject explicit `multi-part`/`multipart` warning text at mapping time;
- add non-forced restart regressions for missing/altered manifests and index
  files, plus the literal warning text.

## Documentation correction

`docs/COORDINATES.md` still describes `--execution-sources` as opt-in and the
disk ledger as per-invocation. Update it only after the executable guarantees
above are correct, so the documentation matches the accepted behavior.

## Acceptance for the second correction round

- Add focused regressions for every B1-C1–C6 case above; each must fail on
  `11738d8` for the intended reason.
- Run the complete suite twice with the isolated environment and pinned real
  binaries on `PATH`.
- Run `git diff --check` and audit staged files for generated/large artifacts.
- Do not access the real CSV, request an NCBI URL, download a human reference,
  build a human-genome index, run real mapping, push, merge, or begin B2.
