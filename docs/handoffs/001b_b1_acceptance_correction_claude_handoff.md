# Acceptance correction handoff — Task 001B checkpoint B1

Claude, remain the executor for **B1 only**. Make the narrowly scoped
authoritative-report-consumer correction in
`docs/reviews/001b_b1_final_correction_review.md`. Do not reopen the completed
B1-F1–F6 design and do not begin B2.

## Git and required reading

1. Verify `origin` is `https://github.com/theAguy/RBP.git`.
2. Work only on `issue-001b-coordinate-execution`.
3. Verify `905f0bd`, `1138022`, and this handoff commit are ancestors of
   `HEAD`.
4. Read, in order:
   - `docs/reviews/001b_b1_final_correction_review.md`;
   - `docs/reviews/001b_b1_second_correction_review.md`;
   - `docs/tasks/001b_coordinate_feasibility_execution.md`;
   - `docs/reviews/001b_coordinate_execution_reconciliation.md`.

Commit locally on the same branch. Do not push, merge, or rewrite history.

## Implementation boundary

Make `report_state.json` the sole machine-authoritative selector for every
per-build report artifact:

- implement a shared fail-closed accepted-report loader/validator;
- have combined reporting read the selected report JSON and mappings table;
- have provenance hash and attribute the selected report JSON, Markdown,
  mappings, and reference-index paths;
- have cleanup read and validate the selected report and ensure its provenance
  evidence identifies those exact selected paths/hashes;
- include accepted report-generation digests in combined-report restart
  validity, and validate the selected states before allowing a skip;
- retain fixed-path mirrors only as optional human conveniences; their
  absence, staleness, corruption, or partial refresh must not affect machine
  correctness.

Do not move the atomic report selection later merely to include mirror
writes. The pointer commit must remain the complete transaction; downstream
consumers must follow it.

## Required regressions

Add focused tests proving:

1. a valid selected generation remains usable when every mirror is missing or
   corrupt;
2. interruption immediately after the pointer commit and between each mirror
   write cannot make combined reporting, provenance, or cleanup consume stale
   evidence;
3. selected-generation tampering fails closed even when mirrors look valid;
4. a forced same-input report rebuild with a new generation digest invalidates
   a prior combined-report completion;
5. provenance records the exact selected-generation paths and hashes;
6. cleanup authorizes from the same selected report/provenance evidence and is
   independent of mirrors.

Each regression must fail on `1138022` for the intended reason. If the
optional index-digest normalization is attempted, isolate it and add a real
two-generation byte-equivalence regression; otherwise leave it unchanged.

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
2. itemized resolution for combined reporting, provenance, cleanup, and
   combined-report restart validity;
3. focused regression names/counts and confirmation each fails on `1138022`;
4. two full-suite results with pinned real binaries and real-binary smoke
   count;
5. `git diff --check` and staged-file audit results;
6. confirmation that the real CSV and all NCBI URLs were untouched;
7. any remaining gap—explicitly, without proceeding.

Stop after the local correction commit and end with exactly:

`Task 001B checkpoints B2–B7 were not started.`
