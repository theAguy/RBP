# Task 002C planning-review reconciliation

## Verdict

**Approved with bounded corrections, reconciled.** The second reviewer
approved the deterministic assignment objective, hard-floor architecture,
legacy-fold separation, exact/reverse-complement audit, restart structure, and
local-first execution boundary. Checkpoint 002C-1 may implement and test the
pipeline using synthetic fixtures only. Real assignment and every real-data
audit remain unauthorized until 002C-1 is accepted.

## Accepted corrections

### Both MMseqs2 search directions are required

The identity and bidirectional-coverage formulas are symmetric, but MMseqs2's
k-mer prefilter and heuristic search are not documented as invariant to
swapping query and target databases. One direction could therefore omit a
qualifying cross-partition match and falsely support a zero-leakage claim.

For each of three widths and three unordered partition pairs, Task 002C now
runs both ordered directions: 18 directed searches. Every selection-record key
and restart fingerprint includes the ordered query and target identities, so
one direction can never satisfy the reverse direction.

### Legacy leakage results require denominators

Raw counts alone do not communicate severity. Crossing-component, crossing-
row, directly edge-matched holdout, and exact/reverse-complement results now
include explicit rates. Row-level rates use their own training or holdout
denominators; the component rate uses components represented in the holdout;
violating pair counts remain raw alongside affected-holdout-row rates.

### Bounded repair must exercise a multi-step feasible case

The approved local repair is fail-closed but not a complete global solver: a
too-small bound could reject a feasible assignment. The existing requirement
to version a generous maximum remains, and 002C-1 must include a feasible
fixture requiring more than one move/swap. Failure to find a valid real
assignment still stops execution; it never permits a component split or a
weaker floor.

## Scope boundary

The corrections do not change component membership, target fractions, label
interpretation, evaluation floors, similarity thresholds, or resource gates.
They do not authorize real CSV access, real assignment, MMseqs2 execution,
baselines, models, coordinates, or another clustering method during 002C-1.
