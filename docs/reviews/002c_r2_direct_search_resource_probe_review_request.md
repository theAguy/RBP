# Task 002C-R2 direct-search resource probe — second-review request

## Requested verdict

Review `docs/tasks/002c_r2_direct_search_resource_probe.md` as a plan only.
Return **approve**, **approve with bounded corrections**, or **reject**, with
specific reasons. Do not implement code, open real artifacts, run MMseqs2, use
the network, or begin R2/R3 execution.

## Context

The v1 assignment was internally component-safe but failed its first fresh
direct audit: the 500-nt train-to-validation search returned 4,792 qualifying
pairs involving 3,576 rows. The return package was independently validated;
the failure is scientific rather than environmental.

Task 002C-R1 is accepted at `d57a266`. It provides synthetic-tested command,
edge-normalization, and components-v2 code. The corrective design requires
three full all-vs-all searches using the audit-equivalent relation, but their
runtime/output cost is not yet known. R2 measures that cost before any full
run is authorized.

## Questions

1. Is a deterministic 10,000-query subset against the complete 361,180-target
   database the right bounded probe for full-target memory and per-query
   runtime/output density?
2. Are the linear `36.118` projection and separately labelled 1.5 safety
   envelope scientifically honest, provided database-creation time is not
   multiplied as a per-query cost?
3. Are the proposed 64-GiB physical/24-GiB available RAM, 100/80-GiB disk,
   10-GiB probe-output, two-hour timeout, 48-GiB projected-memory, 25-GiB
   retained-artifact, and 12-hour-per-width/24-hour-total gates proportionate?
4. Is result-cap saturation, MMseqs2 warning inspection, and the requested
   per-query hit distribution enough to detect an invalid projection?
5. Is it correct that probe edges can never be reused as scientific v2 edges?
6. Does the return-package boundary retain enough evidence while excluding
   large/raw sequences and MMseqs2 databases?
7. Can implementation/package verification and one collaborator execution
   remain one R2 task without risking accidental progression into R3?
8. Is any additional issue genuinely blocking before implementation, as
   opposed to an engineering refinement that can wait for R3?

## Scope discipline

Prioritize whether this probe can support a safe yes/no R3 decision. Do not
request alternative aligners, new similarity thresholds, partition repair,
model work, coordinates, cloud infrastructure, or cosmetic framework changes.
Any proposed correction must identify the concrete failure it prevents and the
earliest point where it is needed.
