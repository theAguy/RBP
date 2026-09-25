# Second-review request — Task 002 sequence-grouped partitions

Claude, review only
`docs/tasks/002_sequence_clustered_partitions.md`. Do not edit files, install
MMseqs2, open the real CSV, generate sequences, construct partitions, or run
models.

## Context

The preferred coordinate path is deferred because the frozen single-part
minimap2 hg38 splice index exceeded the available 16-GiB host; standard Colab
provided only 12.7 GiB. The project owner chose the already documented
sequence-clustering fallback so optional coordinate metadata does not delay the
core model comparison.

The submitted notebook used the first 80/20 fold from a row-level five-fold
multilabel split. That split balances labels but cannot prevent similar or
overlapping sequence windows from crossing its boundary. Task 002 proposes one
locked 70/15/15 split made from indivisible sequence-similarity components.

## Questions requiring a decision

1. Are the proposed three representations (500, centered 251, centered 101)
   sufficient for the planned window comparison without unnecessary grouping?
2. Are 90% true identity with 80% coverage for 500 nt and 95% coverage for the
   centered windows defensible leakage-control thresholds?
3. Does the MMseqs2 command need any additional explicit flag to guarantee
   nucleotide-versus-nucleotide, both-strand, exact-identity behavior in the
   pinned release?
4. Is connected-component transitivity appropriate, and are the 5% largest-
   component / 20% top-20 stop gates adequate protection against component
   chaining?
5. Is a single locked 70/15/15 split preferable here to expensive cross-
   validation, given that multiple training seeds will later quantify model
   variability?
6. Is using known labels only to balance already-frozen components free of
   outcome leakage, and are the 30-positive/30-negative validation/test minima
   sufficient for per-protein AUROC?
7. Is the independent post-split search strong enough to substantiate zero
   cross-partition violations at the frozen rule?
8. Identify any correctness blocker that would invalidate the scientific
   comparison. Separate blockers from optional robustness improvements.

Return one verdict: `approve`, `approve with bounded corrections`, or `reject`,
followed by an itemized answer. Keep corrections limited to what is necessary
for valid leakage-safe partitions. Do not reopen coordinate recovery or expand
this task into baselines/model training.
