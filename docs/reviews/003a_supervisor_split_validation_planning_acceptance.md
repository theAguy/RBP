# Task 003A supervisor split-validation report — planning acceptance

**Verdict:** approved with bounded corrections, now reconciled  
**Execution decision:** implement and run locally; no Darwin, GPU, network, or
MMseqs2 execution  
**Next review:** one final acceptance review after figures, tables, and the
report are generated

## Decision

The Task 003A plan is scientifically proportionate and ready for
implementation. It creates descriptive evidence for the supervisor before any
baseline or model training, without changing the accepted split or inspecting
predictions.

The planning reviewer identified five blocking presentation/reproducibility
corrections. All five are incorporated in
`docs/tasks/003a_supervisor_split_validation_report.md`:

1. The recorded former-fold crossing values are explicitly labelled as
   computed against the rejected v1 grouping of 173,465 components. They are
   lower bounds under v2 because v2 only merges v1 components.
2. The rejected-v1 count of 4,792 is explicitly the first 500-nt
   train-to-validation search only. It involved 3,576 distinct rows; the audit
   stopped and 17 of 18 searches were not run.
3. The v1 membership and report are frozen by path, byte size, and SHA-256;
   the membership must reconstruct exactly 173,465 components.
4. The protected-v1 star-join count is excluded from direct-pair plots. The
   v1-to-v2 relationship is reported using component and row counts instead.
5. Sequence-composition effect wording, dependence limitations, homopolymer
   summaries, protein denominators, achieved row-fraction references, and the
   original 70/15/15 flag basis are prespecified.

The review's non-blocking clarification is also adopted: positive controls ran
once per width, so they will not be presented as 18 direction-specific
control runs.

## Additional strengthening adopted

Task 003A will preserve the accepted v1-based former-fold result and also
recompute that same legacy fold against final v2 membership. The new result is
accepted only if the pinned environment reproduces the recorded fold-0 train
and holdout index digests. This provides the supervisor with the most relevant
final-relation diagnostic without rewriting the historical v1 evidence.

## Boundary

No second planning-review cycle is needed. Implementation must remain within
the frozen Task 003A plan. The final acceptance review will verify numerical
reconciliation, figure/table provenance, denominator labels, and the wording
of allowed and disallowed claims.
