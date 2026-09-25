# Task 002A sequence-partition pipeline acceptance

## Verdict

**Accepted.** Commit `b670b09` resolves the bounded C1-C5 correction on top of
the original implementation commit `6321356`. Checkpoint 002A is complete.
This acceptance does not authorize checkpoint 002B or any access to the real
361,180-row dataset.

## Independent review

The reviewer verified that:

- `cluster_command()` and `audit_search_command()` require a protected width
  and fail before execution for any other width;
- both commands pin `--min-seq-id 0.90`, bidirectional `--cov-mode 0`, the
  width-specific `-c 0.80` or `0.95`, and `--max-seqs 361180` alongside the
  previously accepted flags;
- the command API does not expose arbitrary identity or coverage overrides;
- repeated same-tool invocations receive distinct stdout/stderr paths, so an
  earlier command record is not invalidated by a later call;
- audit edges with an endpoint outside the closed assignment universe fail
  closed; and
- no production caller remains on the old width-less command interface.

The reviewer independently ran:

- command and audit tests: **38 passed plus 6 subtests**; and
- the real pinned-MMseqs2 fixture suite: **12 passed plus 3 subtests**.

The real-binary tests demonstrate above/below-threshold behavior for identity
and width-specific coverage, exact and reverse-complement grouping, explicit
both-strand audit search, and the binary's effective identity, coverage, and
result-ceiling settings.

## Full-suite disclosure

The executor's clean-checkout full suite reported 615 collected tests with
five failures in legacy Task 001 coordinate tests. The same five failures were
reproduced on parent `fa7d5e4`, and the correction changed no coordinate file.
They are therefore recorded but do not block acceptance of the isolated Task
002A implementation. Coordinate work remains closed/deferred.

## Boundary for the next checkpoint

Checkpoint 002B still requires a separate reviewed execution handoff. Its
scope is real-data decoding, three sequential MMseqs2 clustering runs, union
of the resulting memberships, and the component-size/giant-component report
only. It must not assign train/validation/test partitions. The explicit
`--max-seqs 361180` setting may increase resource demand; unsafe memory, disk,
or runtime is a stop condition rather than permission to weaken the frozen
scientific rule.
