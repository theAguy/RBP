# Task 002A implementation review

## Verdict

**Correction required before acceptance.** The architecture is generally
appropriate and the Python-only component, hashing, decoding, assignment, and
reporting helpers are a useful foundation. The implementation must not advance
to 002B because its MMseqs2 commands do not yet implement the central reviewed
similarity rule.

This review is intentionally bounded. It does not reopen coordinates, add a
second clustering package, redesign partition assignment, or authorize access
to the real dataset.

## Blocking findings

### 1. The required identity and coverage thresholds are absent

`cluster_command()` and `audit_search_command()` do not pass
`--min-seq-id 0.90` or `-c`. They also have no width argument from which the
500-nt `0.80` versus 251/101-nt `0.95` coverage rule could be selected.

This is a real behavior difference, not only incomplete provenance. With the
current command, the pinned binary reports:

- clustering sequence-identity threshold `0.0` and coverage `0.8`; and
- search sequence-identity threshold `0.0` and coverage `0.0`.

Therefore the current 251/101 clustering and every audit search can accept
matches outside the frozen rule.

### 2. The real-binary fixtures do not test the thresholds

The real clustering fixture contains exact/reverse-complement duplicates and
an unrelated sequence. Those cases establish nucleotide and strand behavior,
but they pass under many incorrect identity/coverage settings. The component
tests inject already-decided edges rather than asking MMseqs2 to discover the
planned shifted and near-identical matches. Consequently all current tests can
pass while finding 1 remains present.

### 3. MMseqs2's hit ceiling remains default-dependent

The installed binary documents `--max-seqs` as affecting sensitivity, with a
small workflow default. A capped qualifying edge list can fragment a true
connected component. The full dataset universe is fixed at 361,180 rows, so
both clustering and audit search must pin `--max-seqs 361180`. If the real run
cannot support that setting, it must stop for review rather than silently use a
smaller cap.

## Small safety corrections included in the same pass

- Command logs currently use fixed filenames such as
  `mmseqs_createdb.stdout.log`. Two same-tool calls in one log directory
  overwrite earlier evidence while the earlier returned provenance still
  points to that path. Give every invocation non-colliding log paths and prove
  all recorded hashes remain verifiable.
- `cross_partition_violations()` currently skips an audit endpoint absent from
  the assignment universe. For the final closed 361,180-row audit, an unknown
  endpoint is evidence corruption and must fail closed, not disappear.

## Explicit deferrals

The full 002B/002C runner, real-data resource preflight, selection records,
partition-optimization refinements, and real output-generation transactions
remain later-checkpoint work. They are not reasons to prolong this correction.

## Acceptance after correction

Accept 002A when the corrected builders encode the exact per-width rule, the
real pinned binary separates deliberately below-threshold fixtures while
finding above-threshold/shifted/reverse-complement fixtures, the hit ceiling is
explicit, log evidence is non-overwriting, strict audit reconciliation is
tested, and the synthetic-only suite is green. Do not start 002B in the same
turn.
