# Executor handoff — B3B-1 derivation-policy follow-up

Claude, correct only the blockers in
`docs/reviews/001b_b3b1_derivation_policy_correction_review.md` on
`issue-001b-coordinate-execution`.

## Git and required reading

1. Verify `d9bfcad`, `5f5308d`, and this review/handoff commit are ancestors
   of `HEAD`; verify the expected origin and a clean tracked worktree.
2. Read the review above, the prior derivation-policy correction handoff,
   the RefSeq-universe entry in `docs/DECISIONS.md`, both Task 001B/B3 task
   documents, `docs/COORDINATES.md`, and the changed implementation/tests.
3. Commit locally on this branch. Do not push, merge, rewrite history, or
   work on `main`.

## Authorization boundary

Use tiny synthetic fixtures only. Do not access/hash/inventory the real CSV,
B2 FASTAs, accepted human source/reference files, ignored logs/state/
provenance/ledger/index artifacts, or the network. Do not invoke preflight,
download, derive, index, probe, align, exact-match, report, combined-report,
cleanup, or real external tools. Do not change source pins, the accepted
RefSeq-only production decision, category values, mapper settings, sampling,
thresholds, or resource limits. Do not resume B3B-1 or begin B3B-2.

## Required corrections

### F1 — make the complete category policy operational

- Make category selection consume the supplied
  `DerivedReferencePolicy`; do not retain a hidden hard-coded production
  policy on the derivation path.
- A Primary Assembly row is eligible only when its normalized role appears
  in `include_sequence_roles_primary_assembly`, then maps to its known study
  category.
- A non-nuclear assembled molecule is eligible as `mitochondrion` only when
  `include_non_nuclear_assembled_molecule` is exactly `True`.
- Other units/roles remain category-ineligible and are not namespace-
  exclusion records.
- Make the policy argument explicit wherever practical so a caller cannot
  accidentally recover the old hard-coded behavior.
- Ensure selected category counts, contig set/lengths, effective policy, and
  exclusion evidence all describe the same actual output.

### F2 — validate before stage-level source access

- Validate `policy` at the start of `stage_derive()`, before download-
  evidence hashing, source/report reads, disk-ledger mutation, directory
  creation, or selection-record replacement.
- Retain independent validation inside `derive_reference_fasta()` before it
  opens the assembly report or source FASTA.
- Validate that `include_non_nuclear_assembled_molecule` is an actual
  boolean. Do not coerce an integer/string to a boolean while loading.
- Validate accession namespace entries as nonempty strings before set/
  membership operations, so malformed TOML produces controlled violations,
  never `TypeError`.

### F3 — bind an accepted derive generation digest

- Add `generation_digest` to successful `derive.json` records. It must be
  path-independent and content-derived, covering at least the derived FASTA
  SHA-256 and canonical reference-manifest content hash (which already
  covers policy and exclusion evidence).
- Extend `_verify_derive_evidence_hashes()` to parse the accepted manifest,
  recompute this digest, and reject a missing/mismatched digest. Preserve the
  existing raw manifest-file hash check.
- Identical content rebuilt in a fresh generation directory must retain the
  same digest. Any FASTA, canonical manifest, policy, or exclusion-evidence
  change must change it.
- Do not weaken the existing index binding to raw and canonical manifest
  hashes; the derive digest is additional accepted-stage evidence.

### F4 — finish the documentation contract

- Update `docs/tasks/001b_coordinate_feasibility_execution.md` to note that
  its original GenBank fallback was superseded by the recorded 2026-09-24
  RefSeq derivation-universe decision for the pinned GCF sources.
- Update `docs/COORDINATES.md` with policy-driven role/non-nuclear selection,
  RefSeq-only production namespace, explicit unrepresented exclusions,
  reference-manifest schema 3 fields, and the derive generation digest.
- Keep the 191-contig expected hg38 decision and three reviewed exclusions
  unchanged.

## Mandatory regressions

Add focused tests that fail on `5f5308d` and pass on the follow-up for:

1. a policy containing only Primary Assembly `assembled-molecule` excludes a
   present unplaced/unlocalized scaffold from output and selected counts;
2. `include_non_nuclear_assembled_molecule=false` excludes a present
   mitochondrial record;
3. enabling each field includes the corresponding tiny-fixture records;
4. category-ineligible rows are not reported as namespace-unrepresented;
5. toggling role/non-nuclear policy changes the actual derived FASTA/contigs,
   not only the fingerprint or manifest metadata;
6. an invalid policy passed directly to `stage_derive()` fails before
   `_verify_download_evidence_hashes` or any source hash/open;
7. a non-boolean non-nuclear flag and non-string/empty namespace entries
   yield controlled validation violations before data access;
8. successful `derive.json` contains the recomputable generation digest;
9. byte-identical rebuilds in different generation directories have the
   same digest;
10. changed policy/exclusion evidence or derived FASTA changes the digest;
11. missing/tampered digest or canonical manifest content fails derive
    restart-evidence verification;
12. selection-record write failure still preserves the prior accepted
    record/generation with the new digest field.

Keep the 24 prior correction tests and all existing derivation, manifest,
restart, transaction, B3A, download, and real-binary tests green. Prove the
new focused tests fail behaviorally on `5f5308d` in a disposable worktree;
an import/collection failure alone is not sufficient proof for this round.

Run focused tests and the complete suite twice in the pinned environment
with the real pinned binaries first on `PATH`. Run `git diff --check`, audit
all staged files, and leave the worktree clean.

## Required return and stop

Return:

1. correction commit and complete changed-file list;
2. exact F1-F4 resolution;
3. focused tests/count and behavioral failure proof on `5f5308d`;
4. two complete-suite results and real-binary count;
5. derive digest/restart/transaction evidence;
6. `git diff --check`, staged-file audit, and clean-worktree status;
7. confirmation that no prohibited real data/reference/network/stage action
   occurred;
8. every remaining gap.

Stop after the local correction commit. End exactly with:

`Task 001B checkpoint B3B-1 was not resumed.`
