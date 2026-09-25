# Task 002 second-review reconciliation

## Verdict

**Approve with bounded corrections, reconciled.** Task 002 may proceed only to
checkpoint 002A. Coordinates remain deferred, and no real dataset or model work
is authorized by this reconciliation.

## Accepted findings

1. The 500/251/101 union is appropriate because those are the actual planned
   model widths. The manifest will state that unplanned future widths are not
   explicitly protected.
2. The reviewed 90% identity and 80%/95% coverage thresholds are accepted.
   They protect shifted/near-identical windows without grouping sequences merely
   because they share a short RBP motif.
3. MMseqs2 behavior is now explicit rather than default-dependent. The type-2
   input database fixes nucleotide clustering; clustering pins true identity,
   bidirectional coverage, E-value, disabled masking, sensitivity, connected
   components, and single-step graph construction. Fresh audit searches also
   pin nucleotide search type 3 and strand 2. MMseqs2 does not expose those two
   options on `cluster`, so reverse-complement fixture behavior is required
   instead of specifying unsupported flags. Version `18.8cc5c`, osx-64 build
   `h8b377d6_0`, is pinned.
4. Connected components and the 5% single-component / 20% top-20 gates are
   accepted. A gate failure will include diagnostic composition rather than a
   bare stop.
5. One locked 70/15/15 split is accepted instead of cross-validation. Multiple
   model seeds will later measure training variability while the test set stays
   untouched.
6. Label-blind grouping followed by label-aware whole-component balancing is
   accepted. The 30-positive/30-negative evaluation floor is a viability floor,
   not a precision guarantee; low-count proteins will be flagged for confidence
   intervals later.
7. The post-split audit will use fresh MMseqs2 search executions with the fully
   pinned semantics plus tool-independent canonical hashes for exact/reverse-
   complement duplicates at all three widths. It will not claim independent
   software for near-similarity detection.

## Scope control

No optional second clustering package, coordinate retry, baseline, training
run, threshold tuning, or full-data access is added to 002A. The work remains
split into implementation, real grouping, and final partition checkpoints.
