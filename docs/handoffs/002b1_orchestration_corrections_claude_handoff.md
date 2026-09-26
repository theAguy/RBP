# Executor handoff — Task 002B-1 bounded orchestration corrections

Claude, correct commit `52fd295` only as described below. Use synthetic
fixtures. Do not open the real CSV or begin checkpoint 002B-2.

## Git and reading

1. Work on `issue-002-sequence-partitions` from the commit containing this
   handoff. Verify the expected origin, clean tracked worktree, and `52fd295`
   as an ancestor. Do not push, merge, or rewrite history.
2. Read:
   - `docs/reviews/002b1_orchestration_review.md`;
   - `docs/tasks/002b_real_sequence_grouping.md`;
   - `docs/reviews/002b_real_sequence_grouping_reconciliation.md`; and
   - `docs/handoffs/002b1_orchestration_claude_handoff.md`.
3. Preserve the accepted removal of `--split-memory-limit 8G`. Do not rerun or
   redesign that decision.

## C1 — Enforce the exact accepted-stage chain

- Put the current stage fingerprint in every selection record.
- Bind decode to the current accepted preflight fingerprint.
- Bind every probe/cluster to the exact selected decode generation digest.
- Require all three accepted, current probe generations before any full-width
  cluster can launch.
- Bind component report to the exact selected decode generation and all three
  selected cluster generations.
- Treat `state.json` as a cache only; a cached value may never override a stale
  or mismatched selection record.

Recompute the complete current prerequisite chain on every non-dry invocation.
If the dataset/config/audit/proteins/binary changes, refuse the downstream
stage and instruct rerunning preflight/decode as appropriate; do not decode or
cluster the changed input under an old acceptance. If decode is force-rebuilt,
even from byte-identical source data, its new selected generation must
invalidate clusters that name the old generation.

## C2 — Enforce resource gates while the process is running

- Before probe or cluster, require a numeric available-memory measurement at
  or above the configured launch threshold. `None` is a hard failure.
- During every MMseqs2 subprocess, poll the whole Task 002 output tree and the
  candidate generation, enforcing both the 50-GiB combined ceiling and 80-GiB
  free-space floor before the filesystem can run away.
- On timeout or resource violation, terminate the entire subprocess group,
  including grandchildren, wait for it to exit, discard the candidate, and
  preserve any prior selection.
- Recheck disk and record resource evidence after successful completion.

Add a fake tool that grows a file while sleeping and prove it is terminated
before natural completion when the allowance is crossed. Add a fake child
that spawns a grandchild and prove timeout/resource termination leaves no
writer continuing in the candidate.

## C3 — Complete generation transactions

- Put probe subset FASTA inside its candidate generation.
- For a full cluster, pass the accepted decode FASTA directly; do not load all
  real sequences into a dictionary merely to write a second full copy.
- Put component membership and report inside a fresh report generation, not at
  fixed mutable output paths.
- The atomic selection record is the sole accepted pointer for decode,
  probe/cluster, and component report.
- Wrap every final selection-record write. If it fails, remove that attempt's
  candidate and leave a prior record/generation byte-identical.
- Remove abandoned candidate input/output on command, reconciliation, resource,
  or timeout failure while retaining sufficient small rejected-attempt evidence
  outside the candidate if needed for diagnosis.

## C4 — Make preflight fail closed

- Add the accepted MMseqs2 SHA-256 to the production config and validate both
  it and version before acceptance. Tiny fixture configs may pin their own fake
  binary hashes explicitly.
- Require at least the accepted installed-memory minimum on the production
  host and a numeric current available-memory result for MMseqs2 launch gates.
- Apply the configured four-thread cap to `createdb`, `cluster`, and
  `createtsv` invocations. Keep scientific flags non-overridable.

Do not make tests dependent on the reviewer's current working-directory
artifacts. Resolve declared production paths from an explicit repository root
or another deterministic documented base, and test invocation from a different
current directory.

## C5 — Complete selected evidence and report transaction

- Inventory every retained regular file in an accepted generation with path,
  byte size, and SHA-256. Revalidation must reject a missing, added, or
  modified retained file—not just the current membership/`db*` subset.
- Persist exact commands, unique log paths/hashes, binary identity, runtime,
  resource evidence, stage fingerprint, and upstream generation digests.
- Make the component-report fingerprint/restart decision use all current
  upstream digests; bind those digests and all corresponding selected artifact
  manifests into the report record.
- Do not claim “per-width contribution” as raw membership-row count. Either
  implement a scientifically meaningful merge/contribution definition and
  test it, or rename/defer that field until 002B-7.

## Required regressions

Add tests that fail on `52fd295` and prove at least:

1. same-row-count CSV mutation after accepted preflight makes decode refuse
   before creating a generation;
2. force-replacing decode invalidates an old cluster even when source bytes are
   unchanged;
3. cluster refuses before all three current probes and launches no subprocess;
4. stale/tampered probe or cluster upstream evidence blocks downstream work;
5. binary with correct version but wrong SHA fails preflight;
6. missing/unknown/low available-memory evidence prevents MMseqs2 launch;
7. live disk growth and a grandchild writer are stopped, with prior evidence
   untouched;
8. all three MMseqs2 commands use no more than four threads;
9. selection-record write failures for decode, probe/cluster, and report remove
   the new candidate and preserve a prior acceptance;
10. component-report interruption cannot overwrite accepted report artifacts;
11. added, deleted, or changed generation files invalidate revalidation; and
12. running from outside the repository resolves the declared frozen inputs
    deterministically.

Tests may inject tiny resource thresholds and fake executables. Do not access
the real dataset, real Task 002 artifact directory, references, or models.

## Return and stop

Run the focused split suite twice in `rbpbench-splits-002`, including the real
binary tests with none skipped, and one clean-checkout full suite. Do not fix
unrelated coordinate failures.

Commit only the bounded correction and return:

1. commit and changed-file list;
2. C1-C5 resolution;
3. focused regression results and proof the new tests fail on `52fd295`;
4. two focused-suite results plus the clean full-suite result;
5. `git diff --check`, staged-file audit, and clean status;
6. confirmation that no real CSV/artifact/reference/model/network was touched;
   and
7. remaining gaps separated into blockers and later checkpoints.

Stop after the local commit. End exactly with:

`Task 002B-2 real decode was not started.`
