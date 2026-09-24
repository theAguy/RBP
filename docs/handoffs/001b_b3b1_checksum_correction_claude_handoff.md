# Executor handoff — Task 001B B3B-1 checksum-path correction

Claude, implement only the narrow path-identity correction in
`docs/reviews/001b_b3b1_stop_review.md` on
`issue-001b-coordinate-execution`.

## Git and required reading

1. Verify `768771c` and this review/handoff commit are ancestors of `HEAD`.
2. Read:
   - `docs/reviews/001b_b3b1_stop_review.md`;
   - `docs/tasks/001b_b3_hg38_preparation.md`;
   - `docs/handoffs/001b_b3b1_claude_executor_handoff.md`;
   - `docs/reviews/001b_b3a_acceptance.md`;
   - `configs/coordinate_execution_sources.toml`.
3. Inspect `download.py`, `execution_sources.py`, `runner.stage_download`,
   and all download/restart/transaction tests before editing.
4. Commit locally on the same branch. Do not push, merge, rewrite history,
   or work on `main`.

## Authorization boundary

This is a code/test/documentation correction using tiny synthetic fixtures
and injected local transports only.

Do not:

- make any network request or request an NCBI URL;
- open or hash the real dataset or real B2 FASTAs;
- inspect, decompress, derive, or index a human reference;
- rerun preflight/download/derive or alter the preserved ignored B3B-1
  evidence;
- begin B3B-2 or any mapping/report/cleanup stage;
- change frozen URLs, hashes, byte sizes, assemblies, contig policy,
  scientific thresholds, sampling, tool parameters, or resource ceilings.

If a test would use a real URL or real ignored artifact, replace it with a
tiny local fixture. Do not delete the preserved failed `download.json` or
B3B-1 logs.

## Required implementation

1. Make the fail-closed checksum parser preserve a safe normalized POSIX
   relative path for every entry instead of collapsing it to a basename.
   Accept the ordinary NCBI `./relative/path` form, but reject absolute paths,
   `..` traversal, empty/malformed paths, and invalid MD5 tokens.
2. Detect `duplicate` and `conflicting_duplicate` only when the same exact
   normalized path repeats. Retain the first entry and report the violation;
   never silently overwrite it.
3. Treat distinct paths with the same basename as distinct valid entries.
4. Derive the expected FASTA and assembly-report listing paths from their
   frozen URLs relative to the directory of `md5checksums_url`. Fail closed
   if scheme/authority/directory relationships are inconsistent, ambiguous,
   escaping, or otherwise cannot yield safe exact relative paths.
5. Make `stage_download` look up exactly those paths. A nested file sharing a
   target basename must never satisfy a missing root target. Preserve local
   destination basenames from the source URLs.
6. Record the exact target listing paths in planned/accepted download
   evidence so later review can prove which listing entries were used.
7. Preserve all existing behavior: parse every listing line, fail on any
   malformed line or exact-path duplicate, fetch the listing before either
   large file, make no large request after a listing failure, require
   live/frozen/downloaded MD5 agreement and frozen size, select the complete
   source generation atomically, and protect prior accepted evidence.

The lenient legacy `parse_md5checksums()` helper may remain backward
compatible if needed; the production fail-closed path must use exact relative
paths without ambiguity.

## Mandatory regressions

Add focused tests that fail on `a4f0de3` for:

1. two different nested relative paths sharing a basename and having
   different MD5s: no duplicate violation;
2. the same exact normalized path repeated with the same MD5: duplicate
   violation;
3. the same exact normalized path repeated with a different MD5: conflicting
   duplicate violation;
4. a real-NCBI-shaped listing containing many nested same-basename entries
   plus the two unique root targets: the guarded tiny download succeeds and
   selects the root targets;
5. a nested same-basename target with the required root target absent: hard
   missing-entry stop and no large-file transport;
6. a nested same-basename entry conflicting with the frozen MD5 while the
   exact root target agrees: the root target is used and the download may
   proceed;
7. absolute, traversal, empty/malformed path and malformed-token rejection;
8. inconsistent source/checksum URL parent or authority rejection before any
   large-file transport;
9. failed parsing/path resolution preserving a prior accepted generation and
   selection record;
10. accepted evidence recording both exact target listing paths.

Keep the existing missing-entry, checksum-first, interruption, atomic-write,
restart, MD5, and byte-size regressions passing. Prove the core new tests fail
on `a4f0de3` and pass on the correction.

Run the focused tests and the complete suite twice with the pinned
`rbpbench-coord-001b` binaries first on `PATH`. Report real-binary test counts,
run `git diff --check`, audit staged files, and confirm the worktree is clean.

## Required return and stop

Return:

1. correction commit and complete changed-file list;
2. exact path-normalization and target-path derivation contract;
3. focused test names/count and proof of failure on `a4f0de3`;
4. two full-suite results and real-binary count;
5. transactional/restart/no-large-request evidence;
6. `git diff --check`, staged-file audit, and worktree status;
7. confirmation that preserved real B3B-1 evidence was not altered and no
   real data/network/human-reference action occurred;
8. every remaining gap.

Stop after the local correction commit. End exactly with:

`Task 001B checkpoint B3B-1 was not resumed.`
