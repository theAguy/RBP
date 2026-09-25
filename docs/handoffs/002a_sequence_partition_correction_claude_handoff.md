# Executor handoff — Task 002A bounded correction

Claude, correct the accepted scope of checkpoint 002A only. Do not open the
real CSV, generate real dataset FASTAs, or begin 002B.

## Git and required reading

1. Work on `issue-002-sequence-partitions` from the commit containing this
   handoff. Verify the expected origin, a clean tracked worktree, and
   `6321356f8025a32fe6e71fc6db711d3738730ce8` as an ancestor. Do not push,
   merge, or rewrite history.
2. Read:
   - `docs/reviews/002a_sequence_partition_pipeline_review.md`;
   - `docs/tasks/002_sequence_clustered_partitions.md`;
   - `docs/reviews/002_sequence_clustered_partitions_reconciliation.md`;
   - `docs/SPLITS.md` and `docs/DECISIONS.md`.
3. Keep the correction inside `src/rbpbench/splits/`, its tests, and directly
   affected documentation/environment evidence. Do not change coordinate code.

## Required corrections

### C1 — Encode the actual per-width similarity rule

Make clustering and audit-search command construction require one of the three
protected widths and select only this frozen mapping:

| Width | Minimum identity | Bidirectional coverage |
|---:|---:|---:|
| 500 | 0.90 | 0.80 |
| 251 | 0.90 | 0.95 |
| 101 | 0.90 | 0.95 |

Both commands must pass `--min-seq-id 0.90`, `-c` with the mapped coverage,
`--cov-mode 0`, and every previously frozen applicable flag. Reject an unknown
width before process execution. Do not expose identity/coverage as arbitrary
caller overrides.

### C2 — Prevent sensitivity truncation

Pass `--max-seqs 361180` to both clustering and audit search. This equals the
complete fixed dataset universe and avoids a smaller MMseqs2 default silently
discarding qualifying edges. Do not substitute a smaller value. A future real
resource failure is a stop condition, not permission to weaken this setting.

### C3 — Prove semantics with discriminating real-binary fixtures

Using only synthetic sequences and the pinned `rbpbench-splits-002` binary,
test all three width rules with fixtures that distinguish the intended setting
from the old defaults. At minimum prove:

- an above-90%-identity full-length pair groups and a clearly below-90% pair
  does not;
- a shifted pair meeting 80% full-window coverage groups, while a clearly
  sub-80% full-window overlap does not;
- 251- and 101-nt pairs meeting 95% coverage group, while clearly sub-95%
  overlaps do not;
- exact and non-palindromic reverse-complement duplicates still group; and
- audit search applies the same width-specific identity/coverage rule and both
  strands.

Use margins rather than fragile floating-point boundary equality. Capture or
assert the binary's effective settings so omission of `--min-seq-id`, `-c`, or
`--max-seqs` fails a regression. The scientific regressions must fail on
parent `6321356`.

### C4 — Preserve every command's evidence

Make stdout/stderr log paths unique for every invocation, including two
`createdb` calls sharing one log directory. Add a test that executes the same
tool twice and then re-hashes both earlier returned paths successfully; neither
record may point at overwritten content.

### C5 — Fail closed on foreign audit IDs

The closed-universe cross-partition audit must raise on any edge endpoint not
present in the assignment mapping. Do not silently skip it. Test both endpoint
positions and retain ordinary same-partition/cross-partition behavior.

## Verification and return

Run the focused synthetic suite with the real pinned binary, then run the full
repository suite from a clean exported/temporary checkout so ignored real
artifacts cannot influence it. If unrelated legacy tests still fail, return
their exact names and demonstrate that the focused split suite is green; do not
edit coordinate behavior.

Commit only the bounded correction. Return:

1. correction commit and changed-file list;
2. C1-C5 resolution;
3. focused tests and proof the discriminating tests fail on `6321356`;
4. two focused-suite results with the real binary and one clean-checkout full
   suite result;
5. `git diff --check`, staged-file audit, and clean-worktree status;
6. confirmation that no real CSV/reference/B2 artifact or network resource was
   accessed; and
7. remaining gaps, separated into blockers and later-checkpoint work.

Stop after the local commit. End exactly with:

`Task 002B real sequence grouping was not started.`
