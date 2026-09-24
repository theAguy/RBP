# Task 001B checkpoint B3B-1 stopped-execution review

## Verdict

**The stop was correct. A narrow code correction is required before B3B-1
resumes.** No source pin or scientific decision has failed. The accepted
checksum parser uses the wrong identity key for a hierarchical NCBI listing.

No B3B-1 success manifest or commit exists. B3B-2 remains unauthorized.

## Preserved evidence reviewed

- Branch/HEAD remained `issue-001b-coordinate-execution` at `768771c`; the
  tracked worktree and staging area were clean.
- Preflight passed on the approved Darwin/x86_64 host with 16 GiB RAM,
  approximately 149.7 GiB free, and the three pinned tool versions.
- `state.json` contains only the accepted B2 stages plus `preflight`; it
  records `download:hg38` as not executed and not completed.
- `references/sources/GRCh38.p14/download.json` is a non-executed failure
  record with SHA-256
  `e47f022e8be75f4c736ded828efbdb82b9c60d4133bacb40be866a236dd42a25`.
- Only `md5checksums.txt` was requested. The large FASTA and assembly report
  were not requested, no generation was selected, and the discarded
  candidate left no source file behind.
- The persistent disk ledger contains only its baseline; no download bytes
  were accepted. No derive, index, probe, align, exact-match, report, hg19,
  or cleanup action ran.

## Root cause

`parse_md5checksums_evidence()` reduces each listing path to
`Path(path).name`, stores a basename-to-MD5 mapping, and treats a repeated
basename as a duplicate. The real GRCh38.p14 listing has many different
alt-locus subdirectories containing generic names such as
`alt.scaf.fna.gz`. Those are different files with different full relative
paths and therefore legitimately different MD5 values.

A synthetic reproduction with
`./assembly_structure/A/alt.scaf.fna.gz` and
`./assembly_structure/B/alt.scaf.fna.gz` produces a false
`conflicting_duplicate` on `a4f0de3`. The recorded real failure contains 178
such clauses. None indicates disagreement in either intended frozen target.

## Required semantics

The correction must be path-aware, not permissive:

1. Parse and validate every nonempty listing line.
2. Normalize and key entries by safe POSIX relative path after the ordinary
   leading `./`; reject absolute paths, traversal, empty/malformed paths, and
   invalid MD5 tokens.
3. Reject an identical normalized path repeated with either the same or a
   different MD5. Never overwrite the first value silently.
4. Allow the same basename under different normalized relative paths.
5. Derive the two expected listing paths from the frozen source URLs relative
   to the frozen checksum-listing URL's directory. Require the URLs to share
   the expected scheme/host/directory relationship and require the exact
   root-relative target entries.
6. Keep local destination filenames as the exact source URL basenames and
   retain checksum-first ordering, triple MD5 agreement, size validation,
   transactional generation selection, and restart protection unchanged.

Restricting duplicate checks only to the two target basenames would hide
malformed exact-path duplicates elsewhere. Keeping full relative paths
preserves global structural validation without inventing conflicts between
different files.

## Preflight logging anomaly

The first preflight's console/time capture was malformed and discarded. The
authoritative passing `preflight.json` remained intact, and the identical
second invocation performed a restart-safe skip without changing stage
state. This is an execution-log blemish to disclose in the eventual B3B-1
manifest, not a reason to repeat preflight or a blocker to the parser
correction.

## Gate

Only the checksum-path correction handoff is authorized next. It is a
source/test/documentation correction using tiny local fixtures. It may not
access the network, the real CSV/B2 FASTAs, or a human reference, and it may
not resume B3B-1. After correction review, a separate recovery handoff will
authorize the guarded download retry.
