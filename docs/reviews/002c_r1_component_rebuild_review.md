# Task 002C-R1 review — components v2 direct-edge core

## Verdict

**Approve with bounded corrections.**

Commit `c1d61fb` implements the right scientific core: components v2 are
constructed from direct-search edges at all three protected widths, not from
the historical v1 cluster-membership TSVs.  The command builder delegates to
the frozen audit-search command, the direct-edge parser is strict and
deterministic, the component constructor preserves singletons and transitive
closure, and the synthetic legacy-omission regression makes the correction
observable.

The independently rerun focused command passed: **55 tests, 0 failures**.
No real-data or MMseqs2 execution is part of this review.

Three small corrections are required before acceptance.

## F1 — never trust a `frozenset` universe without validation

`parse_direct_edge_lines()` currently skips `validate_universe()` when its
`universe` argument is a `frozenset`.  A caller can therefore pass an empty
or malformed `frozenset` (for example an ID containing a tab/newline) and
bypass the public parser's canonical-universe contract.

Resolve by validating every public `universe` input, including a
`frozenset`, or by introducing a private, unforgeable already-validated type.
The simple unconditional validation is preferred at this checkpoint; R3 is
the appropriate place to optimize after profiling.

Add regressions proving that `parse_direct_edge_lines()` rejects empty and
malformed `frozenset` universes exactly as it rejects list inputs.

## F2 — bind the normalized exact/RC contribution by digest

`ComponentsV2Result.metadata` records only `exact_rc_edge_count`.  This is
not enough provenance for the later runner: two different exact/RC edge sets
can have the same count but yield different components.

After canonicalizing/de-duplicating exact/RC edges, compute a deterministic
SHA-256 over the same sorted two-column representation used for direct edges.
Include at least:

```text
exact_rc_edge_count
exact_rc_edges_sha256
```

in the v2 metadata.  The later runner will bind the source artifact's path,
byte size, and hash as well; this R1 digest binds the actual normalized
relation consumed by the component constructor.

Add tests proving the digest is invariant to input order/reversal/duplicates
and changes if the normalized exact/RC relation changes.

## F3 — do not state an unproven implementation mechanism

The new `docs/SPLITS.md` section and one test comment call v1 clustering
“greedy.”  The verified failure proves that v1 cluster membership was not a
complete closure of the direct audit relation; it does **not** yet isolate the
precise MMseqs2 internal mechanism responsible.

Replace that wording with a neutral, evidence-backed statement such as:

> “The v1 cluster result may leave sequences satisfying the direct predicate
> in different clusters; it is not a direct-edge list or a complete closure
> of the later audit relation.”

No change to frozen scientific settings, v1 historical artifacts, or the
R2/R3 boundary is authorized.

## Required return

Commit the narrowly corrected source/tests/documentation locally, without
pushing or merging.  Report the correction commit, changed files, focused
test command/results, a proof that all tests remain synthetic/no-subprocess,
and clean-worktree/diff-check evidence.

End with:

**Task 002C-R2 resource probing and Task 002C-R3 full edge discovery were not
started.**
