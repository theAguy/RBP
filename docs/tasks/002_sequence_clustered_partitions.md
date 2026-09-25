# Task 002 — Sequence-grouped train/validation/test partitions

**Status:** checkpoint 002A accepted; checkpoint 002B planning is under second
review and no real-data execution is authorized
**Phase:** 2
**Branch after Task 001 merge:** `issue-002-sequence-partitions`

## Objective

Create one reproducible, leakage-resistant 70/15/15 train/validation/test split
for all 361,180 rows without genomic coordinates. Highly similar sequences are
grouped before assignment, and a group is indivisible. The test partition is
then locked before any baseline or neural-model result is inspected.

This replaces the submitted notebook's row-level first fold from
`MultilabelStratifiedKFold(n_splits=5, shuffle=True, random_state=42)`, which
does not know that two rows may contain overlapping or nearly identical
sequence windows.

## Scientific boundary

- Sequence content defines groups; protein labels and model outputs do not.
- Known positive/known negative labels may be used only after grouping to
  balance whole groups across partitions.
- Unknown labels remain unknown and do not enter balance counts.
- No model is trained, selected, or evaluated in this task.
- Coordinate recovery is not reopened.
- One second-review round resolves scientific blockers. Optional engineering
  refinements are deferred so this task does not repeat Task 001's review loop.

## Frozen grouping rule

Use Bioconda MMseqs2 `18.8cc5c` (osx-64 build `h8b377d6_0`) in explicit
nucleotide-versus-nucleotide mode with true alignment identity, forward and
reverse strands, disabled low-complexity masking, and connected-component
clustering. The scientific flags are frozen as:

```text
createdb: --dbtype 2
cluster:   --min-seq-id 0.90 -c <0.80 or 0.95> --alignment-mode 3
           --cov-mode 0 --max-seqs 361180 -e 1000 --mask 0 -s 7.5
           --cluster-mode 1 --single-step-clustering 1
audit search: --search-type 3 --strand 2 --min-seq-id 0.90
              -c <0.80 or 0.95> --alignment-mode 3 --cov-mode 0
              --max-seqs 361180 -e 1000 --mask 0 -s 7.5
```

The coverage value is selected only from the width table below: `0.80` for
500 nt and `0.95` for 251/101 nt. The explicit result ceiling equals the
entire fixed dataset universe, so MMseqs2 cannot silently discard a qualifying
edge merely because a query has more hits than its much smaller workflow
default. If this setting makes the real run unsafe, stop for review rather
than reducing it silently.

The executor must confirm on tiny fixtures that the installed binary accepts
and honors every applicable flag before any real-data execution. MMseqs2 does
not expose `--search-type` or `--strand` on the clustering workflow: nucleotide
clustering is therefore bound by the type-2 database, and both-orientation
behavior must be demonstrated by a reverse-complement fixture. The audit search
does pin search type and strand explicitly. MMseqs2 documents
bidirectional coverage as aligned residues divided by the longer sequence and
connected components as all sequences reachable through accepted similarity
edges:

- <https://mmseqs.com/latest/userguide.pdf>
- <https://github.com/soedinglab/MMseqs2>

Build the final row component as the union of three label-blind clusterings:

| Representation | Minimum identity | Bidirectional coverage | Purpose |
|---|---:|---:|---|
| full 500 nt | 0.90 | 0.80 | capture highly similar and shifted full windows |
| centered 251 nt | 0.90 | 0.95 | protect the planned 251-nt evaluation input |
| centered 101 nt | 0.90 | 0.95 | protect the shortest planned model input |

Exact duplicates and reverse-complement duplicates at each of the 500-, 251-,
and 101-nt representations must always be in the same component even if the
external tool omits an edge. Component IDs are deterministic hashes of the
sorted canonical row IDs, not tool-generated serial numbers.

These thresholds and command semantics were accepted in second review. They
may not be tuned using downstream AUROC.

## Checkpoints

- **002A — implementation and tiny fixtures:** create the isolated pinned
  environment, implement the reusable pipeline, and verify the scientific
  semantics using only synthetic fixtures. Do not open the real CSV.
- **002B — real sequence grouping:** decode the full dataset, run the three
  clustering jobs, union components, and return the component-size/gate report.
  Do not assign train/validation/test yet.
- **002C — partition assignment and audit:** only after 002B acceptance, assign
  whole components, run cross-partition audits, and freeze the membership.

Each checkpoint requires its own executor handoff and review. A checkpoint may
not silently continue into the next one.

