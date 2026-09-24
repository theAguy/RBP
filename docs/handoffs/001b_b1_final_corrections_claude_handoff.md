# Final convergence handoff — Task 001B checkpoint B1

Claude, remain the executor for **B1 only**. Correct every B1-F1–F6 item and
the selection-record failure requirement in
`docs/reviews/001b_b1_second_correction_review.md`. Do not broaden the
scientific design and do not begin B2.

## Git and required reading

1. Verify `origin` is `https://github.com/theAguy/RBP.git`.
2. Work only on `issue-001b-coordinate-execution`.
3. Verify `01d98b5` and this handoff commit are ancestors of `HEAD`.
4. Read, in order:
   - `docs/reviews/001b_b1_second_correction_review.md`;
   - `docs/tasks/001b_coordinate_feasibility_execution.md`;
   - `docs/reviews/001b_coordinate_execution_reconciliation.md`;
   - `docs/reviews/001b_b1_correction_review.md`.

Commit locally on the same branch. Do not push, merge, or rewrite history.

## Implementation boundary

Implement the review literally:

- one live aggregate per-build output counter covering every SAM, BED, log,
  mappings, reference-index, and report artifact;
- transactional report generations and restart artifact verification;
- accepted-generation/record digests chained through every downstream stage;
- exact index-generation evidence bound to align;
- derived-manifest and raw reference-manifest hashes persisted and compared;
- strict checkpoint combinations (`preflight` plus one real build stage only;
  B2 and combined-report invocations remain separate and non-mapping);
- cleanup rooted independently at the actual repository and fail-closed on
  missing/changed derive or report evidence;
- discard every unselected generation if its atomic selection-record write
  fails.

Do not fix tests by weakening these guarantees, retaining stale fixed-path
fallbacks, or merely adding documentation. Failure injection must exercise the
selection-record write itself, not only an earlier subprocess/member failure.

## Authorization boundary

You may use the existing isolated environment and pinned binaries on tiny
synthetic fixtures. Downloader tests must use local/injected transports.

You must not:

- open or hash `dataset_K562_multilabel_with_NEGs.csv`;
- request any NCBI reference/checksum URL;
- download a human reference, create a human-genome index, or run real
  mapping;
- alter thresholds, assemblies, contig policy, sampling, mapper parameters,
  or resource ceilings;
- begin the largest-contig probe or any B2–B7 execution.

## Required return

Return:

1. correction commit hash and complete changed-file list;
2. itemized B1-F1–F6 resolution;
3. focused regression names/counts, including stderr-only cap, report retry,
   upstream-generation propagation, manifest drift, gate crossing, cleanup
   root/evidence, and every selection-record failure;
4. two full-suite results with pinned real binaries and real-binary smoke
   count;
5. `git diff --check` and staged-file audit results;
6. confirmation that the real CSV and all NCBI URLs were untouched;
7. any remaining gap—explicitly, without proceeding.

Stop after the local correction commit and end with exactly:

`Task 001B checkpoints B2–B7 were not started.`
