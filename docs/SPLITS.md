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
  manifest. Its `legacy_diagnostic` stage's former-split diagnostic pins
  `rbpbench.splits.cluster_membership_evidence` to the accepted Task 002B
  per-width `mmseqs createtsv` connected-component cluster-membership TSVs
  (Task 002C-2A, `docs/tasks/002c2a_legacy_cluster_evidence.md`): a
  membership row is cluster co-membership, direct or transitive, never a
  direct pairwise similarity edge, and the diagnostic reports per-width
  `cluster_boundary_by_width` counts/rates accordingly.

## Components v2 (Task 002C-R1; synthetic implementation only)

The v1 assignment failed the direct cross-partition audit
(`docs/reviews/002c3_cross_partition_failure_and_component_rebuild_plan.md`),
because the two relations differ:

- **v1 cluster co-membership (historical).** `mmseqs createtsv` over a
  *cluster* result (`representative<TAB>member`, parsed by
  `rbpbench.splits.membership`). The v1 cluster result may leave sequences
  satisfying the direct predicate in different clusters; it is not a
  direct-edge list or a complete closure of the later audit relation, and
  must never be fed to the v2 parser.
- **v2 normalized direct-search edges (the leakage relation).** Two-column
  `query<TAB>target` output of an all-vs-all `mmseqs search`, built by
  `commands.components_v2_direct_search_command`: the audit's exact
  scientific flags (`--search-type 3 --strand 2 --cov-mode 0 --max-seqs 361180
  --alignment-mode 3 -e 1000 --mask 0 -s 7.5`, identity 0.90, coverage
  0.80/0.95/0.95 at 500/251/101 nt), no cluster-only flags, and no
  identity/coverage/`--max-seqs` parameters.

`rbpbench.splits.direct_edges` strictly parses each width's TSV against the
full canonical-ID universe (exactly two non-empty IDs; foreign IDs fail;
self-pairs dropped; pairs canonicalized to `(min, max)` and de-duplicated)
and writes/reads a sorted, content-hashable `a<TAB>b` artifact with no
sequences or labels. `rbpbench.splits.components_v2.build_components_v2`
takes the three widths' edge sets plus separate exact/RC edges, keeps
singletons, takes the transitive closure across and within widths, and
names components by the hash of their sorted member IDs. It fails closed on
a missing/extra width, mismatched or tampered edge set, or endpoint outside
the universe, and returns membership, a summary, and metadata (per-width
counts and hashes, exact/RC edge count and the SHA-256 of the normalized
exact/RC relation) for a later runner. Resource
probing (R2) and the full edge discovery run (R3) are separate checkpoints;
v1 evidence is unchanged.

Focused tests: `PYTHONPATH=src python3 -m unittest tests.test_splits_components_v2`.

### Task 002C-R2 resource probe (probe-only; implementation synthetic so far)

`rbpbench.splits.resource_probe_r2` measures, before any full run is
authorized, the memory/disk/time/output cost of the components-v2 direct
search. It searches a deterministic label-blind 10,000-ID query subset
(the same IDs at every width) against the complete 361,180-row width
database, using only `components_v2_direct_search_command` plus a
`--threads` cap of at most 4, in the fixed stages `probe_500`, `probe_251`,
`probe_101`. It projects with the 36.118 linear scale and a separately
labelled 1.5 safety factor (database creation is reported unscaled), runs
live RSS/disk/temp/swap/memory-pressure supervision, and stops without retry
on any failure or gate crossing. **Probe output is resource evidence only: no
probe edge is scientific component evidence**, and the module has no
normalized-edge writer, components-v2 build, full-query database, assignment,
audit, or R3 stage. Result parsing is bounded streaming: the raw
`createtsv` output must be grouped by query (duplicates are checked only
within the current query), per-block rows *and bytes* per query are reported
and both are subject to the 1.5x heterogeneity gate, the transient-disk
projection uses the larger of the whole-width free-space drop and the peak
size of the probe's own candidate generation (important on shared storage), the retained
figure is an upper bound `max(raw result DB, rendered TSV)`, and peak RSS also
includes a post-run child measurement. MMseqs2 diagnostics are classified:
nonzero exits and concrete OOM/cannot-fit/truncation/multi-part or split-count
diagnostics stop before the next command; generic `Warning:` lines are retained
in the per-step evidence and final return for review without discarding an
otherwise complete probe; normal verbose parameter lines and internal
`*_seqs_split` paths are neither. Block bytes are the exact supplied TSV bytes, the whole-width disk
measurement starts before candidate-generation/subset writing, and a child observed
after the width deadline is rejected even if it already exited. R2 uses separate query/target databases; R3's
same-database search is not claimed to behave identically. Tests:
`PYTHONPATH=src python3 -m unittest tests.test_splits_resource_probe_r2`.

### Task 002C-R2P portable probe package (source/tests only)

