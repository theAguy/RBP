# Task 003A supervisor split-validation report — planning review request

**Status:** reviewed; verdict "Approve with bounded corrections"; C1-C5
reconciled in the task plan before implementation

## Requested verdict

Return one of:

- **Approve**;
- **Approve with bounded corrections**; or
- **Reject**, only for a scientific-validity, denominator, reproducibility, or
  misleading-communication problem that prevents implementation.

## Required reading

1. `docs/tasks/003a_supervisor_split_validation_report.md`
2. `docs/SEQUENCE_SPLIT_AUDIT_EXPLAINER.md`
3. `docs/reviews/002c_final_sequence_partition_acceptance.md`
4. `manifests/sequence_partitions_002c_v2.json`
5. `docs/reviews/002c2c_non_mmseqs_diagnostics_acceptance.md`
6. `docs/reviews/002c3_cross_partition_failure_and_component_rebuild_plan.md`

## Review questions

1. Do the proposed figures correctly distinguish the former row split, the
   rejected v1 component split, and the accepted v2 component split?
2. Are the denominators and proposed panel separation sufficient to prevent a
   misleading visual comparison between the former 63.593% affected-holdout
   rate, the v1 4,792 direct pairs, and the final zero-hit audit?
3. Is the proposed per-protein balance presentation correct—especially the
   definition of a protein/class/partition cell and the distinction between
   fraction balance and the 30-count support floor?
4. Are component-size, edge-overlap, and v1/v2 summaries scientifically
   interpretable without presenting order-dependent union counts as unique
   causal contributions?
5. Are GC fraction, normalized mononucleotide entropy, and maximum homopolymer
   length reasonable first descriptive sequence-composition checks? Is the
   proposed emphasis on effect sizes over large-sample p-values sufficient?
6. Is the eight-figure main set sufficient and proportionate for a supervisor
   to judge that the split-validation work is rigorous?
7. Does the plan preserve the locked-test boundary and avoid training or model
   selection?
8. Is local streaming execution appropriate, with no scientific reason to use
   Darwin?
9. Identify only blocking issues. Defer optional additional plots, styling
   preferences, dashboard work, and reusable general-purpose reporting
   infrastructure.

## Scope restriction

This is a plan review only. Do not implement code, open the 724-MB CSV, extract
large artifacts, launch MMseqs2, train a model, create figures, or modify the
split. The desired output is a concise scientific review with exact bounded
corrections if needed.

## Reconciliation of the review verdict

The five blocking corrections were accepted without expanding Task 003A:

1. Former-fold crossing values are now labelled as v1-grouping results and as
   lower bounds under v2; Task 003A will separately recompute them against v2
   only after reproducing the recorded legacy-fold index digests.
2. The 4,792 result is labelled as the first 500-nt train-to-validation search
   only, involving 3,576 distinct rows; the audit stopped and 17/18 searches
   did not run, so it is a lower bound.
3. The v1 membership and report are pinned by exact path, size, and SHA-256,
   and 173,465 components must be reconstructed before use.
4. The protected-v1 star-join count is excluded from pair-count and overlap
   displays; v1 protection is summarized only with component and row counts.
5. Composition effect wording, component-dependence handling, homopolymer
   summaries, heatmap denominators, achieved-fraction references, and the
   original 70/15/15 flag basis are prespecified.

The non-blocking clarification was also adopted: positive-control status is
shown per width, not repeated as if a separate control ran for every directed
search. Per the plan's review boundary, no second planning-review loop is
required.
