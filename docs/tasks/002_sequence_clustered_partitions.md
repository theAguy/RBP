# Task 002 — Sequence-grouped train/validation/test partitions

**Status:** proposed; awaiting one second-review pass before implementation
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

## Proposed grouping rule for review

Use a pinned MMseqs2 release in nucleotide-versus-nucleotide mode with true
alignment identity (`--alignment-mode 3`), forward and reverse strands, and
connected-component clustering (`--cluster-mode 1`). MMseqs2 documents
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

Exact full-window duplicates and reverse-complement duplicates must always be
in the same component even if the external tool omits an edge. Component IDs
are deterministic hashes of the sorted canonical row IDs, not tool-generated
serial numbers.

These thresholds are a proposal to be accepted or replaced by the second
reviewer before implementation. They may not be tuned using downstream AUROC.

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
- exact duplicates, reverse complements, shifted 500-nt matches, and nearly
  identical 251/101 centers group as intended;
- transitive A-B-C similarity never splits A and C;
- unrelated rows remain separable;
- a component can never be broken to improve label balance;
- reruns and shuffled input order reproduce the same component IDs and split;
- external-tool failure cannot promote a partial result; and
- the installed binary truly uses nucleotide alignments, both strands, exact
  identity, and the reviewed coverage semantics.

## Full-data execution

After fixture tests pass:

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
9. Run an independent cross-partition search at the same thresholds and an
   exact duplicate/reverse-complement audit. Any qualifying train-validation,
   train-test, or validation-test match is a hard failure.

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
