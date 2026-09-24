# Executor handoff — Task 001B checkpoint B3A final correction

Claude, make only the three final corrections in
`docs/reviews/001b_b3a_correction_review.md` on
`issue-001b-coordinate-execution`, starting from `bd1d671` and this handoff
commit.

## Authorization boundary

This is a source/test/documentation correction on tiny synthetic fixtures.
Do not open or hash the real CSV. Do not use the real B2 FASTAs in tests. Do
not access the network or NCBI, and do not download, derive, index, or map a
human reference. Do not begin B3B or any later checkpoint. Commit locally;
do not push, merge, or rewrite history.

## Required changes

1. **One canonical probe fingerprint.** Factor a stable command-semantics
   representation that is independent of random generation/candidate paths.
   Use it for both the accepted `probe.json` fingerprint and every restart
   recomputation. Preserve exact executed argv/path strings separately in
   tool provenance.
2. **One truly live shared output counter.** Include prior retained probe
   bytes before the first new writer. After each BWA, minimap2, and SeqKit
   call, immediately charge that call's stdout plus stderr to both the probe
   1-GiB counter and the shared 4-GiB counter. Each next writer must see both
   reduced remainders. Store cumulative retained probe bytes in `probe.json`,
   but do not double-charge the cumulative total at completion.
3. **Exact observed contig lengths.** Replace the total-only reference scan
   with a streaming per-accession length scan. Reject malformed/empty or
   duplicate headers and sequence before a header. Require the observed map
   to equal manifest `contig_lengths` exactly, then derive `Ltotal` and the
   largest-contig selection from that verified evidence.

Do not change the accepted B2 anchor, scientific policy, commands, versions,
projection formulas, thresholds, or resource ceilings.

## Mandatory regressions

Add focused tests that fail on `bd1d671` for:

- an accepted probe fingerprint versus an unchanged restart recomputation;
- a complete guarded success followed by an unchanged restart skip, proving
  no subprocess and no new generation occurs;
- invalidation of that skip when a binary, stable command semantic, Git
  commit/clean state, B2 evidence, raw reference manifest, or index digest
  changes;
- three individually sub-limit tool outputs whose cumulative bytes exceed
  the shared remaining allowance;
- a retry where prior retained probe bytes plus other accepted build outputs
  leave less than the new generation requires;
- a successful retry showing each shared/probe charge occurs exactly once;
- a three-contig reference whose declared non-largest lengths are
  redistributed while keys and total remain unchanged;
- duplicate/malformed FASTA headers and sequence before a header.

Run the focused tests and the full suite twice with the pinned environment's
bin directory first on `PATH`; report real-binary executed/skipped counts.
Run `git diff --check`, audit staged files, and confirm a clean worktree.

## Required return and stop

Return:

1. correction commit and changed-file list;
2. F1-F3 resolution;
3. focused test names/count and proof they fail on `bd1d671`;
4. two full-suite results and real-binary count;
5. unchanged-restart skip proof and shared-budget before/after accounting;
6. staged-file audit, `git diff --check`, and worktree status;
7. confirmation that real data/network/human-reference work was untouched;
8. every remaining gap.

Stop after the local commit and end exactly with:

`Task 001B checkpoint B3B was not started.`
