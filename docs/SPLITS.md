# Sequence-clustered partition pipeline: usage and the 002A/002B/002C boundary

This package (`src/rbpbench/splits/`) implements the reusable pipeline for
Task 002, the sequence-grouped 70/15/15 train/validation/test split
(`docs/tasks/002_sequence_clustered_partitions.md`). It is split across
three execution steps, each gated on its own planning review.

## Task 002A (this implementation) — accepted

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
  separately captured/hashed stdout and stderr (unique per-invocation log
  paths, so two same-tool calls sharing one log directory never overwrite
  each other's evidence), a timeout, binary identity (resolved path +
  SHA-256 + version), and a transactional `new_generation_dir` promotion
  pattern (mirrors `rbpbench.coordinates.runner._new_generation_dir`).
  `cluster_command`/`audit_search_command` require a `width` argument
  (500/251/101 only -- any other value raises `UnknownWidthError` before any
  subprocess starts) and always pass `--min-seq-id 0.90`, the width's mapped
  `-c` coverage, `--cov-mode 0`, and `--max-seqs 361180`; identity/coverage
  are never caller-configurable.
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
  detection. The closed-universe audit (`cross_partition_violations`) fails
  closed: an edge endpoint absent from the assignment mapping raises
  `ForeignAuditEndpointError` rather than being silently skipped.
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
`docs/reviews/002a_sequence_partition_pipeline_review.md` required a bounded
correction before 002A could be accepted or 002B could begin. That
correction is applied: `cluster_command`/`audit_search_command` now require
a `width` argument and always pass `--min-seq-id 0.90`, the width's mapped
`-c` coverage, `--cov-mode 0`, and `--max-seqs 361180`
(`tests/test_splits_commands.py`, `tests/test_splits_real_binaries.py`).
The corrected implementation is accepted in
`docs/reviews/002a_sequence_partition_acceptance.md`; this acceptance does
not itself authorize real-data checkpoint 002B.

`mmseqs cluster --help` (18.8cc5c) does not list `--search-type` or
`--strand` at all — confirmed against the real installed binary, not just
assumed (`tests/test_splits_real_binaries.py::ClusterWorkflowFlagExposureTests`).
Nucleotide clustering is therefore bound by the explicit type-2 database,
and both-orientation behavior is proven by a real-binary,
non-palindromic reverse-complement fixture at all three widths, alongside
the frozen identity/coverage rule's discriminating pairs
(`WidthSpecificClusteringDiscriminationTests`), never by passing an
unsupported flag to `cluster`. `mmseqs search` (the separate audit-search
workflow) does expose both flags and pins them explicitly
(`RealAuditSearchStrandTests` proves `--strand 2` finds a reverse-complement
hit that `--strand 1` misses on the identical query/target pair;
`AuditSearchDiscriminationTests` proves the same width-specific
identity/coverage rule applies to audit search as to clustering).

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

## Task 002B-1 (this implementation) — orchestration and synthetic fixtures only

`docs/handoffs/002b1_orchestration_claude_handoff.md`. Still no real CSV
access and no real MMseqs2 execution over real sequences -- every test uses
tiny synthetic CSV/FASTA data (most against a small fake `mmseqs` stand-in;
scientific clustering correctness is a 002A concern, already proven against
the real binary in `tests/test_splits_real_binaries.py`).

- `rbpbench.splits.config` -- loads `configs/splits/sequence_partitions_v1.toml`
  (seed, protected widths, frozen real-input hash/size expectations, and
  resource limits). Exposes no identity/coverage/`--max-seqs` field: those
  stay hardcoded and non-overridable in `rbpbench.splits.commands`.
- `rbpbench.splits.runner` -- the restart-safe CLI/runner (`rbp-splits`),
  with explicit `preflight`/`decode`/`probe`/`cluster`/`component_report`
  stages. Exactly one stage per invocation (no `all`); `--width` is required
  for `probe`/`cluster` and rejected elsewhere; `--authorize-mmseqs` is
  required for any stage that may launch MMseqs2; `--dry-run` is checked
  before any subprocess or declared-real-input file is opened. Every stage
  writes an atomic selection record under `<output-dir>/selected/`, and a
  downstream stage refuses to run (`PriorStageNotAcceptedError`) unless its
  upstream record exists and re-hashes intact -- a stage is never silently
  run on another stage's behalf. Restart-skip fingerprints are recomputed
  fresh (re-hashing the current CSV/config/binary) on every invocation, so a
  changed input, config, or resolved MMseqs2 binary always invalidates a
  skip. `probe` selects `rbpbench.coordinates.hashing.label_blind_rank`'s
  configured sample size, independent of labels and row order; `cluster`
  runs over the whole accepted decode generation. Both apply `--threads 4`
  (`rbpbench.splits.commands.with_threads`) and enforce the 50-GiB combined
  new-artifact ceiling / 80-GiB free-disk floor
  (`rbpbench.coordinates.diskbudget`), discarding (never promoting) a
  candidate generation that crosses either. `component_report` unions the
  three cluster generations' memberships with the independent exact/RC
  duplicate edges computed at decode time, reproduces the union under a
  reversed input order to prove order-independence, and writes the
  deterministic `sample_id,component_id` gzip
  (`rbpbench.splits.output.write_deterministic_component_membership_gzip`)
  plus a sanitized `component_report.json`
  (`rbpbench.splits.output.build_component_report`) -- hashes, counts, and
  IDs only, matching Task 002's "never commit sequence content, labels,
  ... " rule, and never a partition, model-output, or coordinate value,
  since 002B does not touch any of those.
- **Split-memory-limit correction gate**
  (`tests/test_splits_split_memory_gate.py`, real-binary, `rbpbench-splits-002`
  only): proves the candidate production `--split-memory-limit 8G` value
  fails closed on the pinned 18.8cc5c binary even for a tiny synthetic
  fixture under the frozen `-s 7.5` sensitivity setting ("Cannot fit
  databases into 7G. Please use a computer with more main memory."), and that
  no value at or below the ~9.1-GiB fixed per-split memory floor observed on
  this 16-GiB host ever completes -- so a genuine forced multi-way split can
  never be safely demonstrated here (a second split would need materially
  more memory than is physically installed). Per
  `docs/reviews/002b_real_sequence_grouping_reconciliation.md`'s explicit
  fallback, the flag is removed: `rbpbench.splits.runner` never applies
  `with_split_memory_limit` to a production cluster/probe invocation, and
  `configs/splits/sequence_partitions_v1.toml` records the finding. The
  002B-3 resource-probe stop boundary (10-GiB probe peak / 10-GiB available
  memory) remains the sole real-run memory safeguard.

## Task 002B-2 accepted; Task 002B-3 onward / 002C pending

- **002B-3 through 002B-7** -- resource probes, the three real
  full-width clustering runs, and the final union/gate report, each its own
  separately reviewed checkpoint (`docs/tasks/002b_real_sequence_grouping.md`).
- **002C** — after 002B acceptance, assign whole components, run the fresh
  independent cross-partition audits, and freeze the membership file and
  manifest.

Each checkpoint requires its own executor handoff and review; this
implementation does not silently continue into a later checkpoint.
