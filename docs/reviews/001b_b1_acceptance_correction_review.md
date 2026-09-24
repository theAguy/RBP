# Review of Task 001B B1 acceptance correction

## Verdict

**B1 acceptance is deferred for one final, two-item wiring correction.**

Commit `46d857f` successfully makes the selected report generation—not the
fixed-path mirrors—the source of report JSON, mappings, report Markdown, and
cleanup reconciliation status. Mirror deletion/corruption and interruption
between mirror writes are now handled correctly. Two explicit conditions from
the acceptance handoff remain incomplete: combined reporting does not supply
current upstream records to the shared validator, and provenance does not
record the selected reference-index artifact's path/hash.

B2 remains blocked. This review did not open or hash the real dataset, access
an NCBI URL, download a human reference, create a human-genome index, or run
real mapping.

## Independent verification

- Reviewed commit `46d857f` against
  `docs/reviews/001b_b1_final_correction_review.md` and its executor handoff.
- Ran the complete suite with the isolated environment and pinned binaries on
  `PATH`: **330 passed in 49.67s**.
- `git diff --check ce0dfff..46d857f` is clean.
- Confirmed that a corrupt fixed report mirror no longer affects combined
  reporting and that selected-artifact tampering is detected.
- Reproduced upstream staleness directly: the shared accepted-report loader
  rejects a report recording `align-old` when the current align record says
  `align-new`, but `stage_combined_report` accepts and summarizes that same
  stale report because it calls the loader without the current align/exact
  records.
- Reproduced the provenance omission: for an evaluated accepted report,
  `generated_artifacts` contains mappings, report JSON, and report Markdown,
  but no reference-index artifact; the separate `reference_index` value is
  only the parsed payload and contains neither the selected path nor its
  SHA-256.

## Satisfactory parts

- `_load_accepted_report_state` is a useful shared fail-closed validator.
- Combined reporting reads selected report/mappings paths and ignores mirrors.
- Provenance attributes the selected report JSON, Markdown, and mappings
  artifacts.
- Cleanup reads selected reconciliation status and cross-checks the three
  recorded report artifacts against provenance.
- The combined-report fingerprint includes selected report generation
  digests, so a changed report generation invalidates a prior completion.

## A1 — Combined reporting does not validate current upstream generations

The selected report records
`upstream_align_generation_digest` and
`upstream_exact_match_generation_digest`. The shared loader compares them
with current records only when those records are supplied. Both
`stage_combined_report` and the main loop's combined-report restart check omit
them. The combined-report fingerprint also contains only report stage
fingerprints/report generation digests, not current align/exact generation
digests.

Therefore, after a forced align or exact-match rerun, an unchanged older
report can still be considered valid and a previously completed combined
report can be skipped. This defeats the generation chain that B1-F3 added.

Required:

- pass each build's current align and exact-match records to
  `stage_combined_report` and its accepted-report loader;
- perform the same upstream-aware validation before a combined-report restart
  skip;
- include current align/exact generation digests in combined-report restart
  validity, or otherwise ensure an upstream change cannot preserve a valid
  skip;
- fail closed with an instruction to rerun the per-build report when its
  upstream generation is stale;
- add align→report→combined and exact-match→report→combined drift regressions.

## A2 — Selected reference-index artifact is absent from provenance

The handoff required provenance to hash and attribute the selected report
JSON, Markdown, mappings table, **and reference-index diagnostic**. Commit
`46d857f` reads the selected reference-index file and stores its parsed JSON as
`builds[build].reference_index`, but it does not store the artifact path,
SHA-256, or byte size. Cleanup validates the reference-index hash against
`report_state.json`, but cannot cross-check that artifact against provenance
as it does for the other selected report members.

Required:

- add the selected `reference_index.json` to provenance's generated artifacts
  with its exact selected path, SHA-256, and byte size while retaining the
  parsed diagnostic payload if useful;
- have cleanup require provenance to identify that exact selected path/hash
  whenever the report state contains a reference index;
- keep honest `None` behavior for a non-evaluated report with no reference
  index;
- add provenance and cleanup regressions for a selected reference index,
  missing provenance entry, mismatched path/hash, and the legitimate
  no-reference-index case.

## Acceptance conditions

- Limit the correction to A1 and A2.
- Demonstrate each new regression fails on `46d857f` for its intended reason.
- Run the complete suite twice with pinned real binaries on `PATH`.
- Run `git diff --check` and audit staged files for generated/large artifacts.
- Do not access the real CSV or any NCBI URL; do not download/index a human
  genome, run real mapping, push, merge, or begin B2.
