# Task 002C — Component-level partition assignment and leakage audit

**Status:** checkpoint 002C-1 accepted; Task 002C-2A's correction and binding
of retained legacy-clustering evidence is in planning review, while real
assignment remains unauthorized
**Parent:** `docs/tasks/002_sequence_clustered_partitions.md`
**Branch:** `issue-002-sequence-partitions`

## Objective

Assign every accepted Task 002B similarity component, intact, to one locked
70/15/15 train/validation/test partition; verify evaluation-count viability;
quantify the former teammate's row-level split as a diagnostic; and perform
fresh cross-partition similarity audits before freezing the membership used by
all later baselines and models.

Task 002C does not train a model, inspect a prediction, tune a similarity
threshold, reopen coordinates, or rerun Task 002B clustering. Protein labels
may balance already-frozen components but may never redefine or split them.

## Frozen inputs

The real run must revalidate these inputs before reading labels or assigning a
component:

- dataset CSV: 724,425,277 bytes, SHA-256
  `982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945`;
- `manifests/dataset_audit.json`: SHA-256
  `e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c`;
- `configs/proteins.tsv`: SHA-256
  `374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9`;
- accepted Task 002B component membership: 14,578,797 bytes, SHA-256
  `6000c340056ba8204432e7f4c417fb811f8a3d1a5b1c091dea98461862c7b692`;
- accepted Task 002B component report: 13,036,977 bytes, SHA-256
  `b8b5872a4cc5061c562de871ec4500876fcdb72afcab069b21ab2bb44cb3e186`;
- exactly 361,180 canonical IDs and 173,465 deterministic components, with
  the accepted component-size map and giant-component result; and
- assignment seed `20260925`, target fractions 70/15/15, the 30-positive and
  30-known-negative validation/test floors, and the three-percentage-point
  balance-report threshold already frozen by the parent task.

The returned Task 002B artifacts currently live under the ignored local
result directory. The 002C CLI must accept their paths explicitly and bind
their hashes into every restart fingerprint and final manifest; it must not
depend on the collaborator's former absolute path.

## Real-data feasibility finding before implementation

A read-only, non-retained local diagnostic exposed a defect in the existing
`assignment.assign_partitions()` objective: raw absolute row deficits dominate
the much smaller protein/class deficits. It produced nearly exact row totals
but ten validation/test floor failures, including a protein/class count of
only five, despite every protein having at least 506 positives and 506 known
negatives overall.

This is not evidence that the frozen components make the floor infeasible.
All 244 protein/class dimensions span enough distinct components to distribute
well above 30 per partition; a scale-normalized scratch assignment cleared all
floors. Neither scratch assignment is accepted or frozen. The production
implementation must correct the objective under the prespecified contract
below and then execute once through the reviewed runner.

## Frozen assignment contract

### Label interpretation

- `+k` contributes one known positive to protein `k`.
- `-k` contributes one known negative to protein `k`.
- an absent protein is unknown and contributes nothing.
- all 122 positive and 122 known-negative dimensions are balanced separately.
- no sequence, GC value, model prediction, coordinate, or prior performance
  value may enter assignment.

### Deterministic objective

1. Treat the accepted component mapping as immutable and verify each of the
   361,180 IDs exactly once.
2. Stream the CSV once to aggregate size and the 244 known-label counts per
   component. Do not materialize the 724-MB CSV or dense 361,180-by-122 label
   matrices.
3. Order components deterministically by decreasing placement difficulty:
   their maximum share of any global protein/class total or of total rows,
   followed by component size and the frozen seeded hash tie-break.
4. For each component, choose the partition that minimizes the increase in a
   normalized squared-deficit objective. Normalize every row or protein/class
   dimension by its target count so abundant dimensions cannot overwhelm rare
   ones. Give the single row-count objective the same aggregate weight as all
   244 protein/class objectives together. Resolve all ties by the fixed order
   `train`, `validation`, `test`.
