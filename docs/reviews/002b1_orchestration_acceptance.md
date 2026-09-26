# Task 002B-1 orchestration acceptance

## Verdict

**Accepted.** Commit `173b2a6` closes the final bounded findings against the
Task 002B runner. Checkpoint 002B-1 is complete; no further orchestration
hardening is required before real decode.

## Accepted evidence

- The current prerequisite chain is recomputed from the live config, CSV,
  audit JSON, proteins TSV, MMseqs2 version/hash, installed RAM, and free
  disk before downstream work can run or skip.
- Direct probe/cluster calls independently reject a non-accepted MMseqs2
  binary before launching a subprocess.
- Every MMseqs2 subprocess receives live process-group resource supervision
  and an unconditional final disk-ceiling/free-space check, including a fast
  process that exits before the first polling interval.
- Decode, probe/cluster, and component-report generations remain atomic and
  restart-safe, with complete retained-file inventories and exact upstream
  bindings.
- Component-report evidence snapshots the decode and all three cluster
  artifact manifests.
- Synthetic fixtures no longer depend on unrestricted macOS RAM discovery;
  dedicated tests retain fail-closed `None`/low-RAM coverage.
- Claude reported 188 synthetic split tests passing (15 expected real-binary
  skips) and 12/12 real-binary smoke tests passing with none skipped.
- The reviewer independently ran the bounded correction file in
  `rbpbench-splits-002`: 28/28 tests passed.
- No real dataset row, Task 002 artifact, reference, model, or network
  resource was touched during 002B-1.

## Convergence decision

The accepted removal of `--split-memory-limit 8G` remains final. Task 002B
will rely on the deterministic 10,000-ID resource probe and explicit stop
boundary before full clustering.

Minor framework polish or hypothetical provenance refinements are deferred.
From this point, a checkpoint is blocked only by a result-changing scientific
error, input/evidence corruption, or a realistic risk to the long real-data
execution.

## Next boundary

Checkpoint 002B-2 may run only `preflight` and `decode` as separate
invocations, then stop with a sanitized manifest. It may not launch MMseqs2
clustering or begin the 002B-3 probes.

