# Task 002C-R2P Claude executor handoff — portable guarded-probe package

## Authorization and boundary

Implement and synthetically test Task 002C-R2P only.  Commit locally on
`issue-002c-partition-assignment`; do not push or merge.

Before editing, verify the repository root, origin
`https://github.com/theAguy/RBP.git`, the branch, a clean tracked worktree,
and that commit `2210380` is an ancestor of `HEAD`.  Stop for a failed check
or unrelated tracked changes; do not overwrite anything.

This handoff authorizes **source, tests, and documentation only**.  It does
not authorize a real package build, archive, input inspection, probe, R3,
components-v2 build, partitioning, audit, baseline, or model work.

## Required reading

1. `CONTRIBUTING.md`
2. `docs/tasks/002c_r2_direct_search_resource_probe.md`
3. `docs/tasks/002c_r2_portable_probe_package.md`
4. `docs/reviews/002c_r2_resource_probe_implementation_acceptance.md`
5. `docs/reviews/002c3_cross_partition_failure_and_component_rebuild_plan.md`
6. `src/rbpbench/splits/resource_probe_r2.py`
7. `src/rbpbench/splits/portable_002c3.py` and
   `scripts/build_002c3_portable_bundle.py` as **design references only**
8. the focused R2 tests.

## Absolute exclusions

Do not open, list, stat, hash, copy, or otherwise access real decoded FASTAs,
the CSV, ignored `artifacts/`, prior portable bundles, collaborator returns,
runtime directories, references, coordinates, or model files.  Do not launch
real MMseqs2 or use the network.  Tests may use only temporary generated
inputs and a clearly fake executable.

## Required implementation

Create a separate portable R2 builder/launcher (for example,
`scripts/build_002c_r2_portable_bundle.py` and
`src/rbpbench/splits/portable_002c_r2.py`).  Reuse small safe helpers where
appropriate, but do not make the old 002C-3/4 launcher serve R2.

The future builder must accept explicit repository, destination and runtime
paths.  It must refuse a non-clean source tree or pre-existing destination.
Its inventory must bind every bundled regular file and permitted symlink.
The future launcher must:

- check that inventory before it opens its target FASTAs;
- require Darwin/arm64, exact bundled interpreter, exact frozen native-arm64
  MMseqs2 hash/version, manifest-bound FASTAs, >=64 GiB installed RAM, >=24
  GiB available RAM and >=100 GiB free disk;
- refuse an existing/nonempty execution root;
- expose only the fixed ordered enum `probe_500`, `probe_251`, `probe_101`;
- use `resource_probe_r2` for the actual probe logic, with no call/import path
  to direct-edge writing, `components_v2`, assignment, audits, or R3;
- stop at the first failure without retrying or launching a subsequent width;
- always attempt a small, checksum-complete `SUCCESS` or `STOPPED` return ZIP;
  and
- retain only sanitized metadata and hashes for excluded raw files, never their
  contents.

The bundle's human-facing prompt/runbook must say: double-click the one R2
launcher, wait for it to finish, and return only the generated return ZIP.  It
must make clear that a successful resource probe is **not** authorization for
R3.

Keep the implementation deliberately narrow.  Do not attach the real data or
runtime in this checkpoint.  A later reviewed task will create one actual
bundle after source acceptance.

## Required synthetic tests

Add focused tests that create a tiny temporary bundle/runtime/FASTA set and
fake tool.  Cover at minimum:

1. builder refusal for dirty/pre-existing destination and inventory inclusion;
2. inventory/file tampering rejection before FASTA/tool access;
3. native host, runtime, binary/hash/version, decode-manifest/FASTA, resource,
   and output-root gates;
4. exactly three ordered R2 stage calls and no R3/direct-edge/component call;
5. stop on the first fake-tool failure, with no retry/later width;
6. successful return and stopped return inventories/checksums; and
7. explicit absence of FASTA sequence, raw TSV/database contents and labels
   from returned files.

Run the R2/package-focused tests.  Do not run real-binary tests or the full
repository suite.

## Commit and return

Commit only intended source, tests, documentation, and small configuration
templates if needed.  Do not stage generated packages, runtime files, FASTAs,
or any ignored artifact.  Return:

1. commit hash and changed-file list;
2. package layout, immutable-inventory checks, and exact execution boundary;
3. focused test commands/results;
4. proof all fixtures/tool calls were synthetic and prohibited inputs were not
   accessed;
5. `git diff --check`, staged-file audit, and clean-worktree status; and
6. any remaining issue before a real bundle can be created.

End exactly with:

**Task 002C-R2 real package build, collaborator execution, and Task 002C-R3
full edge discovery were not started.**
