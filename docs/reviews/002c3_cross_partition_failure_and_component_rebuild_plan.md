# Task 002C-3 — Cross-partition failure and component-rebuild plan

## Status

**The Task 002C v1 assignment is rejected for model evaluation.**  It remains
preserved as historical diagnostic evidence; it must not be edited, deleted,
or presented as leakage-safe.

The portable audit run on 2026-10-04 stopped correctly at its first directed
search:

```text
width: 500 nt
direction: train -> validation
qualifying hits: 4,792
criterion: >=90% identity and >=80% bidirectional coverage, both strands
```

The return package is
`artifacts/teammate_run_results/RBP_002C3_RETURN_20261004T101131Z_Mayans-MBP.zip`.
Its ZIP integrity check and all 67 recorded file checksums were independently
verified.  The package used the pinned native arm64 MMseqs2 18.8cc5c binary,
with the expected hash, and the frozen audit command.  This is therefore a
scientific result, not a packaging, host, or command-line failure.

## What failed

The v1 partition assignment kept every **v1 component** together.  However,
the later direct MMseqs2 search found sequence pairs that satisfy the declared
similarity rule but belong to different v1 components and different partitions.
Thus, v1 components are not a complete closure of the leakage relation.

The first directed result contains:

| Quantity | Count |
| --- | ---: |
| Qualifying train-to-validation pairs | 4,792 |
| Distinct train query rows | 1,400 |
| Distinct validation target rows | 2,176 |
| Distinct rows involved | 3,576 |
| Existing v1 component-to-component links | 737 |
| Existing v1 components involved | 1,351 |
| Connected groups induced by those links | 614 |
| Largest induced group | 6 existing components |

All reported query IDs are in v1 train, all target IDs are in v1 validation,
and no reported pair was already in the same v1 component.  The figures above
cover only the *first* of 18 directed audits, so they are a lower bound on the
problem.

The original Task 002B construction used MMseqs2 connected-component
clustering with `--single-step-clustering 1`; Task 002C uses a direct
`mmseqs search` for leakage audit.  The observed result proves that the former
output is not sufficient as a closure of the latter relation.  It would be
unsafe to claim a more specific implementation cause without a dedicated
experiment, and it would be scientifically wrong to weaken the audit merely
to retain v1.

## Immutable decisions

The rebuild must retain all of the following:

- The frozen dataset, sequence decoding, and canonical `row_<n>` IDs.
- The three protected widths: 500, 251, and 101 nt.
- The similarity predicate: 90% identity; coverage 80% at 500 nt and 95% at
  251/101 nt; coverage mode 0; both strands; alignment mode 3; E-value 1000;
  masking disabled; sensitivity 7.5; and `--max-seqs 361180`.
- Exact and reverse-complement edges as independent protections.
- Whole-component assignment and the 70/15/15 target with the existing
  per-protein known-positive/known-negative floors.
- The zero-hit requirement for all 18 directed fresh audits before any model,
  baseline, or comparison result is accepted.

No parameter may be relaxed in response to the failure.

## Corrective scientific design: components v2

The direct search relation used by the audit becomes the relation used for
component construction.

For each protected width, run the frozen `mmseqs search` over the full decoded
FASTA against itself.  Convert its `createtsv` output into canonical undirected
edges after removing self-pairs and validating that every endpoint is a unique
canonical ID.  Then take the union of:

1. all three width-specific direct-search edge sets; and
2. the independently generated exact/reverse-complement edge sets.

Connected components of this union are **components v2**.  The v2 assignment
will place each whole v2 component in exactly one partition.

This is intentionally different from merely merging the 4,792 discovered
pairs: that would leave unknown relations in the 17 unrun directions and may
create new cross-partition relations after reassignment.  It is also stronger
than removing `--single-step-clustering` and hoping the output agrees with the
audit.  A direct search with the same frozen rule makes the construction
auditable, while the final independent audits remain the acceptance test.

## Execution checkpoints

### R1 — implementation and synthetic proof

Implement a separate v2 pipeline and configuration.  It must not mutate
Task 002B/002C v1 records or artifacts.

Required tests include:

- direct-search edge parsing, self-pair removal, canonicalization, duplicate
  collapse, malformed/foreign-ID rejection, and both-orientation handling;
- transitive component construction across widths and exact/RC edges;
- fingerprint/provenance binding for decoded FASTAs, binary, frozen flags,
  each edge artifact, and every component artifact;
- transactional/restart behavior; and
- a synthetic regression where v1-style clustering omits a qualifying edge
  but v2 direct-search components keep its endpoints together.

No real data or MMseqs2 full-dataset execution is authorized at R1.

### R2 — resource probe and run authorization

On the high-memory host, run bounded resource probes using the v2 command and
the real decoded FASTAs.  Record RAM, disk, runtime, result size, and output
growth separately for all three widths.  Do not alter scientific flags to meet
a resource limit.

Before a full run, require a reviewed projection and hard stop conditions for
disk, RAM, wall time, and result size.  A host with 64 GiB RAM is the preferred
executor.  A failed resource gate is a stop, not permission to truncate,
sample, or lower sensitivity.

### R3 — full edge discovery and components v2

Run one full all-vs-all direct search per width, retain normalized edge
evidence and content hashes, build components v2, and emit only sanitized
summary/manifest material to Git.  The raw search artifacts remain ignored.

Acceptance requires full-universe reconciliation at every width, a complete
edge inventory, a deterministic repeated component digest, and an explicit
comparison with v1 (component count, largest component, rows/components
merged, and giant-component gates).

### R4 — v2 partition assignment

Run the existing label-aware assignment logic only on components v2.  It must
produce a fresh `sequence_partitions_002c_v2` output root and a new sanitized
assignment manifest.  Verify no component is split, partition fractions meet
tolerance, and all known-label floors pass.  Repeat the assignment in a
separate output root and require identical membership and summary hashes.

### R5 — independent leakage acceptance

Run exact/RC audits and all 18 directed fresh MMseqs2 searches against the v2
assignment.  Each report must have zero qualifying cross-partition hits.  The
process may stop at the first nonzero result, but no v2 result is accepted
until all 18 pass and a final verification report independently recomputes the
summary.

Only after R5 passes may Task 003 baselines, former-teammate-model evaluation,
or external-method comparison begin.

## Current boundary

Do not rerun the failed v1 portable audit, continue its remaining searches,
or use its partitions for modelling.  Preserve the returned STOPPED package
unchanged.  The immediate next deliverable is an R1 implementation/review
handoff, not another high-memory execution.
