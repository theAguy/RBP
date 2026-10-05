# Task 002C-R1 Claude executor handoff — components v2 implementation

## Authorization and Git boundary

Implement **Task 002C-R1 only** on branch
`issue-002c-partition-assignment`, starting from commit `11ddad8` or a
descendant containing this handoff.  Work locally, commit the bounded change,
and return the requested evidence.  Do not push, merge, or begin R2/R3.

Before editing, verify:

- repository root and origin `https://github.com/theAguy/RBP.git`;
- branch `issue-002c-partition-assignment`;
- `11ddad8` is an ancestor of `HEAD`; and
- the tracked worktree is clean apart from this handoff commit if applicable.

Stop for an unexpected branch, remote, ancestry failure, or unrelated tracked
change.  Do not discard or overwrite any existing work.

## Required reading, in order

1. `CONTRIBUTING.md`
2. `docs/reviews/002c3_cross_partition_failure_and_component_rebuild_plan.md`
3. `docs/tasks/002c_r1_component_rebuild_implementation.md`
4. `docs/tasks/002_sequence_clustered_partitions.md` (frozen-rule and
   acceptance sections)
5. `docs/SPLITS.md`
6. `src/rbpbench/splits/commands.py`, the existing component/membership
   utilities, and their focused tests.

The R1 task document is authoritative.  Do not reopen its scientific
decisions or substitute a narrower repair such as merging the 4,792 observed
pairs.

## Absolute data/tool boundary

This checkpoint is **synthetic only**.  Do not open, stat, hash, list,
inventory, copy, or otherwise access:

- `dataset_K562_multilabel_with_NEGs.csv`;
- any real decoded FASTA, Task 002B/002C artifact, return package, component
  membership, assignment, or ignored `artifacts/` content;
- model, coordinate, reference, or competitor files.

Do not launch MMseqs2, any external scientific binary, or a network request.
Do not run a real-binary test.  Tiny fake command strings and synthetic TSV
fixtures are permitted; no subprocess is needed for the intended solution.

## Required work

Implement exactly the four sections of
`docs/tasks/002c_r1_component_rebuild_implementation.md`:

1. a shell-free v2 all-vs-all direct-search command builder with precisely the
   frozen audit-search flags;
2. strict streaming parsing/normalization for two-column direct-search result
   TSVs;
3. deterministic components-v2 construction from all three direct-edge sets
   plus separately supplied exact/RC edges; and
4. focused documentation in `docs/SPLITS.md`.

Choose clear module names under `src/rbpbench/splits/`.  Reuse existing safe
ID/hash utilities where that reduces duplication, but do not change v1
clustering semantics or make existing cluster-membership parsers accept direct
edge data implicitly.

The v2 public API must not expose identity, coverage, or maximum-result
overrides.  It must preserve singletons, take transitive closure, and use
hashes of sorted member IDs for deterministic component IDs.

## Tests and required proof

Add focused synthetic tests covering every numbered test requirement in the
R1 task document.  In particular, include a regression proving that a legacy
cluster-membership fixture may omit a qualifying edge while the v2 direct-edge
input joins its endpoints.  The test must make the semantic difference
observable; do not simply assert distinct function names.

Run only the new/affected pure-Python split tests.  Report exact commands and
counts.  Do not run the full repository suite or real MMseqs2 tests.

## Explicit exclusions

Do not:

- create or run an R2/R3 runner/CLI, resource probe, or full direct search;
- read real data to create a manifest;
- recompute, replace, modify, or delete components v1;
- assign partitions or rerun audits;
- alter label parsing, balance logic, coordinate work, or competitor/model
  code; or
- change any frozen scientific threshold, coverage mode, strand setting,
  sensitivity, masking, or zero-hit acceptance rule.

If an implementation choice would require any excluded action, stop and
return the issue instead of expanding scope.

## Commit and return

Commit only intended source, test, and documentation files.  Do not stage
generated artifacts or files under `artifacts/`.  Do not push or merge.

Return:

1. commit hash and changed-file list;
2. the v2 command/edge/component API and how it preserves the frozen rule;
3. the focused test commands/results, including the legacy-omission
   regression;
4. proof tests are synthetic and no MMseqs2/network/real artifact was used;
5. `git diff --check`, staged-file audit, and clean-worktree status; and
6. any remaining design gap.

End exactly with:

**Task 002C-R2 resource probing and Task 002C-R3 full edge discovery were not
started.**
