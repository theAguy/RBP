# Executor handoff — Task 001B B3B-1 RefSeq derivation-policy correction

Claude, implement only the bounded correction defined in
`docs/reviews/001b_b3b1_derivation_stop_review.md` on
`issue-001b-coordinate-execution`.

## Git and required reading

1. Verify `eab0a35`, `722b3a1`, and this review/handoff commit are ancestors
   of `HEAD`; verify the expected origin and a clean tracked worktree.
2. Read, in order:
   - `docs/reviews/001b_b3b1_derivation_stop_review.md`;
   - `docs/DECISIONS.md` (the RefSeq derivation-universe decision);
   - `docs/tasks/001b_b3_hg38_preparation.md`;
   - `docs/handoffs/001b_b3b1_recovery_claude_handoff.md`;
   - `configs/coordinate_execution_sources.toml`;
   - the derivation, execution-source, runner, manifest, restart, and
     transaction tests.
3. Commit locally on this branch. Do not push, merge, rewrite history, or
   work on `main`.

## Authorization boundary

This is a code/test/config/documentation correction using tiny synthetic
fixtures only.

Do not:

- make any network request or invoke a URL transport;
- open, hash, decompress, inventory, or otherwise read the accepted human
  reference files, their assembly report/listing, or any ignored B3 log,
  state, provenance, ledger, source, derived, or index artifact;
- open/hash the real dataset or B2 biological/control FASTAs;
- run preflight, download, derive, index, probe, align, exact-match, report,
  combined-report, cleanup, or any real mapper/SeqKit command;
- change a source URL, checksum, byte size, assembly, category/role rule,
  sampling rule, threshold, tool pin, command, or resource ceiling;
- begin B3B-2 or create the sanitized B3B-1 execution manifest.

The accepted download must remain byte-for-byte untouched. If any requested
test would need real ignored evidence, replace it with a tiny local fixture.

## Required policy and implementation

1. In `configs/coordinate_execution_sources.toml`, make the source accession
   namespace explicit for the two pinned `GCF_...` sources by setting the
   authoritative accession preference to RefSeq only. Update its comments;
   do not alter any source field or role/category rule.
2. Validate the loaded derived policy fail closed: supported nonempty
   accession namespaces only, no duplicate preference, and valid/nonempty
   role values. Unknown or malformed policy must stop before data access.
3. Pass the exact loaded `DerivedReferencePolicy` through the runner into
   `stage_derive` and `derive_reference_fasta`; remove the real path's
   hard-coded policy. The derivation restart fingerprint and accepted record/
   manifest must bind the complete canonical policy. A policy-only change
   must invalidate derivation but must not invalidate or repeat an otherwise
   hash-valid download whose source acquisition fields are unchanged.
4. Apply configured unit/role and accession-namespace selection
   deterministically from the assembly report. A category-eligible row with
   no accession in the configured source namespace is an explicit
   `source_namespace_unrepresented` exclusion, not a selected missing FASTA
   record. Do not decide exclusions by scanning for absent FASTA headers.
5. Preserve the selected source accession as the output FASTA identifier.
   Never substitute a UCSC alias, infer an alternative accession, or combine
   RefSeq and GenBank packages.
6. Add structured derivation/manifest evidence for the effective policy and
   exclusions: reason, count, total bases, category counts, and deterministic
   records containing accession, role/category, report sequence name, and
   length. For the real policy this will later identify the three reviewed
   GRCh38 exclusions, but all tests here must use synthetic names/data.
7. For every selected accession retain the strict contract: it occurs
   exactly once in the source, its emitted length equals the assembly report,
   IDs/contig-length keys agree, and total emitted bases agree. Aggregate and
   raise the existing occurrence/length `violations` together with
   `validate_contig_lengths()` failures before any promotion; do not leave
   the former list unused.
8. Preserve transactional behavior: any policy, occurrence, length,
   manifest, record-write, or fingerprint failure discards the candidate and
   leaves a prior accepted derivation/generation/selection record unchanged.
9. Update documentation to distinguish category eligibility, source-
   namespace representation, selected contigs, and hard missing-selected
   failures. Do not describe the three exclusions as a corrupt source or a
   parser failure.

You may retain explicit GenBank-mode support for synthetic or future `GCA`
sources, but it must require a policy that names `genbank`; it must never be a
silent fallback under a RefSeq-only policy.

## Mandatory regressions

Add focused tiny-fixture tests that fail on this handoff's parent commit and
pass on the correction for at least:

1. a GCF-shaped report with one RefSeq-selected row plus one category-
   eligible GenBank-only row omitted from the FASTA: derivation succeeds with
   only the RefSeq row selected and the GenBank-only row explicitly reported;
2. exact exclusion reason/count/bases/category/record evidence in the result
   and reference manifest;
3. expected category counts for selected contigs excluding the reported row;
4. a selected RefSeq accession absent from the FASTA: hard failure, never an
   inferred exclusion;
5. a selected accession duplicated in the FASTA: explicit hard failure;
6. a selected accession with a length mismatch: explicit hard failure;
7. each failure preserving a prior accepted output/selection generation;
8. explicit GenBank-only policy selecting a GenBank-only fixture record;
9. RefSeq-only policy never falling back to a present GenBank alias;
10. preference order/namespace behavior when a fixture has both accessions;
11. unknown, empty, or duplicate accession policy rejected before source
    data access;
12. malformed/empty role policy rejected before source data access;
13. runner `stage_derive` uses the supplied policy and records/binds it;
14. a policy-only change invalidates derive restart state but does not
    invalidate or trigger download;
15. derivation/manifest generation digest changes when policy/exclusion
    evidence changes;
16. candidate and selection-record write failures retain the prior accepted
    generation under the new fields.

Keep all existing derivation, manifest, restart, atomicity, B3A, download,
and real-binary tests green. Where an existing synthetic test intentionally
uses a GenBank fallback, give it an explicit policy permitting GenBank rather
than weakening the new RefSeq production policy.

Prove the substantive new tests fail on the parent commit in a disposable
worktree, without reading the ignored real artifacts there. Run focused
tests, then the complete suite twice with the pinned environment and real
binaries first on `PATH`. Run `git diff --check` and audit staged files.

## Required return and stop

Return:

1. correction commit and complete changed-file list;
2. exact configured-policy, selection, and exclusion contract;
3. focused test names/count and parent-failure proof;
4. two full-suite results and real-binary test count;
5. restart-fingerprint, manifest, transaction, and download-preservation
   evidence;
6. `git diff --check`, staged-file audit, and clean-worktree status;
7. confirmation that no network, real CSV/B2 FASTA, human-reference, ignored
   evidence, or pipeline-stage action occurred;
8. every remaining gap.

Stop after the local correction commit. Do not resume B3B-1. End exactly with:

`Task 001B checkpoint B3B-1 was not resumed.`
