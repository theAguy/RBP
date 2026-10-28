# Task 003A supervisor split validation — superseded review request

> Superseded by the direct former-versus-accepted supervisor presentation.
> The underlying scientific evidence is unchanged; no further Claude review
> is required for this presentation-only revision.

## Review purpose

Perform the one independent final acceptance review authorized by the Task
003A planning acceptance. Review commit `ea2611a` on branch
`issue-002c-partition-assignment`. This is a review of numerical
reconciliation, claim wording, figure/table provenance, and presentation
quality. It is not a request to redesign the analysis or start Task 003B.

## Required reading

Read these files in order:

1. `docs/tasks/003a_supervisor_split_validation_report.md`
2. `docs/reviews/003a_supervisor_split_validation_planning_acceptance.md`
3. `docs/reports/003a_supervisor_split_validation.md`
4. `manifests/task003a_split_validation_report.json`
5. `src/rbpbench/analysis/split_validation.py`
6. `src/rbpbench/analysis/legacy_fold_export.py`
7. `src/rbpbench/analysis/figures.py`
8. `src/rbpbench/analysis/reporting.py`
9. `src/rbpbench/analysis/task003a.py`
10. `tests/test_analysis_split_validation.py`

The rendered supervisor PDF and complete tables are in the Git-ignored accepted
generation:

`artifacts/task003a_split_validation/generations/task003a_0c89d75feec7/`

Its selection record is:

`artifacts/task003a_split_validation/selected.json`

## Implementation and execution evidence

- Implementation commit: `ea2611a`.
- Focused synthetic suite: 27/27 passed.
- Full local real-data regeneration: completed in 150.89 seconds.
- Independent consecutive generations produced byte-identical `results.json`,
  all eight TSV tables, and all eight SVG figures.
- The final PDF has 10 A4 pages, page numbering on every page, and was rendered
  page-by-page with Poppler for visual review.
- Output selection, provenance inventory, sanitized manifest, tracked SVG
  hashes, and all PDF page labels were independently reverified after the
  final run.
- No model, prediction, baseline, MMseqs2 search, network request, or split
  mutation occurred.

## Headline results to reconcile

- Former fold against rejected v1 grouping:
  - 26,765 crossing components;
  - 45,937/72,236 affected holdout rows (63.593%);
  - 120,760/288,944 affected train rows (41.794%).
- Same reproduced former fold against accepted components v2:
  - 25,307 crossing components;
  - 46,209/72,236 affected holdout rows (63.969%);
  - 125,772/288,944 affected train rows (43.528%).
- Accepted split:
  - 169,699 components and 361,180 rows;
  - 246,017 train / 57,565 validation / 57,598 test;
  - zero split components;
  - zero exact/reverse-complement cross-partition groups;
  - zero qualifying cross-partition hits in all 18/18 directed audits.
- Label disclosure:
  - 86 proteins / 218 cells flagged over all partitions;
  - 54 proteins / 117 cells flagged in validation/test;
  - minimum evaluation support 97 known positives and 80 known negatives,
    above the floor of 30.
- Composition disclosure:
  - maximum absolute SMD 0.101225 for 500-nt normalized entropy,
    train versus test;
  - this is only 0.001 above the prespecified 0.10 reporting boundary and is
    described as small/borderline rather than as a split failure;
  - maximum KS D 0.057244 for 500-nt GC fraction, train versus validation.

## Required review questions

1. Do every accepted headline and denominator reconcile to the frozen evidence
   and generated tables?
2. Is the historical v1 result clearly separated from the new v2 recomputation
   of the same former fold?
3. Are direct edges, connected components, exact/RC relations, and audit hits
   kept scientifically distinct?
4. Are the 4,792 rejected-v1 pairs correctly presented as the first stopped
   search and a lower bound, not a complete leakage total?
5. Do the figures and captions avoid implying AUROC inflation or model
   performance?
6. Is the protein-balance denominator clear, with count sufficiency separated
   from fraction balance?
7. Is the borderline composition result described proportionately and without
   row-level inferential claims?
8. Does the transaction/provenance design fail closed and preserve a prior
   accepted selection on failure?
9. Is the supervisor PDF visually legible and free of clipping or overlap?
10. Is any remaining issue genuinely blocking Task 003A acceptance?

## Review boundary and return

Do not run model training, MMseqs2, network access, or a full real-data
regeneration. Small read-only hash checks and focused tests are allowed. Do not
modify files in the first response.

Return one verdict:

- `Accept Task 003A`, or
- `Approve with bounded corrections`, listing only scientifically or
  reproducibly blocking corrections with the exact failure prevented.

If accepted, explicitly confirm that Task 003A can close and that the next
project task may move to simple training-only baselines without reopening the
split.