Task 002B is further divided into restart-safe execution subcheckpoints in
`docs/tasks/002b_real_sequence_grouping.md`; its current review request is
`docs/reviews/002b_real_sequence_grouping_review_request.md`.

## Implementation and fixture checks

Implement reusable code under `src/rbpbench/splits/` for:

1. streaming strict decode and deterministic 500/251/101 FASTA generation;
2. exact/reverse-complement duplicate union;
3. safe MMseqs2 command construction and version capture;
4. parsing cluster memberships and unioning components across window sizes;
5. deterministic whole-component partition assignment;
6. cross-partition similarity audit and report generation.

Tiny fixtures must prove:

- invalid one-hot rows fail closed;
- exact duplicates and reverse complements at all three widths, shifted 500-nt
  matches, and nearly identical 251/101 centers group as intended;
- transitive A-B-C similarity never splits A and C;
- unrelated rows remain separable;
- a component can never be broken to improve label balance;
- reruns and shuffled input order reproduce the same component IDs and split;
- external-tool failure cannot promote a partial result; and
- the installed binary truly uses nucleotide alignments, both strands, exact
  identity, disabled masking, the explicit E-value ceiling, and the reviewed
  coverage semantics.

## Full-data execution in later checkpoints

After 002A fixture tests are accepted, execute the following only through the
separate 002B and 002C handoffs:

1. Revalidate the frozen CSV, audit, and protein-index hashes.
2. Decode all 361,180 rows once, preserving canonical `row_<index>` IDs.
3. Run the three reviewed clustering jobs and union their memberships.
4. Report component counts and sizes before assigning a partition.
5. Stop for review rather than assign partitions if one component contains
   more than 5% of all rows or the largest 20 components together contain more
   than 20%; this guards against an uninformative repeat-driven giant
   component.
6. Assign whole components deterministically with seed `20260925` toward
   70% train, 15% validation, and 15% test, minimizing deviations in total rows
   and the 244 per-protein positive/known-negative counts.
7. Require every protein to retain at least 30 known positives and 30 known
   negatives in both validation and test. Report, but do not silently repair,
   any class whose achieved partition fraction differs from its target by more
   than three percentage points.
8. Reproduce the submitted row-level 80/20 split as a diagnostic and compare
   its cross-boundary similarity violations with the new grouped split. The
   old split is never used for model selection.
9. Run fresh cross-partition MMseqs2 searches in new temporary/output
   generations with all frozen flags, never reusing clustering results or
   temporary databases. Also run a tool-independent canonical-sequence hash
   audit for exact and reverse-complement duplicates at all three widths. Any
   qualifying train-validation, train-test, or validation-test match is a hard
   failure. The manifest must state honestly that the near-similarity audit is
   an independent execution of the same pinned aligner, while the exact audit
   is independent code.

## Outputs

- `configs/splits/sequence_partitions_v1.toml` — frozen parameters and seed;
- `artifacts/splits/sequence_partitions_v1.tsv.gz` — deterministic gzip
  (`mtime=0`) containing `sample_id`, `component_id`, and `partition` only;
- `manifests/sequence_partitions_v1.json` — input/tool/config/output hashes,
  component and partition summaries, per-protein counts, original-split
  leakage diagnostic, audit results, runtime, memory, and disk;
- tests and documentation needed for a collaborator to regenerate the split.

The compressed membership file may enter ordinary Git only if it is at most
10 MiB and contains no sequence or label values. Otherwise commit its hash and
deterministic regeneration instructions, and exchange it as a project
artifact.

The manifest must also note that only the planned 500/251/101 widths are
explicitly protected, report likely low-complexity/repeat drivers if a giant-
component gate trips, and flag proteins near the 30/30 evaluation floor for
confidence-interval treatment in Phase 3.

## Acceptance gate

- All 361,180 sample IDs appear exactly once.
- Every similarity component belongs to exactly one partition.
- Independent cross-partition audits find zero matches meeting the frozen
  grouping rules.
- Exact/reverse-complement duplicates never cross partitions.
- Per-protein positive/negative minima pass, and all balance deviations are
  disclosed.
- Two executions reproduce decompressed membership and scientific summaries
  byte-for-byte.
- The test partition has not been used for any threshold, architecture,
  stopping, or hyperparameter decision.

Only after acceptance may Phase 3 baselines begin.

## Stop conditions

Stop and return evidence if the pinned MMseqs2 binary is unavailable, fixture
semantics disagree with the plan, memory/disk becomes unsafe, a giant component
triggers the gate, class minima cannot be met without splitting a component,
the audit finds a cross-partition qualifying match, or implementation would
require model results or coordinates.
