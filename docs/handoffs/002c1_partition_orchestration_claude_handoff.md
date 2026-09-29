# Task 002C-1 Claude executor handoff — synthetic partition/audit orchestration

## Authorization and Git boundary

Implement checkpoint 002C-1 only on branch
`issue-002c-partition-assignment`, starting from commit `2272ca2` or a
descendant containing this handoff. Work locally on the current project Mac.
Commit the implementation and return evidence, but do not merge or push unless
the project owner separately asks.

Before editing, verify:

- repository root and origin `https://github.com/theAguy/RBP.git`;
- branch `issue-002c-partition-assignment`;
- `2272ca2` is an ancestor of `HEAD`; and
- the tracked worktree is clean apart from this handoff commit if applicable.

Stop for an unexpected branch, remote, ancestry failure, or unrelated tracked
change. Do not discard or overwrite an existing change.

## Required reading, in order

1. `CONTRIBUTING.md`
2. `docs/tasks/002_sequence_clustered_partitions.md`
3. `docs/reviews/002b_real_sequence_grouping_acceptance.md`
4. `docs/tasks/002c_partition_assignment_and_audit.md`
5. `docs/reviews/002c_partition_assignment_review_request.md`
6. `docs/reviews/002c_partition_assignment_reconciliation.md`
7. `docs/DECISIONS.md`
8. `docs/DATA.md`
9. existing `src/rbpbench/splits/` and `tests/test_splits_*.py`

The task and reconciliation are authoritative. This handoff translates them
into the bounded implementation checkpoint; it does not change their
scientific rules.

## Hard boundary: synthetic inputs only

Do not open, hash, stat, copy, list the contents of, or otherwise access:

- `dataset_K562_multilabel_with_NEGs.csv`;
- `artifacts/teammate_run_results/`;
- any accepted real component membership/report;
- ignored real decode FASTAs, Task 002B MMseqs2 databases, or real membership
  files; or
- any model checkpoint, prediction, coordinate artifact, or reference.

Use temporary directories and tiny committed synthetic fixtures only. Do not
run a real assignment, legacy diagnostic, exact audit, audit probe, or full
audit search. Task 002C-2 and 002C-3 remain unauthorized.

## Environment boundary

Do not modify the accepted `rbpbench-splits-002` environment. Create a new
isolated environment only if required for the exact former-notebook diagnostic
dependencies. Before installing, verify availability of:

- Python 3.12;
- `numpy==2.0.2`;
- `scipy==1.16.1`;
- `scikit-learn==1.6.1`; and
- `iterative-stratification==0.1.9`.

Record the actual resolved versions and an explicit environment export. The
notebook output proves these four Python-package versions; do not substitute a
newer version silently. It is acceptable to use the already accepted MMseqs2
18.8cc5c binary for tiny real-binary audit-search fixtures, but do not alter
its environment. If the exact diagnostic dependencies cannot resolve, stop
and report rather than changing the legacy reproduction contract.

## Required implementation

### 1. Separate Task 002C configuration and runner

Do not mutate Task 002B's accepted config in a way that invalidates its
accepted selected records. Add a Task 002C-specific versioned configuration
that records:

- the frozen dataset/audit/proteins and Task 002B component hashes/sizes;
- seed, protected widths, target fractions, floor, and deviation threshold;
- the fully specified normalized-assignment objective and row weight;
- a fixed, generous maximum repair-pass/proposal bound;
- exact legacy dependency versions and fold parameters; and
- audit resource gates, thread cap, timeout, and scientific widths.

Implement a separate 002C runner/CLI (a new console entry point is acceptable)
so extending 002C cannot destabilize the accepted 002B runner. Its explicit
single stages are:

- `assign`;
- `legacy_diagnostic`;
- `exact_audit`;
- `audit_probe` (width-scoped);
- `audit_search` (width plus ordered query and target partition); and
- `finalize`.

There is no `all` stage. `--width` is rejected outside width-scoped stages.
The ordered query and target partitions must be distinct and selected only
from `train`, `validation`, and `test`. Every audit-search selection key and
fingerprint includes width, query partition, and target partition; e.g.
`audit_search_500_train_to_validation` and
`audit_search_500_validation_to_train` are independent requirements.

Every stage uses immutable candidate generations, full relative-path/size/
SHA-256 inventories, content-derived generation digests, atomic selection
records, exact upstream digests, and fresh current-input revalidation on every
run/skip decision. Selection-record write failure discards only the candidate
and preserves prior accepted evidence byte-for-byte. `--dry-run` is checked
before any declared input is opened or subprocess is launched. MMseqs2 stages
require explicit authorization and run only one external stage per invocation.

### 2. Strict component and signed-label ingestion

Implement streaming ingestion that:

- validates the two-column Task 002B gzip header and its exact expected
  hash/size;
- requires the canonical universe `row_0` through `row_361179` exactly once,
  with every component ID a lowercase 64-hex digest and component sizes equal
  the accepted report;
- parses semicolon-separated signed protein IDs strictly in `1..122`;
- rejects zero, malformed/out-of-range IDs, repeated same-sign IDs, or
  contradictory `+k` and `-k` in one row;
- counts `+k` and `-k` independently and treats absent proteins as unknown;
  and
- streams component aggregates without building a dense real label matrix.

Fixture-mode configuration supplies its own tiny hashes/universe; tests must
never make a production config accept a tiny fixture.

### 3. Correct deterministic whole-component assignment

Replace the raw-absolute-deficit behavior in `assignment.py` with the exact
approved contract:

- difficulty order is decreasing maximum component share of total rows or any
  protein/class total, then decreasing component size, then frozen seeded-hash
  tie-break;
