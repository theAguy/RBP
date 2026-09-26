# Task 002B-1 correction review

## Verdict

**Approve the direction, but one final bounded correction is required before
002B-1 acceptance.** Commit `acc677f` fixes the large defects identified in
the first review: full clustering is probe-gated, candidate generations are
transactional, MMseqs2 runs in a guarded process group, the accepted binary
hash and installed-RAM boundary are checked in preflight, and retained
generation files are inventoried completely.

No scientific rule needs to change. The accepted removal of
`--split-memory-limit 8G` remains closed. Real decode (002B-2) must not start
until the items below converge.

## Blocking findings

### F1 — The live preflight chain is still bypassable downstream

`main()` loads an intact preflight record before decode, but it does not
recompute and compare the current preflight fingerprint. Probe/cluster then
trust an intact decode record without proving that decode still descends from
a current preflight. Consequently, changes to `dataset_audit.json`,
`proteins.tsv`, or the installed MMseqs2 binary can bypass the accepted
preflight boundary.

Two independent reproductions against `acc677f` demonstrate the defect:

- after accepting preflight, mutating the audit JSON still allowed decode to
  complete and write `selected/decode.json`;
- after accepting preflight and decode, changing the fake MMseqs2 binary's
  bytes while preserving its reported version still allowed a probe to run
  and write `selected/probe_500.json`, despite no longer matching the pinned
  binary SHA-256.

This conflicts directly with C1's requirement that a dataset/config/audit/
proteins/binary change refuse downstream work and instruct the operator to
rerun the appropriate prerequisite.

### F2 — A fast process can cross the free-disk floor and still be accepted

`run_guarded_mmseqs()` checks timeout/disk limits only after a polling timeout.
When a process exits before the first poll, it records the final disk snapshot
but does not enforce it. The later stage-level post-check enforces only the
50-GiB output ceiling, not the 80-GiB free-space floor.

An independent fast-process reproduction returned successfully with a mocked
final `free_disk_gib_at_finish` of `0.0`, despite an 80-GiB required floor.
Every command must perform one unconditional final ceiling/floor check after
exit, including commands that finish before the first poll.

## Evidence/test correction

### F3 — Synthetic correction tests depend on host RAM discovery

The new tests set `min_installed_ram_gib = 0` but leave installed-RAM detection
unmocked. In the reviewer's restricted macOS environment, `sysctl` is not
available and the fail-closed detector correctly returns `None`; 17 of the 18
new correction tests then fail at fixture preflight rather than exercising
their intended behavior. Claude's unrestricted run may still be valid, but
the synthetic suite is not host-independent as claimed.

Synthetic fixtures should explicitly mock a sufficient installed-RAM value.
Dedicated fail-closed RAM tests must continue to exercise `None` and low
values. This changes no production behavior.

## Small provenance completion

C5 explicitly requested that the component-report record bind the selected
artifact manifests for decode and all three cluster generations. The current
record binds their fingerprints/digests but does not snapshot their artifact
manifests. Add those manifests to the accepted component-report record. This
is an evidence-completeness correction, not a new computation.

## Acceptance boundary

The final correction is limited to:

1. current preflight/decode-chain validation before every downstream action;
2. unconditional post-process disk-floor/ceiling enforcement;
3. host-independent synthetic fixtures; and
4. component-report upstream artifact-manifest binding.

Do not alter clustering flags, thresholds, probe selection, component logic,
or resource limits. Do not access the real CSV or begin 002B-2.
