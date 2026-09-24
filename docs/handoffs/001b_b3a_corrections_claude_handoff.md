# Executor handoff — Task 001B checkpoint B3A corrections

Claude, correct commit `1f14adc` on
`issue-001b-coordinate-execution` according to
`docs/reviews/001b_b3a_review.md`. This is a code/test correction only.

## Required reading and Git boundary

1. Verify `1f14adc` and this handoff commit are ancestors of `HEAD`.
2. Read:
   - `docs/reviews/001b_b3a_review.md`;
   - `docs/reviews/001b_b3_reconciliation.md`;
   - `docs/tasks/001b_b3_hg38_preparation.md`;
   - `docs/handoffs/001b_b3a_claude_executor_handoff.md`;
   - `manifests/coordinate_sampling_b2.json`;
   - `docs/reviews/001b_b2_acceptance.md`.
3. Inspect the current probe, runner, manifest, index-binding, budget,
   provenance, and B2 artifact formats before editing.
4. Commit locally on the same branch. Do not push, merge, rewrite history, or
   work on `main`.

## Authorization boundary

Only source, tests, tiny synthetic fixtures, and necessary documentation may
change. Do not open or hash the real CSV or real B2 FASTAs during development
or tests. Do not access the network or an NCBI URL. Do not download, read,
derive, or index a human reference. Do not begin B3B, B4, B5, B6, or B7.

## Required corrections

Implement B3A-R1 through B3A-R7 literally:

1. Replace free-form caller hashes as the real CLI trust anchor with verified
   accepted B2-manifest evidence. Bind the manifest to the committed accepted
   checkpoint, verify every named artifact's path/size/hash, derive and check
   exact biological/control ID sets, and enforce 10,000 plus 100 in real CLI
   mode. Keep smaller fixtures behind a non-CLI test seam only.
   Specifically, the accepted trust anchor is
   `manifests/coordinate_sampling_b2.json` at acceptance commit `e62026b`, raw
   SHA-256
   `2dbe37bcdad4622e2801d1b42169acd5e2096a4ef6a8625fee99766c52f4e200`.
2. Fully validate `contig_lengths` before selection. Fully bind both selected
   index types to build, actual paths/files, reference hash, canonical and raw
   manifest hashes, and the recomputed current index-generation digest.
3. Make accepted-record and runner restart validity use the same complete
   stable fingerprint inputs. Require a resolved clean Git commit before any
   real subprocess. Recompute and compare the accepted fingerprint on every
   proposed restart skip.
4. Hash/revalidate all three stdout and all three stderr files; include all
   six in the generation digest. Fail closed if candidate cleanup is not
   complete. Do not let retained superseded generations escape disk/shared
   budget accounting.
5. Enforce the candidate 1-GiB bound on observed growth. Live-cap each tool by
   both the remaining probe 1-GiB share and remaining shared 4-GiB build
   budget; reject overflow before selection.
6. Stream BED validation and validate complete BED6 semantics. Implement and
   record the accepted wall/output/memory projection evidence and fail-closed
   gates, including measured available/reclaimable memory.
7. Exercise the actual guarded `stage_probe` path with pinned real binaries
   on tiny fixtures, not only its helpers.

Do not change frozen source values, contig policy, mapper/SeqKit parameters,
scientific thresholds, or resource ceilings.

## Mandatory regressions

Add tests that fail on `1f14adc` for at least:

- arbitrary caller-matched FASTA hashes not anchored to accepted B2 evidence;
- real CLI population counts other than 10,000 plus 100;
- biological ID mismatch with accepted `sample_ids.tsv` and control-ID-set
  mismatch;
- malformed or drifted B2 manifest/artifact path, size, hash, status, or
  checkpoint identity;
- malformed/mismatched `contig_lengths` keys, values, and total at the probe
  boundary;
- wrong index-manifest build, raw-manifest hash, actual path, or recomputed
  generation digest;
- dirty/unresolved Git state and restart changes to binaries, commands,
  implementation commit, raw manifest, expected B2 evidence, or index digest;
- mutated/missing stderr evidence after acceptance;
- failed candidate-directory removal;
- candidate work exceeding 1 GiB and probe output exceeding the remaining
  shared 4-GiB allowance despite being below its own 1-GiB cap;
- large BED validation without `read_text()`/whole-file materialization,
  invalid score/strand, and existing ID/bounds/duplicate cases;
- unavailable/insufficient available memory, failed time/output projections,
  zero-hit projection annotation, and complete passing projection evidence;
- a pinned-real-binary tiny `stage_probe` run through authorization,
  preflight, binding, budgets, transaction, and `probe.json` selection.

Prove the focused tests fail on `1f14adc` and pass on the correction commit.
Run the full suite twice with
`/opt/miniconda3/envs/rbpbench-coord-001b/bin` first on `PATH`, report the
real-binary executed/skipped counts, run `git diff --check`, and audit staged
files for generated or large artifacts.

## Required return and stop

Return:

1. correction commit and complete changed-file list;
2. itemized R1-R7 resolution;
3. focused regression names/count and proof of failure on `1f14adc`;
4. two full-suite results and guarded real-binary stage result;
5. B2/reference/index/fingerprint/restart evidence;
6. disk/memory/projection/streaming/retention evidence;
7. `git diff --check`, staged-file audit, and clean-worktree status;
8. confirmation that real data, network, NCBI, and human references/indices
   were untouched;
9. all remaining gaps.

Stop after the local correction commit. End with exactly:

`Task 001B checkpoint B3B was not started.`
