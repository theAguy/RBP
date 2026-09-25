# Sequence-clustered partition pipeline: usage and the 002A/002B/002C boundary

This package (`src/rbpbench/splits/`) implements the reusable pipeline for
Task 002, the sequence-grouped 70/15/15 train/validation/test split
(`docs/tasks/002_sequence_clustered_partitions.md`). It is split across
three execution steps, each gated on its own planning review.

## Task 002A (this implementation) — correction in progress

Implementation and tiny synthetic fixture tests only. Nothing in this
checkpoint opens the real CSV, generates a real dataset FASTA, or constructs
a real component/partition.

- `rbpbench.splits.decode` — streaming strict one-hot decode (reuses
  `rbpbench.coordinates.decode`) into deterministic 500/251/101-nt
  center-window FASTAs, keyed by canonical `row_<index>` sample IDs. A
  single strict-decode failure anywhere aborts the whole run before any
  output is promoted (atomic `.tmp` → final rename per width).
- `rbpbench.splits.hashing` — exact/reverse-complement canonical sequence
  hashing at every protected width, independent of the external clustering
  tool.
- `rbpbench.splits.commands` — shell-free MMseqs2 `argv` construction
  (`createdb`/`cluster`/`createtsv`/`search`), guarded execution with
  separately captured/hashed stdout and stderr, a timeout, binary identity
  (resolved path + SHA-256 + version), and a transactional
  `new_generation_dir` promotion pattern (mirrors
  `rbpbench.coordinates.runner._new_generation_dir`).
- `rbpbench.splits.membership` — `mmseqs createtsv` cluster-membership
  parsing with complete/unique ID reconciliation (missing, duplicate, and
  foreign IDs are all hard failures).
- `rbpbench.splits.components` — deterministic union-find across every
  window-size clustering plus canonical-hash duplicate edges; component IDs
  are content hashes of sorted member IDs, never tool-generated serial
  numbers.
- `rbpbench.splits.assignment` — deterministic whole-component 70/15/15
  assignment, label-blind grouping with label-aware balancing of already-
  frozen components (never splits one).
- `rbpbench.splits.audit` — 5%/20% giant-component gates, balance/deviation
  reporting, the 30/30 evaluation-floor check, and cross-partition violation
  detection.
- `rbpbench.splits.output` — deterministic `mtime=0` gzip membership output
  and sanitized manifest/report generation (hashes, counts, and IDs only —
  never a sequence or label value).

## Frozen command semantics (`docs/DECISIONS.md`, 2026-09-25)

```text
createdb:      --dbtype 2
cluster:       --min-seq-id 0.90 -c <0.80 or 0.95> --alignment-mode 3
               --cov-mode 0 --max-seqs 361180 -e 1000 --mask 0 -s 7.5
               --cluster-mode 1 --single-step-clustering 1
audit search:  --search-type 3 --strand 2 --min-seq-id 0.90
               -c <0.80 or 0.95> --alignment-mode 3 --cov-mode 0
               --max-seqs 361180 -e 1000 --mask 0 -s 7.5
```

Coverage is `0.80` at 500 nt and `0.95` at 251/101 nt. Commit `6321356`
omitted the identity, width-specific coverage, and result-ceiling arguments;
`docs/reviews/002a_sequence_partition_pipeline_review.md` therefore requires a
bounded correction before 002A can be accepted or 002B can begin.

`mmseqs cluster --help` (18.8cc5c) does not list `--search-type` or
`--strand` at all — confirmed against the real installed binary, not just
assumed (`tests/test_splits_real_binaries.py::ClusterWorkflowFlagExposureTests`).
Nucleotide clustering is therefore bound by the explicit type-2 database,
and both-orientation behavior is proven by a real-binary,
non-palindromic reverse-complement fixture at all three widths
(`RealClusteringReverseComplementFixtureTests`), never by passing an
unsupported flag to `cluster`. `mmseqs search` (the separate audit-search
workflow) does expose both flags and pins them explicitly
(`RealAuditSearchStrandTests` proves `--strand 2` finds a reverse-complement
hit that `--strand 1` misses on the identical query/target pair).

## Environment

The isolated `rbpbench-splits-002` conda environment (Bioconda MMseqs2
`18.8cc5c`, build `h8b377d6_0`) is recorded in
`manifests/sequence_partition_environment_002a.{yml,explicit.txt,json}`
(binary path, SHA-256, and the real-fixture gate results). It is separate
from `rbpbench-coord-001b` (Task 001) and is never altered by this task.

## Running the tests

Pure-Python tests (`test_splits_decode.py`, `test_splits_hashing.py`,
`test_splits_components.py`, `test_splits_membership.py`,
`test_splits_assignment.py`, `test_splits_audit.py`,
`test_splits_output.py`) run anywhere:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_splits_*.py' -v
```

`test_splits_commands.py`'s execution/timeout/failure tests use small fake
shell scripts, not `mmseqs`, so they also run anywhere. Real-binary tests
(`test_splits_real_binaries.py`) skip cleanly when `mmseqs` is not on PATH
and only run for real inside `rbpbench-splits-002`:

```bash
conda activate rbpbench-splits-002
PYTHONPATH=src python3 -m unittest tests.test_splits_real_binaries -v
```

## Task 002B / 002C — not started here

- **002B** — decode the full 361,180-row dataset, run the three reviewed
  clustering jobs for real, union components, and report component-size/gate
  results before any partition assignment.
- **002C** — after 002B acceptance, assign whole components, run the fresh
  independent cross-partition audits, and freeze the membership file and
  manifest.

Each checkpoint requires its own executor handoff and review; this
implementation does not silently continue past 002A.