`scripts/build_002c_r2_portable_bundle.py` (explicit repo, destination,
runtime and decode-directory arguments; refuses a dirty tree or an existing
destination) and `rbpbench.splits.portable_002c_r2` (the launcher, separate
from the 002C-3/4 launcher) define a single-use offline package: `src/rbpbench`,
the tracked decode manifest, the three manifest-bound decode FASTAs, the native
arm64 runtime, `R2_PACKAGE_CONFIG.json`, a runbook, and one
`RUN_002C_R2_PROBE.command`. `R2_INPUT_MANIFEST.json` (+ `.sha256`) binds every
regular file and symlink; the launcher verifies it, and rejects any unlisted
file, BEFORE opening a FASTA or starting a tool, then checks Darwin/arm64, the
bundled interpreter, the frozen MMseqs2 hash/version, the manifest-bound
FASTAs, 64 GiB installed / 24 GiB available RAM, 100 GiB free disk, and absent
`r2_output/`, `return/`, `execution_logs/`. It calls only
`resource_probe_r2.run_probe` (fixed `probe_500`, `probe_251`, `probe_101`; no
stage selector, no direct-edge/components/assignment/audit/R3 path), stops at
the first failure, and always attempts one `RBP_002C_R2_RETURN_<UTC>_<host>.zip`
with STATUS, manifest, inventory, checksums, commands, logs, selection and
path/size/hash records for excluded raw artifacts, guarded against sequence
content; if that guard trips, the return degrades to a minimal STATUS-only
package and the effective status becomes `STOPPED` with a non-zero exit. The
builder ships only an explicit R2 source subset (`R2_SOURCE_SUBSET`, checked
against the launcher's static import closure), so direct-edge, components-v2,
assignment, audit, `runner_002c` and 002C-3 modules are absent from the bundle;
it also writes `RUNBOOK.md` and `PROMPT_FOR_CLAUDE_OR_CODEX.txt`, and with
`--archive` builds a re-read-verified `<bundle>.tar.gz` plus `.sha256`
(refusing an existing archive). Before copying the runtime, the builder requires
an explicit expected runtime manifest and its pinned SHA-256 and verifies every
file (path, size, hash) and symlink (path, target) under the runtime prefix,
rejecting missing, extra, retyped, mismatching or escaping entries; the fixed
MMseqs2 hash/version check remains a second independent gate. The verified
manifest and the environment lock are copied into the bundle
(`manifests/runtime_manifest.json`, `manifests/runtime_environment_lock.explicit.txt`),
their hashes are bound in `R2_PACKAGE_CONFIG.json` and `BUNDLE_SUMMARY.json`,
and the launcher re-checks them and reports `runtime_provenance` in the return
`STATUS.json`. A SUCCESS return is not authorization for R3. Tests:
`PYTHONPATH=src python3 -m unittest tests.test_splits_portable_002c_r2`.

The accepted Mac package was subsequently built. Its collaborator attempt
stopped before any MMseqs2 command because only 90.76 GiB was free, below the
frozen 100-GiB pre-width gate; that STOPPED return is preserved at
`artifacts/teammate_run_results/return.zip`.

### Task 002C-R2N Linux/Slurm adapter

`rbpbench.splits.newton_002c_r2` and `hpc/newton/002c_r2/` adapt the same R2
core to a scheduled Linux x86_64 node. The scientific command, seed, sample,
widths, target universe, four-thread cap and projection gates are unchanged.
Linux monitoring uses process-tree RSS, `/proc/meminfo` swap and
`MemAvailable`, plus raw PSI evidence; an unreadable measurement fails closed.
The submit wrapper requests four CPUs, 96 GiB RAM, eight hours, no requeue and
no GPU, and the launcher refuses to run outside Slurm. The public Newton GPU
cluster rejects CPU-only jobs, so real CPU execution uses the Darwin cluster;
the historical `newton` module/directory names are retained for package
compatibility. A separate conda setup
pins MMseqs2 18.8cc5c build `hd6d6fdc_0`, exports an explicit lock and records the exact Linux
binary hash; the job revalidates that receipt. The full operator procedure and
review boundary are in `docs/tasks/002c_r2_newton_hpc_execution.md` and
`docs/reviews/002c_r2_newton_hpc_execution_review_request.md`.

The first Darwin attempt is preserved under
`artifacts/teammate_run_results/002c_r2_darwin_stopped_20261024/`. Its 500-nt
search exited cleanly, but an over-broad text matcher treated the normal
MMseqs2 18.8cc5c lines `Split database 0`, `Split memory limit 0`, and internal
`*_seqs_split` command paths as a fatal warning. The corrected classifier is
regression-tested against a sanitized excerpt of that exact output. This stop
contains no accepted R2 result because `createtsv` and the projection gates had
not yet run.

Each checkpoint requires its own executor handoff and review; this
implementation does not silently continue into a later checkpoint.
