# Task 002B-1 orchestration implementation review

## Verdict

**Correction required before acceptance.** Commit `52fd295` provides a useful
runner foundation, and removing the unprovable `--split-memory-limit 8G` flag
correctly follows the planning reconciliation. The current orchestration must
not yet touch the real dataset because several guards described by the handoff
are present only as post-hoc checks or incomplete cache fingerprints.

This is one bounded convergence pass. It does not change clustering science,
reconsider the split-memory decision, reopen coordinates, or authorize 002B-2.

## Accepted work

- The CLI exposes one explicit stage, no `all`, protected width choices, and
  explicit MMseqs2 authorization.
- Scientific thresholds and `--max-seqs 361180` remain non-overridable.
- Decode, label-blind probe selection, membership reconciliation, deterministic
  outputs, unique logs, and the split-memory fallback are directionally
  correct and well tested on synthetic fixtures.
- The real-binary split-memory evidence is sufficient to remove the 8-GiB
  production flag. It does not need another review cycle.

## Blocking findings

### R1 — The accepted-stage chain is not actually enforced

The CLI requires only `decode` before either `probe` or `cluster`. A full
`cluster` invocation can therefore run before the three resource probes are
accepted. The existing tests call and accept this path directly.

Restart fingerprints also use cached state fingerprints rather than the exact
selected upstream generation digest. If decode is force-rebuilt under the same
input fingerprint, an earlier cluster can remain skippable even though its
record names the old decode generation. Similarly, decode can proceed after
the CSV changes without requiring a fresh passing preflight; it notices the
change but decodes it instead of failing against the frozen input hash.

Every selected record needs its own fingerprint and exact upstream generation
digest(s). Downstream stages must recompute the current chain and refuse stale
or missing prerequisites. Before any full cluster, all three probe records
must be accepted and current.

### R2 — Resource checks are post-hoc rather than protective

The 50-GiB ceiling is measured only after MMseqs2 exits. A process can therefore
fill the disk before the runner notices. Available memory is checked only after
a probe and is not checked before a probe or a full cluster; an unknown memory
measurement currently passes. The free-disk floor is not consistently checked
after every MMseqs2 stage.

Monitor the complete candidate plus Task 002 output directory while each child
process runs, enforce the free-space floor live, and terminate the complete
process group on timeout or resource violation. Available-memory measurement
must pass before every probe/full cluster and fail closed if unavailable.

### R3 — Generation transactions are incomplete

Probe/cluster input FASTA is written to a fixed mutable
`<stage>/<width>/input.fasta.tmp` outside the candidate generation. The full
cluster unnecessarily reads the entire accepted FASTA into a Python dictionary
and writes another full copy. Component-report outputs are also written to
fixed paths before its selection record commits.

In addition, selection-record write failures do not remove new decode,
probe/cluster, or report candidates. Move every generated input/output into its
attempt generation; use the accepted decode FASTA directly for a full cluster;
and make the selection record the sole atomic pointer. A failed final record
write must leave the prior selection and generation byte-identical and remove
the unaccepted candidate.

### R4 — Preflight does not enforce the accepted binary or host boundary

Preflight checks the MMseqs2 version but not the accepted binary SHA-256
`44afaca1d6d8a4c7709177782aa37203cd52651563c778d75f9ae2ee98bed635`.
It records host memory but does not require the accepted installed-memory
minimum or the current-memory launch gate. It also allows `None` from available
memory detection to pass later.

Pin and validate the binary hash in the production config, validate installed
RAM and current available memory fail-closed for MMseqs2 stages, and ensure all
MMseqs2 subprocesses—not only `cluster`—respect the four-thread cap.

### R5 — Selected evidence is incomplete

Cluster selection currently hashes membership and `db*` files, but omits
cluster-result files, logs, the generated input, and other retained generation
files. The component report binds decode artifacts but not all three exact
cluster generations. This weakens both restart revalidation and provenance.

Each selection record must inventory path, size, and SHA-256 for every retained
file in its accepted generation, bind exact upstream digests, and allow a later
revalidation to reject deletion or tampering. Component-report output must be
generation-scoped and bind decode plus all three cluster generation digests.

## Explicit deferrals

Real decode, real probes, real clustering, component-science diagnostics,
cleanup, partition assignment, and legacy coordinate failures remain outside
this correction. No cosmetic framework or second clustering tool is requested.

## Acceptance gate

Accept 002B-1 when regressions demonstrate current prerequisite chaining,
live resource termination, fail-closed host/binary validation, complete
generation transactions, and full retained-file evidence. All tests remain
synthetic except the already accepted small MMseqs2 binary checks. Do not begin
002B-2 in the correction turn.
