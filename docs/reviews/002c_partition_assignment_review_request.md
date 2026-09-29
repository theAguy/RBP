# Task 002C planning review request

## Reviewer role and boundary

Act as the independent scientific/methodological reviewer for
`docs/tasks/002c_partition_assignment_and_audit.md`. Review the plan only.
Do not edit code, open the real CSV, execute assignment, run MMseqs2, install
packages, or start Task 002C.

The project owner wants almost all work to run on the current 16-GiB Mac. A
clean handoff to a collaborator's 64-GiB Apple-Silicon Mac is permitted only
for the fresh MMseqs2 audit if the current Mac fails the unchanged 10-GiB
available-memory gate.

## Accepted context

- Task 002B is accepted in
  `docs/reviews/002b_real_sequence_grouping_acceptance.md`.
- The fixed universe has 361,180 rows and 173,465 indivisible components.
- The largest component is 611 rows; no giant-component gate tripped.
- The former notebook used fold 0 from
  `MultilabelStratifiedKFold(n_splits=5, shuffle=True, random_state=42)` over
  `targets * masks`, which encodes positives but not known negatives.
- Existing `assignment.assign_partitions()` was fixture-tested but a read-only
  real-data feasibility pass showed ten 30/30 floor failures because its raw
  absolute row deficit dominates label deficits. Every protein has at least
  506 observations in each known class, and component-level distribution is
  sufficient for the floor; a scale-normalized scratch assignment passed all
  floors but is not an accepted result.
- No model output or performance result has been inspected for Task 002.

## Questions requiring an explicit answer

1. Is the frozen deterministic assignment objective scientifically defensible:
   normalized dimensions, row objective weighted equally to the 244 label
   objectives in aggregate, component-difficulty ordering, and bounded
   lexicographic whole-component repair?
2. Does the plan prevent post-hoc tuning while still giving the hard 30/30
   floors genuine priority? Identify any exact failure mode and the smallest
   correction needed.
3. Is the legacy fold reproduction sufficiently exact and properly separated
   from the new assignment? Should its leakage comparison use any additional
   denominator that is necessary for an honest conclusion?
4. Is one directed fresh MMseqs2 search for each unordered partition pair
   sufficient under the symmetric identity/coverage rule, or must both query-
   target directions be executed? Give a concrete reason rather than a general
   preference.
5. Are the exact/RC and MMseqs2 audit endpoints, self-hit handling, closed
   universe checks, and zero-hit acceptance rule adequate?
6. Is the local-first checkpoint boundary safe? In particular, can assignment,
   legacy reconstruction, and exact/RC audit remain local while only the fresh
   MMseqs2 search is handed off if memory is insufficient?
7. Are restart/provenance requirements strong enough to prevent a stale
   component, label file, assignment, or audit from being silently accepted?
8. Is any issue genuinely blocking before 002C-1 implementation? Distinguish
   blocking scientific/correctness issues from optional engineering work.

## Requested verdict

Return one of:

- **Approve**;
- **Approve with bounded corrections**; or
- **Stop**, naming the precise scientific blocker.

For each required correction, state the failure it prevents and the earliest
checkpoint that needs it. Do not expand scope into coordinates, a second
clustering package, baselines, or model training. One review/reconciliation
round is the intended limit unless a correction reveals a new scientific
blocker.
