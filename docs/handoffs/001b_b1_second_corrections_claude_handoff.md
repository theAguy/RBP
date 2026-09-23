# Second correction handoff — Task 001B checkpoint B1

Claude, remain the implementation executor for **B1 only**. Read and correct
every blocker in `docs/reviews/001b_b1_correction_review.md`. This is a narrow
operational-safety round; do not change the scientific design and do not start
B2.

## Git and reading boundary

1. Verify `origin` is `https://github.com/theAguy/RBP.git`.
2. Work only on `issue-001b-coordinate-execution`.
3. Verify correction commit `11738d8` and this handoff commit are ancestors of
   `HEAD`.
4. Read, in order:
   - `docs/reviews/001b_b1_correction_review.md`;
   - `docs/tasks/001b_coordinate_feasibility_execution.md`;
   - `docs/reviews/001b_coordinate_execution_reconciliation.md`;
   - `docs/handoffs/001b_b1_corrections_claude_handoff.md`.

Commit the second correction locally on the same branch. Do not push, merge,
or rewrite prior history.

## Required implementation

Implement all B1-C1 through B1-C6 requirements. In particular:

- make the live NCBI checksum listing part of the guarded, fixture-tested
  acquisition contract and revalidate current accepted source/derived files;
- use genuinely transactional artifact generations for every multi-file set,
  so failure during promotion or record persistence preserves the prior set;
- enforce one combined 4-GiB live allowance per build and include source and
  derived roots in volume accounting;
- pin cleanup to the real configured root/reference, reject all symlinked path
  components, verify report/provenance evidence, and preserve pre-deletion
  hashes in the completed receipt;
- make checkpoint-stage compatibility executable, not a convention;
- wire current index manifest/file evidence into restart validity and reject
  the literal minimap2 multi-part warning;
- update `docs/COORDINATES.md` to describe the final behavior accurately.

Do not satisfy transactional tests by mocking away the promotion boundary.
Inject failures at each member/pointer/record transition and prove that the
previously accepted generation remains byte-for-byte intact and selected.

## Authorization boundary

You may use the existing isolated `rbpbench-coord-001b` environment and its
pinned binaries on tiny synthetic fixtures. Every downloader test must use a
local/injected transport.

You must not:

- open or hash `dataset_K562_multilabel_with_NEGs.csv`;
- request any NCBI human-reference or checksum URL;
- download a human reference, create a human-genome index, or run real
  mapping;
- alter scientific thresholds, source assemblies, contig policy, sampling,
  mapper parameters, or resource ceilings;
- begin the largest-contig SeqKit probe or any B2–B7 execution.

## Required verification

Return:

1. the correction commit hash and complete changed-file list;
2. an itemized B1-C1–C6 resolution;
3. focused regression names/counts, including each failure-injection point;
4. two complete-suite results with the pinned real binaries on `PATH` and the
   real-binary smoke-test count;
5. explicit evidence that the combined output cap, transactional generations,
   cleanup receipt, and checkpoint-stage rejection were exercised;
6. `git diff --check` and staged-file audit results;
7. confirmation that the real CSV and every NCBI URL were untouched;
8. any remaining gap, without proceeding further.

Stop after the local correction commit and end with exactly:

`Task 001B checkpoints B2–B7 were not started.`