5. If an evaluation floor remains below 30, perform deterministic whole-
   component moves or swaps that strictly reduce the lexicographic tuple:
   total floor deficit, number of floor violations, maximum absolute row-fraction
   deviation, number of protein/class deviations over three percentage points,
   then total normalized squared error. A repair may never split a component,
   lower another evaluation class below 30, or move row balance outside three
   percentage points of its target.
6. Stop rather than silently weaken a floor or split a component if bounded
   repair cannot reach zero floor violations. Once floors pass, report all
   remaining deviations over three percentage points; they are disclosures,
   not a reason for open-ended post-hoc optimization.

The exact objective, weights, ordering, tie-breaking, and maximum repair-pass
count must live in versioned configuration/code before the accepted real run.
Two executions over reordered inputs must yield byte-identical decompressed
membership and identical scientific summaries.

## Former-split diagnostic

> **Evidence correction pending:** the accepted Task 002B return retained
> per-width connected-component cluster memberships, not the internal
> alignment-result databases needed to substantiate the direct-edge claim
> below. `docs/tasks/002c2a_legacy_cluster_evidence.md` proposes replacing it
> with an accurately named per-width cluster-boundary diagnostic before any
> real legacy diagnostic runs. The historical requirement below is not
> authorized for execution as written.

Reproduce the submitted notebook's first fold exactly:

- `iterative-stratification==0.1.9`;
- `MultilabelStratifiedKFold(n_splits=5, shuffle=True, random_state=42)`;
- `strat_labels = targets * masks`, which is equivalent to the positive-only
  target matrix and does not distinguish known negatives from unknowns; and
- fold 0's 80% training indices and 20% holdout indices.

Record environment/package versions and a deterministic digest of both index
sets. Compare the legacy split with the accepted components using at least:

- components crossing the legacy boundary, reported both as a count and as a
  rate over components represented in the legacy holdout;
- training and holdout rows belonging to crossing components, each reported
  against its own partition-row denominator;
- holdout rows with at least one directly recorded Task 002B similarity edge
  to a training row, by protected width, reported as a count and a rate over
  all legacy holdout rows; and
- exact/reverse-complement cross-boundary violations, including the number and
  rate of affected legacy holdout rows (plus raw violating-pair counts).

This diagnostic does not rescue, alter, or reuse the old split. The new test
partition remains untouched by all model results.

## Checkpoints and local-first execution

### 002C-1 — implementation and synthetic fixtures only

Extend the split pipeline with explicit, single-stage invocations for:

- `assign` — load an accepted component artifact, stream labels, assign whole
  components, and create transactional candidate membership/report artifacts;
- `legacy_diagnostic` — reproduce the old fold and measure its component/edge
  crossings without changing the new assignment;
- `exact_audit` — independently regenerate canonical exact/reverse-complement
  hashes at 500/251/101 nt and fail on a cross-partition collision;
- `audit_probe` and `audit_search` — fresh MMseqs2 search generations, scoped
  to one width and one ordered query/target partition pair per invocation;
  both directions are required for every unordered pair; and
- `finalize` — accept only a complete assignment plus all required audit
  records and write the final sanitized manifest.

Use tiny synthetic inputs only. Every stage must use immutable generation
directories, atomic selection records, current-input fingerprints, complete
file inventories, and fail-closed restart checks. `--dry-run` must open no
declared real input and launch no subprocess. MMseqs2 stages require explicit
authorization and may not share an invocation with another stage.

Fixture tests must cover: component immutability; signed-label parsing;
unknown exclusion; normalized balancing; floor repair and infeasible-floor
stop; deterministic ties/reordered input; foreign/missing/duplicate IDs;
selection-record write failure; changed upstream invalidation; exact/RC
crossing; legacy-fold reproduction against a tiny frozen expected result;
audit-hit parsing; self-hit exclusion; cross-partition failure; subprocess
kill/timeout/disk/resource failure; and finalization refusing any missing or
stale audit. Include a feasible synthetic floor case that requires a chain of
more than one move/swap so the configured repair bound is exercised rather
than merely declared. Every audit-search fingerprint and selection-record key
must include ordered query and target partition identities; an accepted result
from one direction can never satisfy the reverse direction.