- each placement minimizes the change in normalized squared error, normalizing
  each dimension by that partition's target count;
- the single row-count dimension has weight 244, while every one of the 244
  separate protein/class dimensions has weight 1;
- partition ties use fixed order `train`, `validation`, `test`; and
- all arithmetic/order semantics are deterministic and documented.

Then implement deterministic whole-component repair for validation/test floor
violations. Moves/swaps may be accepted only when they strictly improve the
plan's lexicographic tuple, never split a component, never lower another
evaluation class below 30, and never move a row fraction more than three
percentage points from its target. Stop if the fixed bound is exhausted with
a violation.

The accepted real run will use this implementation once; do not add a CLI
weight, order, seed, floor, or objective override. Add a synthetic feasible
case requiring a chain of more than one move/swap and prove the configured
bound finds it. Also test a genuinely infeasible case that fails closed.

### 4. Exact legacy-fold reproduction module

Implement the submitted notebook contract using the exact pinned dependencies:

- construct the positive-only binary target matrix equivalent to
  `targets * masks` in canonical row order;
- call `MultilabelStratifiedKFold(n_splits=5, shuffle=True,
  random_state=42)`; and
- select fold 0's train and holdout arrays.

Define and document deterministic index-set digest encoding. Record package
versions. A tiny fixed fixture must assert exact expected train/holdout indices
and digests from the pinned library, not merely counts.

The diagnostic report schema includes raw counts plus explicit denominators
and rates for:

- crossing components over components represented in holdout;
- training/holdout rows in crossing components over their own row totals;
- directly edge-matched holdout rows over all holdout rows, per width; and
- exact/RC affected holdout rows over all holdout rows, plus raw pair counts.

Legacy results never feed the new assignment or its repair.

### 5. Independent exact/reverse-complement audit

Regenerate the 500/251/101 representations through strict decode, canonicalize
each as `min(sequence, reverse_complement(sequence))`, and detect canonical
hash groups spanning partitions. Reconcile the complete ID universe. Any
cross-partition group is a hard failure. The retained report contains IDs,
hashes, counts, denominators, and rates only—never raw sequence or labels.

### 6. Fresh directed MMseqs2 audit orchestration

Use the existing frozen command builders; do not expose scientific overrides.
For each directed stage:

- regenerate or consume generation-bound synthetic query/target FASTAs;
- build fresh type-2 query and target databases;
- run `audit_search_command()` with the frozen flags and at most four threads;
- render query/target hits;
- require every endpoint to belong to its direction-specific closed universe;
  a foreign or wrong-side endpoint is a hard failure; and
- require zero qualifying cross-partition hits for acceptance.

Actual partition universes are disjoint, so an identical ID on both sides is
evidence corruption, not an ordinary self-hit to discard. If a same-database
fixture needs self-hit removal to test the parser, keep that behavior explicitly
test-only; production cross-partition stages must fail on overlapping
universes.

Run external tools through the existing process-group, live timeout/disk,
available-memory, peak-RSS, and atomic-generation protections. The probe and
full search remain separate stages. Do not execute a real probe/search in
002C-1.

### 7. Finalization completeness

`finalize` must refuse unless the current assignment, legacy diagnostic,
three exact audits, three width probes, and all 18 directed search records are
present, intact, and bound to the same current inputs/assignment/config/tool
identity. It writes deterministic three-column gzip membership and a sanitized
manifest, then independently reproduces and compares decompressed membership
and scientific summaries before promotion.

No final artifact may claim acceptance while a floor fails, a row deviation
exceeds three percentage points, an audit is missing/stale, or any audit has a
cross-partition violation.

## Required focused tests

At minimum, tests must prove:

1. strict component/header/hash/universe reconciliation;
2. strict signed-label parsing and unknown exclusion;
3. normalized objective semantics and fixed tie-breaking;
4. multi-step floor repair, infeasible repair, no collateral floor break, and
   row-deviation protection;
5. deterministic assignment under shuffled component/label input order;
6. exact pinned legacy fixture indices/digests and every count/rate
   denominator;
7. exact/RC cross-partition detection at all widths and closed-universe
   failure;
8. ordered audit keys/fingerprints distinguish both directions;
9. wrong-side/foreign/overlapping audit endpoints fail closed;
10. changed CSV/component/config/binary/upstream invalidates the correct
    downstream stages;
11. dry-run/authorization checks happen before file access/subprocess launch;
12. subprocess failure, kill, timeout, resource breach, and record-write
    failure never promote or damage prior evidence; and
13. finalization refuses each individually missing, stale, failed, or
    one-direction-only audit requirement.

Real-binary tests may use only tiny synthetic FASTAs and the accepted local
MMseqs2 binary. No test may skip silently when the handoff's chosen isolated
environment is active.

## Verification and return

Run:

1. new focused 002C tests;
2. the complete `test_splits_*` suite twice in the isolated 002C environment,
   with all intended real-binary tests executing;
3. the repository-wide suite once from a clean checkout/worktree, separately
   disclosing unrelated pre-existing failures; and
4. `git diff --check` plus a staged-file audit proving no data, generated
   database, large output, environment directory, or model artifact entered
   Git.

Return:

- implementation commit and changed-file list;
- environment resolution/export and binary evidence;
- concise mapping from required items/tests to implementation;
- test counts for both split-suite runs, real-binary tests, and full suite;
- proof no real CSV/component/result/reference/model/network resource was
  accessed except package installation if needed;
- runtime/memory observations for synthetic tests;
- `git diff --check`, staged-file audit, and clean-worktree result; and
- any remaining gap before 002C-2.

Stop after the local implementation commit. Do not start 002C-2 real
assignment or any real-data stage.
