# Executor handoff — Task 002B-1 orchestration and synthetic fixtures

Claude, implement and verify only checkpoint 002B-1. This is a code-and-tiny-
fixture checkpoint. Do not open the real dataset or start any real-data stage.

## Git and required reading

1. Work on `issue-002-sequence-partitions` from the commit containing this
   handoff. Verify expected origin, clean tracked worktree, and accepted commit
   `ec08a71` as an ancestor. Do not push, merge, or rewrite history.
2. Read, in order:
   - `docs/tasks/002b_real_sequence_grouping.md`;
   - `docs/reviews/002b_real_sequence_grouping_review_request.md`;
   - `docs/reviews/002b_real_sequence_grouping_reconciliation.md`;
   - `docs/reviews/002a_sequence_partition_acceptance.md`;
   - `docs/SPLITS.md`, `docs/DATA.md`, `docs/DECISIONS.md`, and
     `CONTRIBUTING.md`.
3. Keep reusable work under `src/rbpbench/splits/`, configs under
   `configs/splits/`, and tests under `tests/`. Do not change coordinate
   behavior or access ignored real artifacts.

## Authorized implementation

Implement a restart-safe Task 002 runner sufficient for the later reviewed
real checkpoints:

- explicit stages `preflight`, `decode`, `probe`, `cluster`, and
  `component_report`;
- exactly one stage per invocation, with width required for width-scoped stages;
- no omitted-stage default and no `all` stage;
- explicit authorization required for any stage that may launch MMseqs2;
- `--dry-run` checked before any subprocess or real input access;
- immutable candidate generation directories and atomic selection records;
- stage fingerprints binding config, declared inputs, exact upstream generation
  digests, tool identity, width, and authorization;
- restart skips that re-hash accepted evidence rather than trusting state alone;
- failure or final-record-write interruption that discards the new candidate
  without changing a prior accepted selection;
- deterministic normalized cluster memberships with every member exactly once
  and every representative inside the expected universe;
- shell-free commands, unique logs, bounded timeout, and complete command,
  binary, input, output, runtime, memory, and disk provenance;
- full candidate-directory disk monitoring under a combined 50-GiB ceiling and
  80-GiB free-space floor;
- four threads and sequential-only width execution; and
- future-compatible selected records for decode, probes, each cluster width,
  and component report.

Add `configs/splits/sequence_partitions_v1.toml` with the already accepted
scientific parameters, fixed input expectations, seed `20260925`, resource
limits, and protected widths. Scientific thresholds and `--max-seqs 361180`
must not become arbitrary CLI overrides.

The runner may expose paths and test-only dependency injection needed for tiny
fixtures, but production defaults must remain under
`artifacts/splits/sequence_partitions_v1/`. Do not create a real component or
partition.

## Split-memory-limit correction gate

The new operational `--split-memory-limit 8G` flag is conditional on real-
binary proof during this checkpoint:

1. Run the same discriminating synthetic clustering fixture with the frozen
   production command with and without the 8-GiB limit. Require identical
   canonical component member sets and record the effective setting.
2. On a bounded synthetic fixture, use a deliberately small limit that the
   pinned binary confirms caused actual splitting, then compare its canonical
   component member sets with an unconstrained run.
3. Tests must fail if the alleged forced-split run did not really split.

Do not require raw TSV bytes, representative IDs, or MMseqs internal DB bytes
to match; those are not the biological component identity. If the pinned
binary cannot safely produce and disclose a forced split on a bounded fixture,
remove the production 8-GiB flag and document that the resource probe/stop
boundary remains the safeguard. Do not silently keep an unproven flag.

## Required synthetic tests

Use only temporary tiny CSV/FASTA data. Cover at least:

- config and CLI rejection of unknown widths, multiple stages, missing stage,
  `all`, mapping authorization absence, and scientific CLI overrides;
- dry-run causing no subprocess and no real input read;
- strict decode and exact/RC artifacts in an immutable generation;
- member and representative missing/duplicate/foreign reconciliation;
- changed config/input/upstream/tool evidence invalidating restart skips;
- nonzero exit, timeout, killed process, output growth past the disk allowance,
  low free disk, and selection-record write failure preserving prior evidence;
- unique log hashes and complete provenance;
- normalized membership determinism and component-member-set comparison;
- the split-memory-limit equivalence gate above against the real pinned binary;
  and
- no stage can advance automatically into a later checkpoint.

Do not overfit tests to implementation internals. Reuse accepted Task 002A
modules and Task 001 transaction/disk patterns where appropriate rather than
duplicating them.

## Verification and return

Run the focused split suite twice in `rbpbench-splits-002`, including all real-
binary split-limit tests with none skipped. Run the full repository suite from
a clean checkout and disclose, but do not repair, unrelated legacy coordinate
failures.

Commit only code, config, tests, directly affected docs, and small synthetic
fixtures. Return:

1. commit and changed-file list;
2. stage/transaction/restart/resource design summary;
3. split-memory-limit equivalence evidence, including proof the forced run
   actually split, or explicit removal of the 8-GiB flag;
4. two focused-suite results and one clean full-suite result;
5. `git diff --check`, staged-file audit, and clean worktree status;
6. confirmation that the real CSV, real Task 002 artifacts, references,
   models, and network were untouched; and
7. remaining gaps separated into blockers and later checkpoints.

Stop after the local commit. End exactly with:

`Task 002B-2 real decode was not started.`
