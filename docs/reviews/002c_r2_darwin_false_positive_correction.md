# Task 002C-R2 Darwin false-positive correction

## Evidence and verdict

The first Darwin job is a valid, checksum-complete `STOPPED` return, but it is
not accepted R2 resource evidence. The width-500 MMseqs2 search exited zero,
its stderr was empty, and its stdout showed a normal single prefilter step
(`step 1 of 1`). The old regular expression nevertheless matched:

- the verbose parameter line `Split database 0`;
- the verbose parameter line `Split memory limit 0`; and
- ordinary internal commands and paths containing `*_seqs_split` and
  `--split-memory-limit 0`.

The runner stopped before `createtsv`, result reconciliation and projection
gates. No width was accepted and R3 remains unauthorized. The bound evidence
is recorded in
`manifests/sequence_r2_darwin_false_positive_stop.json`.

## Corrected operational policy

The probe now separates MMseqs2 text into three classes:

1. Normal verbose parameters, internal commands and paths are ignored.
2. Generic `Warning:` lines are advisory. They are retained in the per-step
   record, raw logs and sanitized final return, and the remaining fixed stages
   continue so the warning can be reviewed in context at the end.
3. A nonzero exit or concrete `Error:`, OOM, cannot-fit, `bad_alloc`,
   truncation, multi-part, greater-than-one split-count, or unsafe
   split-memory override diagnostic is fatal and stops before the next child.

All live resource gates, input checks, result reconciliation, projection
limits, scientific flags and the no-R3 boundary are unchanged. This is the
bounded tolerance appropriate for reducing handoff churn: accumulate
ambiguous text, but never accumulate objective corruption or resource failure.

The exact relevant Darwin/MMseqs2 output is represented by the regression
fixture
`tests/fixtures/splits/mmseqs18_darwin_probe500_diagnostics_excerpt.txt`.
Synthetic tests also prove that advisory warnings survive into the final
return and that the fatal classes still stop execution.

## Operator improvement

The submit wrapper accepts an optional validated `RBP_SLURM_MAIL_USER` and, if
set, supplies fixed Slurm `BEGIN,END,FAIL` notifications. No GPU option is
added. The CPU job must be submitted from Darwin; the historical `newton`
file/module names are retained only for compatibility.

## Acceptance boundary

This correction authorizes a fresh, single-use R2 package and one new Darwin
submission after tests and archive verification. It does not authorize reuse
of the stopped extraction, manual MMseqs2 commands, R3, component construction,
partition assignment or model work.
