# Task 004A-3C-2 handoff correction review request

Please review only corrections D1-D3 to
`docs/handoffs/004a3c2_darwin_environment_execution.md` relative to `b90b35a`.

- D1 must resolve Conda to an executable absolute path, verify it, verify
  system Python, and require a non-empty public-partition result before the one
  allowed submission.
- D2 must save scheduler accounting with routing, resources, elapsed time and
  peak RSS, and download that evidence for return review.
- D3 must record Darwin's physical home path and free space, require at least
  50 GiB, prove Newton sees the same checkout at the same home path, and build
  download paths from the recorded value rather than `/home/guy.assa`.

Confirm that the document regression fails on `b90b35a` and passes on the
correction. Return Approve, Approve with bounded corrections, or Stop.

Reported verification:

- the new document regression fails on `b90b35a` at the first missing D1
  prerequisite;
- corrected focused run 1: 110 passed, 73 subtests, 2 pre-existing warnings,
  75.61 seconds;
- corrected focused run 2: 110 passed, 73 subtests, 2 pre-existing warnings,
  74.66 seconds;
- `git diff --check` is clean.

Static review only. Do not connect, install, submit, access data or authorize
execution.

## E1 follow-up

The first D1-D3 review approved those corrections but found that enabling
`set -Eeuo pipefail` in the operator's live SSH shell could disconnect the
session and lose the validated variables. The handoff now:

- does not enable strict mode in the interactive shell;
- sets `PREFLIGHT_OK` only after rechecking every prerequisite, the newly
  created checkout and Newton visibility;
- chains the actual submit command behind a fresh absolute/executable Conda
  guard, the evidence file and `PREFLIGHT_OK`;
- instructs the operator to repeat the complete preflight after any disconnect;
- verifies that saved `sacct` evidence contains the requested job row.

Please include E1 in the same static correction verdict.

E1 verification:

- the extended regression fails on parent `7d03b0d` because strict mode is
  still present there;
- corrected `test_rescnn_004a3.py` run 1: 46 passed, 53 subtests, one
  pre-existing warning, 6.73 seconds;
- corrected run 2: 46 passed, 53 subtests, one pre-existing warning,
  6.11 seconds;
- the earlier post-D1-D3 complete five-file runs remain 110 passed and 73
  subtests twice.

## F1 follow-up

The E1 review approved D1-D3 and E1 but found that the exported approval flag
remained reusable after the submission command. The handoff now:

- records the submission command's status and unsets
  `RBP_004A3_PREFLIGHT_OK` immediately afterward, whether submission succeeds
  or fails;
- tells the operator that a disconnect after cloning ends the checkpoint and
  that the checkout must not be deleted or reused;
- keeps checkout entry and detached checkout inside the newly-created clone
  branch, so a pre-existing directory is not entered or edited.

The extended document regression requires the approval-token consumption to
occur after the submit call and checks the existing-checkout stop language.
Please include F1 in the same static correction verdict.

F1 verification:

- the extended regression fails on parent `caab8d3` because no approval-token
  `unset` occurs after the submit call;
- corrected `test_rescnn_004a3.py` run 1: 46 passed, 53 subtests, one
  pre-existing warning, 7.17 seconds;
- corrected run 2: 46 passed, 53 subtests, one pre-existing warning,
  6.74 seconds.
- complete five-file focused run 1: 110 passed, 73 subtests, two pre-existing
  warnings, 76.04 seconds;
- complete five-file focused run 2: 110 passed, 73 subtests, two pre-existing
  warnings, 72.19 seconds.
