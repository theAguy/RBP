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
