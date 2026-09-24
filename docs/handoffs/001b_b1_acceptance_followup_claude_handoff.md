# Final acceptance follow-up — Task 001B checkpoint B1

Claude, remain the executor for **B1 only**. Correct only A1 and A2 in
`docs/reviews/001b_b1_acceptance_correction_review.md`. The mirror-independence
work in `46d857f` is accepted; do not redesign or reopen it, and do not begin
B2.

## Git and required reading

1. Work only on `issue-001b-coordinate-execution` with the configured RBP
   origin.
2. Verify `46d857f` and this handoff commit are ancestors of `HEAD`.
3. Read:
   - `docs/reviews/001b_b1_acceptance_correction_review.md`;
   - `docs/reviews/001b_b1_final_correction_review.md`;
   - `docs/tasks/001b_coordinate_feasibility_execution.md`.

Commit locally on the same branch. Do not push, merge, or rewrite history.

## A1 — Preserve the upstream generation chain through combined reporting

- Supply current per-build align and exact-match records to the combined
  report path and shared accepted-report validator.
- Use the upstream-aware validator before both execution and restart skip.
- Ensure combined-report restart validity changes when current align or
  exact-match generation digests change, even if the selected report has not
  yet been rerun.
- Refuse a stale report and tell the operator to rerun that build's report.
- Test both align-generation and exact-match-generation drift through the
  actual runner path, including a previously completed combined report.

## A2 — Complete selected reference-index provenance

- Record the selected reference-index artifact's exact path, SHA-256, and byte
  size in the build's provenance generated-artifact section.
- Retain the parsed reference-index diagnostic separately if desired.
- Require cleanup to cross-check the selected reference-index path/hash
  against provenance whenever it exists.
- Preserve valid `None` behavior for a non-evaluated report that has no
  reference-index artifact.
- Test valid attribution, missing/mismatched provenance, selected artifact
  tampering, and the no-reference-index case.

## Authorization boundary

Use only tiny synthetic fixtures and the existing isolated environment. Do
not open or hash the real dataset; request an NCBI URL; download/index a human
reference; run real mapping; alter scientific parameters; push; merge; or
begin B2–B7.

## Required return

Return:

1. correction commit and changed-file list;
2. A1/A2 resolution;
3. focused tests and proof they fail on `46d857f`;
4. two full-suite results and real-binary smoke count;
5. `git diff --check` and staged-file audit;
6. confirmation that the real CSV and NCBI URLs were untouched;
7. any remaining gap.

Stop after the local commit and end with exactly:

`Task 001B checkpoints B2–B7 were not started.`
