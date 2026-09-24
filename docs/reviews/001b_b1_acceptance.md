# Task 001B checkpoint B1 acceptance

## Verdict

**Checkpoint B1 is accepted. Checkpoints B2–B7 remain unstarted.**

The readiness implementation through commit `512d15a` satisfies the reviewed
B1 contract. It may serve as the code and environment base for the separately
authorized B2 real-dataset sampling checkpoint. Acceptance of B1 does not
authorize opening the real dataset, downloading references, indexing a human
genome, or running real mapping.

## Independent acceptance evidence

- Reviewed the A1/A2 correction in `512d15a` against
  `docs/reviews/001b_b1_acceptance_correction_review.md`.
- Focused acceptance-correction suite: **10 passed in 5.64s**.
- Complete suite with the isolated environment and pinned binaries on
  `PATH`: **336 passed in 62.99s**.
- `git diff --check 8dec676..512d15a` is clean.
- Directly reproduced that a report recording an older align generation is
  rejected by combined reporting when the current align record names a newer
  generation.
- Directly verified that selected reference-index provenance contains its
  exact `path`, `sha256`, and `byte_size`.
- The worktree contained no uncommitted implementation changes at acceptance.

## Accepted guarantees

- The isolated pinned tool environment and real-binary tiny smoke coverage are
  present.
- Real execution remains fail-closed behind explicit authorization,
  single-build and single-checkpoint boundaries, current preflight, reference
  manifests, hashes, resource limits, and disk/output budgets.
- Download, derivation, index, align, exact-match, and report artifacts use
  restart-safe selected generations with protected prior evidence.
- The accepted generation-digest chain reaches combined reporting and rejects
  stale upstream align or exact-match evidence.
- Per-build report consumers use `report_state.json` selected artifacts rather
  than mutable convenience mirrors.
- Provenance and cleanup identify and validate the selected report JSON,
  Markdown, mappings table, and reference-index artifact.
- Cleanup remains pinned to the actual repository index directory and requires
  complete hash-verified evidence.

## Next checkpoint boundary

B2 is limited to verifying the four frozen input hashes and running only the
`sample`, `decode`, and `controls` stages on the real dataset. It must reconcile
10,000 biological IDs, 5,000 representative IDs, all quotas, strict 500-nt
round trips, and 100 distinct controls. Decoded FASTA and other large/sensitive
artifacts remain outside Git. B3 cannot begin until the B2 manifest and counts
are independently reviewed and accepted.