### 002C-2 — local assignment and non-MMseqs2 diagnostics

On the current project Mac, sequentially:

1. revalidate all frozen inputs;
2. run `assign` twice and require byte-identical decompressed membership and
   scientific summaries;
3. require exactly 361,180 IDs, 173,465 indivisible components, acceptable
   70/15/15 row balance, and at least 30 positives and 30 known negatives for
   every protein in validation and test;
4. run and record the exact legacy-split diagnostic; and
5. run the independent exact/reverse-complement audit.

These stages are expected to remain comfortably within the local 16-GiB host.
They may not launch MMseqs2 or begin model/baseline work.

### 002C-3 — fresh cross-partition MMseqs2 audits

For each protected width and each unordered pair
`train-validation`, `train-test`, and `validation-test`, run both ordered
query/target directions (18 directed searches in total):

1. regenerate the two partition FASTAs from the frozen assignment in a fresh
   audit generation;
2. build fresh type-2 MMseqs2 databases; do not reuse clustering databases,
   results, or temporary files;
3. run the frozen audit-search command with nucleotide search type 3, both
   strands, 0.90 identity, the width-specific 0.80/0.95 bidirectional
   coverage, `--max-seqs 361180`, alignment mode 3, E-value 1000, masking
   disabled, sensitivity 7.5, and at most four threads; and
4. reconcile all endpoints against the closed, direction-specific query and
   target universes and require zero qualifying cross-partition hits.

First run one deterministic bounded probe per width. Preserve the existing
10-GiB available-memory launch gate, 10-GiB peak-memory probe gate, 80-GiB
free-disk floor, 50-GiB combined new-artifact ceiling, and 12-hour timeout.
Run searches sequentially, never concurrently.

Attempt this checkpoint locally only when the runner's live memory gate
passes. If it does not, stop without lowering the gate and create a clean,
hash-bound handoff containing the frozen assignment and only the files needed
to execute the audit on the 64-GiB collaborator Mac. Do not repeat assignment,
legacy diagnostics, or Task 002B clustering there.

### 002C-4 — finalize and freeze

Finalize only after all 18 directed width-by-partition-pair audit searches and
all three exact/RC width audits are accepted and current. The final output is:

- `artifacts/splits/sequence_partitions_v1.tsv.gz` containing only
  `sample_id`, `component_id`, and `partition`, deterministically compressed;
- `manifests/sequence_partitions_v1.json` containing hashes, aggregate counts,
  balance/floor disclosures, legacy leakage diagnostics, audit summaries,
  resources, commands, tool identities, and upstream generation digests; and
- a small acceptance review. If membership exceeds 10 MiB, keep it out of
  ordinary Git and commit only its hash and regeneration/exchange procedure.

## Acceptance gate

- All 361,180 canonical IDs occur exactly once.
- Every accepted Task 002B component belongs entirely to one partition.
- Row fractions remain within three percentage points of 70/15/15.
- Every protein has at least 30 known positives and 30 known negatives in both
  validation and test; every larger balance deviation is disclosed.
- Exact/reverse-complement audits find zero cross-partition collisions at all
  three widths.
- All 18 directed fresh MMseqs2 searches find zero qualifying
  cross-partition hits.
- Repeated assignment/finalization reproduces decompressed membership and
  scientific summaries exactly.
- The manifest quantifies the legacy split without using it for new model
  selection.
- No prediction, model result, coordinate, or test-set performance influenced
  grouping, assignment, repair, or acceptance.

Only after this gate passes may Phase 3 baselines begin.

## Stop conditions

Stop and return evidence for: any frozen hash or component mismatch; a floor
that cannot be met without splitting a component; row imbalance beyond three
percentage points after bounded repair; nondeterministic membership; a stale
or incomplete audit; any exact/RC or MMseqs2 cross-partition hit; a foreign
audit endpoint; changed scientific flags; unavailable memory/disk; killed or
timed-out subprocess; or any need to inspect model predictions.
