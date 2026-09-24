# Claude planning-review request — Task 001B checkpoint B3

Claude, act as the **second reviewer**, not the executor. Review
`docs/tasks/001b_b3_hg38_preparation.md` against the accepted Task 001B plan,
current runner, and B1/B2 evidence.

## Strict boundary

This is a read-only planning review. Do not edit or commit files; do not run
the runner; do not open/hash the real CSV or generated B2 FASTAs; do not make a
network request; do not download a reference; do not build an index; do not
invoke BWA, minimap2, or SeqKit; and do not begin B3–B7.

You may inspect tracked source, tests, configuration, manifests, Git history,
and the filenames/metadata of ignored dry-run records. Do not treat any
pre-existing `executed: false` dry-run record as accepted B3 evidence.

## Required reading

1. `docs/tasks/001b_b3_hg38_preparation.md`;
2. `docs/tasks/001b_coordinate_feasibility_execution.md`;
3. `docs/reviews/001b_coordinate_execution_second_review.md`;
4. `docs/reviews/001b_coordinate_execution_reconciliation.md`;
5. `docs/reviews/001b_b1_acceptance.md`;
6. `docs/reviews/001b_b2_acceptance.md`;
7. `manifests/coordinate_sampling_b2.json` without opening its referenced
   real artifacts;
8. the download, derivation, manifest, indexing, runner, disk-budget,
   provenance, and cleanup code plus their tests.

## Questions to answer

1. Are the three stated B3 readiness gaps real and complete: remote-basename
   checksum lookup, absent guarded probe stage, and absent accepted contig
   lengths? Identify any additional blocker that would first appear on the
   real GRCh38 source/reference/indices.
2. Is the proposed B3A/B3B split the safest minimal reproducible approach, or
   can any B3A item be removed without resorting to ad-hoc unaudited commands?
3. Review A1's checksum-first and remote-filename design against real NCBI
   listing semantics. Are duplicate/malformed-entry rules and transactional
   behavior sufficient?
4. Review A2's `contig_lengths` schema, validation, total-base evidence, and
   deterministic largest-contig rule.
5. Review A3's probe authorization, dependencies, smoke-query construction,
   mapper validation, SeqKit command semantics, BED validation, generation
   selection, restart binding, and separation from B4 outputs. Name every
   missing fail-closed check.
6. Review the proposed memory/time/output projections. Explicitly accept the
   2-GiB memory margin, 4.5-hour wall gate, and provisional 1-GiB SeqKit share,
   or replace them with justified formulas that can be evaluated before B4.
7. Can the persistent disk ledger safely account for the downloaded source,
   derived reference, two index families, extracted largest contig, patterns,
   and probe logs without double counting or silently exceeding the 30-GiB
   peak? Identify required code changes.
8. Are the pre-existing non-executed dry-run `derive.json`/`index.json` records
   safe to replace through the guarded stages, and what evidence should be
   captured before replacement?
9. Are the proposed B3B stage order, commands, internal stop conditions, and
   return evidence sufficient to authorize the whole B3 sequence after B3A
   acceptance, or should a human review gate be inserted before expensive
   indexing or probing?
10. Identify any change that would alter scientific policy rather than merely
    operational readiness; such a change must be escalated to the project
    owner instead of accepted implicitly.

## Required response

Return:

- verdict: approve, approve with required changes, or reject;
- numbered blockers with exact code/document evidence;
- numbered non-blocking improvements kept separate from blockers;
- explicit answers to questions 1–10;
- a proposed minimal B3A acceptance-test list;
- whether B3B may be covered by one later executor handoff after B3A review;
- confirmation that you made no edits and performed none of the prohibited
  actions.

Stop after the review. End with exactly:

`Task 001B checkpoint B3 execution was not started.`
