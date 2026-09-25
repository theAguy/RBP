# Executor handoff — Task 001B checkpoint B3B-2 indexing and probe

Claude, execute B3B-2 only: build the accepted hg38 indices, then run the
guarded feasibility probe. B3B-1 is accepted in
`docs/reviews/001b_b3b1_acceptance.md`.

## Git and required reading

1. Work only on `issue-001b-coordinate-execution`; verify `b0409b6` and this
   acceptance/handoff commit are ancestors of `HEAD`, the expected origin,
   and a clean tracked worktree.
2. Read the B3B-1 acceptance, `docs/tasks/001b_b3_hg38_preparation.md`, the
   B3A probe acceptance/reviews, `docs/COORDINATES.md`, the accepted B2/B3
   manifests, and the index/probe implementation before execution.
3. Use `rbpbench-coord-001b` with the pinned real binaries first on `PATH`.
   Do not push, merge, rewrite history, or work on `main`.

## Authorization boundary

Authorized, sequentially:

1. one guarded `index:hg38` invocation;
2. only after index acceptance checks pass, one guarded `probe:hg38`
   invocation;
3. validation/hashing of their accepted evidence;
4. update and local commit of only
   `manifests/coordinate_preparation_hg38_b3.json`.

Not authorized:

- network, download, derive, hg19, `--force`, or `--stage all`;
- align, exact-match, report, combined-report, cleanup, or the B4 full
  10,100-query workflow;
- code/test/config/source/reference/policy/threshold/budget changes;
- deleting accepted source/derived/index/probe evidence or silently retrying
  a failed stage.

Use exactly one build-scoped stage per runner invocation. Both index and
probe already perform their own fresh, input-bound preflight immediately
before real subprocesses; require it to pass. Stop on any failure or gate
violation.

## Frozen inputs

Revalidate before index execution:

- B3 manifest `manifests/coordinate_preparation_hg38_b3.json`, checkpoint
  `001B-B3B-1`, status `B3B-1 passed`, commit `b0409b6`;
- selected reference
  `references/derived/hg38/generations/derive_588ed69489274b01/reference.fna`,
  size 3,138,203,434 bytes, SHA-256
  `5e3bf613355c96c2b78fcfdb26dc1fafe7279fbacd0f25b87d899d9186a53676`;
- selected manifest beside it, size 26,775 bytes, SHA-256
  `f27fb2d38b54de99d38afe456314f12c4c3d6d1fa96d90d2def573c35c4ca01e`;
- 191 contigs and total 3,099,457,607 bases under the accepted frozen policy;
- accepted B2 manifest and its 10,000 biological plus 100 control records;
- non-executed pre-B3B-2 `indices/hg38/index.json` SHA-256
  `da375f2259a696bc1a2baadbb4010bd2acd6532816be4cb9423a401500f4f37f`;
- state complete only through `derive:hg38`, and no existing accepted probe;
- current host/tool versions, volume identity, at least 80 GiB free, and a
  passing 30-GiB projected ledger.

If any binding/hash/count/state differs, stop without execution.

## Step 1 — hg38 index

Run the frozen common runner arguments with:

```text
--build hg38 --host-role approved_mac --allow-mapping --threads 4
--reference hg38=references/derived/hg38/generations/derive_588ed69489274b01/reference.fna
--reference-manifest hg38=references/derived/hg38/generations/derive_588ed69489274b01/reference_manifest.json
--stage index
```

Do not include another stage. Capture external command/resource evidence
under new non-overwriting persistent names such as `07_index.*`.

Require:

- fresh preflight passes against the exact reference, manifest, host,
  resources, threads, and pinned BWA 0.7.19/minimap2 2.31/SeqKit 2.13.0;
- exact frozen commands: BWA index and minimap2 `-x splice:sr -I 8G`;
- both tools exit zero with separate persistent stdout/stderr;
- one immutable selected index generation and executed `index.json`;
- all expected BWA and minimap2 files exist and match recorded hashes/sizes;
- index manifest binds build, reference SHA-256, and both raw/canonical
  reference-manifest hashes;
- minimap2 resolves `k=15`, `w=5`, non-HPC, one part, with no override or
  multipart warning;
- generation digest, commands, binary hashes/versions, elapsed time, peak
  memory, output sizes, disk/free-space, and ledger evidence reconcile.

If index fails, preserve the prior non-executed record/candidate transaction,
return the failure, and do not run probe.

## Step 2 — guarded feasibility probe

Only after all index checks pass, run a separate runner invocation with the
same frozen common/reference arguments plus the accepted B2 manifest and:

```text
--build hg38 --host-role approved_mac --allow-mapping --threads 4
--b2-manifest manifests/coordinate_sampling_b2.json
--stage probe
```

Do not pass manual index overrides; the runner must reload the accepted
`index.json`. Capture external command/resource evidence under new names such
as `08_probe.*`.

Require:

- fresh preflight and clean resolved Git commit before subprocesses;
- exact B2 binding: 10,000 biological and 100 control IDs, with the
  transactional 10,100-record pattern FASTA internally reconciled;
- largest contig selected from verified current reference lengths:
  `NC_000001.11`, 248,956,422 bases; total reference bases 3,099,457,607;
  scale approximately 12.4498;
- deterministic 500-nt A/C/G/T smoke window recorded by coordinates only;
- one-thread BWA-MEM and minimap2 smoke runs exit zero and each has exactly
  one mapped primary record on an accepted contig;
- one pinned SeqKit invocation searches all 10,100 patterns against only the
  extracted largest contig; BED rows are streamed, unique, known-ID,
  single-contig, and coordinate-valid;
- candidate workspace is removed before acceptance; selected probe evidence
  remains within its 1-GiB cap and the shared 4-GiB build-output cap;
- all three fail-closed B4-safety projections pass:
  - projected full-reference SeqKit time below 4.5 hours;
  - projected output within the provisional 1-GiB exact-match share;
  - observed peak RSS plus 2 GiB fits physical and measured available/
    reclaimable memory;
- accepted `probe.json` binds B2, reference, raw/canonical manifest, index
  generation, binaries, commands, Git commit, outputs, resources, and
  projection evidence.

A failed smoke, malformed/oversized output, unavailable memory evidence, or
failed projection is a valid B3 result but not permission to tune/retry.
Stop and report it without proceeding to B4.

## Sanitized manifest, return, and stop

If both stages pass, update the existing B3 manifest to checkpoint/status
`001B-B3B-2` / `B3B-2 passed`, preserving B3B-1 evidence and adding:

- exact index/probe commands, logs, hashes, sizes, timings, peak memory, and
  disk/ledger snapshots;
- selected index/probe generation IDs and all binding evidence;
- resolved minimap2 parameters and smoke-mapping results;
- largest-contig/window/pattern/BED reconciliation without sequences or
  complete SAM/BED content;
- observed probe metrics and every projection formula/input/result/gate;
- an explicit conclusion: `B4 operationally eligible` only when every gate
  passes, but `B4 not started and still requires reviewer authorization`;
- proof that no prohibited stage/build/network/cleanup action ran.

Validate the JSON and run `git diff --check`; commit only the sanitized B3
manifest. No reference, index, probe output, log, state, provenance, or
ledger artifact may be staged.

Return commands/statuses, index and probe evidence, projection results,
resources/disk, boundary proof, staged-file audit, commit, worktree status,
and every anomaly. Stop after the local manifest commit. End exactly with:

`Task 001B checkpoint B4 was not started.`
