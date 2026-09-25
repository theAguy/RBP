# Task 001B B3B-2 resource stop and coordinate deferral

## Verdict

**Accept the guarded stop; do not retry. Defer the remaining coordinate track
and activate the prespecified sequence-clustering fallback.**

This is an infrastructure feasibility result, not a biological mapping result.
No coordinate mapping was completed, so the project must not report mapping
rates, genomic loci, splice rescue, or build comparisons from this attempt.

## Evidence reviewed

- The guarded attempt ran from `fce6eb8` on the accepted hg38 reference.
- BWA 0.7.19 completed its index in 4,600.957 seconds.
- Minimap2 2.31 reached minimizer collection for the frozen single-part
  `splice:sr` index and was killed by the operating system for low memory on
  the 16-GiB host.
- The required 0-byte `.mmi` proves that minimap2 did not complete.
- The accepted selection record `indices/hg38/index.json` remained unchanged,
  with SHA-256
  `da375f2259a696bc1a2baadbb4010bd2acd6532816be4cb9423a401500f4f37f`.
- Probe, full mapping, exact matching, reporting, hg19, and model work did not
  start.
- The failed generation contains 5,424,083,332 bytes. Every file hash and
  size is frozen in
  `manifests/coordinate_index_hg38_b3b2_stop.json` before cleanup.
- A standard Google Colab check returned only 12.7 GiB RAM, two CPUs, and
  87.4 GiB free disk; it provides less memory than the failed host.

## Scope decision

The project will not:

- retry the same operation on a 16- or 24-GiB Mac;
- pay for or depend on a high-memory cloud runtime;
- weaken the frozen single-part-index contract;
- add multipart minimap2 engineering;
- silently continue with BWA alone and call that the accepted coordinate
  study; or
- allow Task 001 to delay the core benchmark further.

The accepted GRCh38 source and deterministic derived reference remain valid
and reproducible. They may be reused if a future collaborator supplies an
adequate high-memory host, but coordinates are not a prerequisite for the
submitted model or its competitors.

## Cleanup decision

The unaccepted failed candidate
`indices/hg38/generations/index_bfeb7be42185425f` may be removed only through
the bounded cleanup handoff. The accepted index selection record, sources,
derived reference, committed manifests, and persistent attempt logs must stay.

## Next scientific action

Use sequence similarity, computed without model predictions, to keep highly
similar windows in the same train/validation/test partition. Task 002 first
requires one second-review pass on its grouping thresholds and split design;
it does not reopen coordinate recovery.
