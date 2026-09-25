# Task 001B B3B-1 derivation-policy correction review

**Status: superseded by the project-scope decision and conditional acceptance
in `001b_b3b1_derivation_policy_conditional_acceptance.md`. The findings below
remain valid engineering observations, but they do not block the frozen
production run.**

## Verdict

**Changes required. Correction `5f5308d` is not accepted yet.** Its RefSeq
namespace selection and explicit exclusion evidence are correct, and the
complete suite passes, but the full configured policy is not actually
applied to contig selection. B3B-1 may not resume and B3B-2 remains
unauthorized.

## What passed review

- Production `accession_preference` is now explicitly RefSeq-only.
- A category-eligible GenBank-only row becomes a deterministic
  `source_namespace_unrepresented` exclusion under that policy; it is not
  inferred from a missing FASTA header.
- Selected missing, duplicated, and length-discordant accessions fail before
  output promotion. The formerly unused occurrence/length violation list is
  now raised together with the contig-length validator.
- The reference manifest records the effective policy, exclusion records,
  and exclusion summary. A policy-only change invalidates derive restart
  state without invalidating the accepted download.
- Existing transaction and selection-record preservation behavior remains
  intact in the reviewed paths.
- `git diff --check d9bfcad..5f5308d` is clean. The 24 new focused tests pass.
  An independent complete pinned-environment run passed: **502 tests in
  138.71 seconds**. The tracked worktree was clean before review.

No network, real dataset/B2 FASTA, pipeline stage, or real-reference
derivation was run during this review. The already accepted primary-source
metadata was not changed.

## Blocking finding R1 — two recorded policy fields are ignored

`derive_reference_fasta()` records all of `DerivedReferencePolicy` as
`effective_policy`, and the runner fingerprints it, but selection still
calls the old hard-coded `contig_category(record)`. That function always
includes all three recognized Primary Assembly roles and always includes the
non-nuclear mitochondrial assembled molecule. It never reads:

- `policy.include_sequence_roles_primary_assembly`; or
- `policy.include_non_nuclear_assembled_molecule`.

An independent tiny synthetic reproduction used this valid policy:

```text
include_sequence_roles_primary_assembly = ["assembled-molecule"]
include_non_nuclear_assembled_molecule = false
accession_preference = ["refseq"]
```

The manifest reported exactly that policy, but derivation emitted:

```text
ACTUAL_CONTIGS   ('NC1.1', 'NCMT.1', 'NW1.1')
EXPECTED_CONTIGS ('NC1.1',)
```

`NW1.1` was an unplaced Primary Assembly scaffold and `NCMT.1` was the
non-nuclear mitochondrion. Both should have been category-ineligible under
the supplied policy.

The current production policy happens to name all three roles and enable the
mitochondrion, so this bug would not change the planned 191-contig hg38
result. It is still an acceptance blocker: accepted evidence can claim one
policy while the FASTA implements another, and the promised configurable,
fingerprinted contract is false.

## Blocking finding R2 — stage-level validation is after source hashing

The CLI `main()` validates the policy before local-input verification, which
is correct. However, the callable `stage_derive()` trusts its caller and
invokes `_verify_download_evidence_hashes()` before
`derive_reference_fasta()` performs its own policy validation. A malformed
policy passed directly to the stage therefore hashes accepted source files
before failing, contrary to the handoff's “before any source data access”
contract.

`stage_derive()` must validate its policy at entry, before reading or hashing
the download record's files and before creating a candidate generation. The
lower-level validation in `derive_reference_fasta()` should remain as an
independent guard.

## Blocking finding R3 — promised derive generation digest is absent

The handoff required the derivation/manifest generation digest to change
when policy or exclusion evidence changes. The new test only compares
`manifest_content_sha256(manifest)` locally. An accepted `derive.json` still
has no `generation_digest`, despite `docs/COORDINATES.md` describing every
accepted stage record as carrying one.

Add a path-independent, content-derived digest to an accepted derive record,
covering at least the derived FASTA hash and canonical reference-manifest
content hash. Restart evidence verification must recompute and compare it.
Byte-identical derivations under identical policy/evidence must yield the
same digest even when written to a new generation directory; changed policy,
exclusion evidence, FASTA, or manifest content must change it.

## Documentation and validation follow-up

- `docs/tasks/001b_coordinate_feasibility_execution.md` still says RefSeq
  falls back to GenBank. It must point to the recorded RefSeq-universe
  decision and describe the superseding RefSeq-only production rule.
- `docs/COORDINATES.md` must document policy-driven category eligibility,
  namespace-unrepresented exclusions, manifest schema 3 fields, and the
  derive generation digest.
- Policy validation should reject a non-boolean
  `include_non_nuclear_assembled_molecule` and non-string accession namespace
  entries with controlled violations rather than coercing/crashing.

## Gate

Only the tiny-fixture follow-up handoff is authorized. It may change code,
tests, and documentation, but may not access ignored B3 evidence, the human
reference, the real dataset/B2 FASTAs, or the network; it may not invoke any
pipeline stage. After the follow-up is independently accepted, a separate
handoff may authorize real `derive:hg38` from the already accepted download.
The download must not be repeated.
