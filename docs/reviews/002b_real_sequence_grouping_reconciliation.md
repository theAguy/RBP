# Task 002B planning-review reconciliation

## Verdict

**Approve with one bounded correction, reconciled.** The staged execution
design is accepted. Only checkpoint 002B-1, using synthetic fixtures, may begin
through its separate executor handoff. No real CSV access or MMseqs2 execution
over real dataset sequences is authorized.

## Accepted findings

- The frozen three-width identity/coverage rule, input hashes, label-blind
  boundary, and separation from 002C match the accepted parent task.
- Splitting orchestration, real decode, resource probes, each full width, and
  component union into separately reviewed checkpoints is appropriate for the
  16-GiB host.
- The 50-GiB artifact ceiling, 80-GiB disk floor, four threads, sequential
  widths, 12-hour timeout, immutable generations, and fail-closed resource
  behavior are accepted as operational safeguards.
- `--max-seqs 361180` remains immutable. Resource pressure is a stop condition,
  not permission to weaken the scientific rule.
- The component gate and sanitized aggregate diagnostics are sufficient for
  002B; deeper diagnosis is needed only if a gate actually trips.

## Bounded correction

`--split-memory-limit 8G` was not part of Task 002A's real-binary proof and can
change MMseqs2's chunking path. Checkpoint 002B-1 must therefore demonstrate
component equivalence both with the production 8-GiB value and with a separate
small value that is verified to trigger splitting. The comparison is between
canonical component member sets, not raw DB files or arbitrary representative
IDs.

If equivalence or actual forced splitting cannot be demonstrated, the 8-GiB
flag is removed before real execution. No further planning-review round is
needed for that conservative removal. Any proposal to keep a behavior-changing
flag after failed equivalence proof would require new review.

## Deferrals

Manifest naming, post-acceptance database cleanup, partition optimization,
cross-partition audits, model work, coordinate recovery, and additional
clustering packages remain outside 002B-1.
