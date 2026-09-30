# Task 002C-2A planning-review reconciliation

## Verdict

**Approved with one bounded correction, reconciled.** The second reviewer
confirmed that the retained MMseqs2 `createtsv` files are connected-component
cluster memberships rather than complete or necessarily direct similarity-edge
lists. The proposed per-width cluster-boundary diagnostic is scientifically
honest, useful, and sufficiently normalized. Direct streaming of the accepted
TSVs and the planned evidence bindings are appropriate.

Task 002C-2A may be implemented and may validate only its explicitly frozen
returned membership evidence. Real CSV access, partition assignment, legacy
fold execution, exact/RC audit execution, MMseqs2 execution, and model work
remain unauthorized.

## Accepted bounded correction

The executor must replace—not merely annotate—the obsolete parent-plan bullet
requiring a directly recorded Task 002B similarity edge. The replacement must
name the per-width cluster-boundary counts and denominators from Task 002C-2A.
It must also remove the temporary warning and correct any downstream wording
that could leave a later executor believing the retired direct-edge metric is
still owed.

This prevents a later Task 002C-2 or finalization run from treating an
unsupported historical requirement as active after the implementation has
moved to cluster-membership evidence.

## Scientific interpretation

For a protected width, membership in a cluster spanning legacy train and
holdout means that the two sides are connected directly or transitively under
the frozen Task 002B clustering relation. It does not establish a direct
pairwise alignment for every affected row. Long transitive chains can make the
diagnostic inclusive; this limitation must remain explicit in reports.

The later Task 002C-3 fresh directed MMseqs2 searches remain the independent
pairwise zero-hit acceptance test for the new split.

## Scope boundary

No threshold, cluster, component, assignment rule, resource gate, or model
decision changes. The checkpoint remains one bounded local unit: correct the
schema and terminology, validate and bind the three returned membership TSVs,
write one small sanitized manifest, and stop before any real Task 002C
scientific execution.
