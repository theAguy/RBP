# Task 004A-3C-1 implementation review request

Please statically review the synthetic-only 004A-3C-1 implementation against
`docs/tasks/004a3c_environment_and_bundle.md` and
`docs/reviews/004a3c_planning_reconciliation.md`.

Return one verdict: Approve, Approve with bounded corrections, or Stop.

Check specifically:

1. the G1 solve, explicit-lock recreation and final package/build assertions;
2. G2 manifest completeness, post-suite revalidation, `--copy` and read-only
   ordering;
3. G3 CPU routing, channel reachability, host compatibility and failure return;
4. G4 pre-data authentication, source/environment binding, exact accepted
   matrix check, transaction and resource gates;
5. G5 `gpu:L40:1` plus `nlp-l40-2` and exact L40S runtime refusal;
6. whether the synthetic regressions cover the failure modes without weakening
   any frozen scientific constant.

This is a static review. Do not execute scripts, access real/ignored data,
query Newton, install packages, use CUDA, submit Slurm or authorize 3C-2/3C-3.
