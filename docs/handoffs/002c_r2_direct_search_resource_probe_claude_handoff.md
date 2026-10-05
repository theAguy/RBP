# Task 002C-R2 Claude executor handoff — guarded resource-probe implementation

## Authorization and Git boundary

Implement the **synthetic implementation portion** of Task 002C-R2 only, on
branch `issue-002c-partition-assignment`, starting from commit `1c19220` or a
descendant containing this handoff. Commit locally and return the required
evidence. Do not push, merge, create the real portable bundle, or execute the
real probe.

Before editing, verify:

- repository root and origin `https://github.com/theAguy/RBP.git`;
- branch `issue-002c-partition-assignment`;
- `1c19220` is an ancestor of `HEAD`; and
- the tracked worktree is clean apart from this handoff commit if applicable.

Stop for an unexpected branch, remote, ancestry failure, or unrelated tracked
change. Do not discard or overwrite existing work.

## Required reading, in order

1. `CONTRIBUTING.md`
2. `docs/tasks/002c_r2_direct_search_resource_probe.md`
3. `docs/reviews/002c_r2_direct_search_resource_probe_reconciliation.md`
4. `docs/reviews/002c3_cross_partition_failure_and_component_rebuild_plan.md`
5. `docs/reviews/002c_r1_component_rebuild_acceptance.md`
6. `src/rbpbench/splits/direct_edges.py`, `components_v2.py`,
   `commands.py`, `guarded_exec.py`, and `portable_002c3.py` as relevant;
7. their focused tests.

The R2 task and reconciliation are authoritative. Do not loosen a scientific
flag, gate, or stop condition.

## Absolute boundary: synthetic implementation only

Do not open, stat, hash, list, inventory, copy, or otherwise access the real
CSV, decoded FASTAs, prior collaborator returns, ignored `artifacts/` content,
model files, coordinate/reference files, or any real portable bundle input.

Do not launch real MMseqs2, use the network, or create the real arm64 package.
Tiny temporary FASTAs and a fake executable in tests are allowed solely to
exercise the guarded subprocess/provenance behavior. The fake tool must never
be named/resolved as the real MMseqs2 binary.

## Required implementation

Create a clear, testable R2 probe module/runner under
`src/rbpbench/splits/`. It must provide the future portable launcher with the
following capabilities, while accepting all paths/dependencies explicitly so
tests can use synthetic fixtures.

### 1. Fixed probe workflow

- The only permitted stages are `probe_500`, `probe_251`, and `probe_101`, in
  that order. No generic `all`, full-search, direct-edge-normalization,
  component-building, assignment, audit, or R3 stage exists.
- Derive one deterministic label-blind 10,000-ID selection from a supplied
  canonical universe, then use precisely that selection at all widths.
- Build subset query FASTA records from supplied decoded FASTA records and
  require their IDs/width/alphabet/order to reconcile exactly. The target must
  be the complete supplied width FASTA; reject a target smaller than the full
  universe.
- Build MMseqs2 argv only through
  `components_v2_direct_search_command`, with a four-thread maximum. No
  identity, coverage, sensitivity, strand, result-cap, or width override
  parameter is allowed.

### 2. Strict result and projection logic

- Parse only two-column query/target TSV output. Require each query endpoint
  to belong to the selected 10,000 IDs and every target endpoint to belong to
  the full universe. Reject malformed, foreign, missing, or duplicate input
  evidence where the specification requires uniqueness.
- Report total rows, distinct query/target IDs, per-query counts, the five
  requested quantiles, deterministic 1,000-query block densities, and 100%
  self-hit rate. Do not create normalized-edge artifacts or expose a result as
  scientific edge input.
- Detect any per-query result count at the frozen 361,180 cap.
- Compute the explicit 36.118 linear and 1.5 conservative projections, with
  database creation kept separate from multiplied search work. Enforce the
  13.3-minute per-search, 26.6-minute total-search, 48-GiB projected-RSS,
  25-GiB retained-artifact, and 20-GiB transient-disk gates from the task.
- Treat a deterministic block density above 1.5 times the overall density as
  a fail-closed projection-heterogeneity stop.

### 3. Live resource and restart safety

- Reuse or extend the existing fail-closed macOS available-memory detector:
  free + inactive + speculative pages from `vm_stat`; `None` is a failure.
- Implement injectable monitors for process-tree RSS, free disk, temporary
  directory size, swap use, and macOS memory-pressure state. Preserve raw
  evidence and a parsed state. An unavailable/non-normal pressure state or
  >2-GiB swap increase stops the stage.
- Enforce 64-GiB installed RAM, 24-GiB available RAM immediately before every
  child launch, 100-GiB pre-width free disk, 80-GiB live floor, 10-GiB
  per-width probe temporary/output ceiling, and a two-hour timeout.
- Use isolated candidate generations and atomic selected records. A failed
  stage must not alter a prior accepted record/generation. Refuse an output
  root that exists or contains any file; never retry a failed width
  automatically.
- Retain relative paths, sizes, and SHA-256 hashes for all excluded raw
  artifacts so a later small return package can bind them without including
  their contents. The implementation may define the return schema, but must
  not create a real package or read real inputs in this checkpoint.

### 4. Documentation

Update `docs/SPLITS.md` concisely to identify R2 as a probe-only,
query-subset/full-target resource measurement and to state that no probe edge
is scientific component evidence.

## Required synthetic tests

Add focused tests covering at least:

1. fixed three-width stage enum/order and rejection of every R3/full-search
   stage name;
2. identical deterministic label-blind selection across widths and selection
   digest/list reconciliation;
3. full target versus subset query enforcement, FASTA width/alphabet/ID
   reconciliation, and frozen argv/thread cap;
4. malformed/foreign result rows, self-hit loss, cap saturation, and query/
   target count reconciliation;
5. block-density heterogeneity, projection arithmetic, and the real
   time-gate arithmetic;
6. live RSS/disk/temp/swap/pressure failures, including undetectable memory
   and non-normal pressure;
7. transient-disk, retained-artifact, and output-ceiling gates;
8. atomic failure/restart behavior and refusal of an existing output root;
9. absence of every direct-edge/component/R3 writer from the executable R2
   path; and
10. deterministic sanitized return-schema/inventory content that omits raw
    sequences, labels, databases, and result TSV contents.

Run the new/affected pure-Python split tests. Fake-tool subprocess tests may
run. Do not run real-binary tests or a full repository suite.

## Explicit exclusions

Do not create a real arm64 environment, package a real bundle, or run the
probe. Do not modify the R1 direct-edge scientific core, v1 artifacts,
assignment code, audit code, frozen relation, competitor/model code, or
coordinate work. Do not start R3.

## Commit and return

Commit only intended source, tests, and documentation. Do not stage generated
artifacts. Do not push or merge.

Return:

1. commit hash and changed-file list;
2. the R2 API/stage boundary and resource-monitoring design;
3. focused test commands/results;
4. proof all fixtures/tool executions were synthetic and no real input or
   real MMseqs2/network was used;
5. `git diff --check`, staged-file audit, and clean-worktree status; and
6. any remaining issue that prevents later packaging.

End exactly with:

**Task 002C-R2 real package execution and Task 002C-R3 full edge discovery
were not started.**
