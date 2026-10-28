# Task 003A supervisor split-validation report — planning review request

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
