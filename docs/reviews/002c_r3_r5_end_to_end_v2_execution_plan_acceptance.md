# Task 002C-R3–R5 end-to-end plan — acceptance

## Verdict

**Accepted after bounded corrections. No further planning review is required.**

The second reviewer read the complete plan, accepted the one-package design
and unchanged similarity relation, and requested five bounded plan-text
corrections. All five are incorporated in
`docs/tasks/002c_r3_r5_end_to_end_v2_execution.md` before implementation.

## Reconciliation

### C1 — internally consistent disk and quota gates

Before each construction or audit width, required live free space is now the
80-GiB floor plus that width's job-owned ceiling: 140 GiB at 500 nt, 105 GiB
at 251 nt, and 95 GiB at 101 nt. Quota headroom must be at least 80 GiB and is
rechecked when the scheduler/filesystem exposes it; otherwise a recorded
operator attestation is mandatory. The scientific settings are unchanged.

### C2 — prove that a zero-hit audit actually searched the right data

Every partition FASTA is reconciled to final membership and to per-record
sequence hashes from the accepted full FASTA. Every MMseqs2 database is checked
through both its `.lookup` IDs and a strict `convert2fasta` round trip. Each
width also runs deterministic self-hit and construction-edge positive controls
before the six directed audits. Empty, incomplete, foreign, or substituted
audit input therefore fails before a zero-hit result can be accepted.

### C3 — preserve the historical accepted relation

All members of every accepted v1 component are a separately identified
protected co-membership relation in components v2. They are not called direct
alignment edges. Consequently v2 may merge v1 components but may never split
one; the explicit split count must be zero. Giant-component gates remain in
force after those joins. Final verification also uses a separate breadth-first
component implementation.

### C4 — role-aware return sanitation

The R2 blanket ban on TSV/GZIP/large files is retired for this package.
Named normalized-edge, membership, and audit-violation artifacts are parsed
through role-specific schemas after streaming decompression and have explicit
size limits tied to accepted stage ceilings. Reports and logs are scanned for
raw nucleotide strings. STOPPED audit returns include complete ID-pair evidence
with width and direction; it is never silently truncated.

### C5 — closed resume contract

Resume is allowed only after scheduler timeout, caught signal, or a corrected
external resource stop, with all accepted evidence current. It is refused
after terminal scientific or integrity stops. Every attempt produces a unique,
linked return; the verifier accepts a series. The first signal latches one
non-reentrant packaging path, while later catchable signals are only recorded.

## Incorporated reviewer refinements

- Assignment label-count dictionaries use fixed protein order before any
  floating-point objective evaluation.
- The exact/RC audit uses an implementation independent of the construction
  canonicalization helper.
- Per-audit timeout is the lesser of the remaining width budget and time before
  the two-hour packaging reserve.
- When the partition maximum is 20–48 hours, the operator wrapper may submit a
  dependency-ordered restart chain totalling at least 48 hours.
- First-cycle audit-discovered direct edges trigger exactly one predefined
  rebuild/reassignment/re-audit cycle. A pair already protected but split is an
  integrity failure; a second-cycle hit is a terminal scientific failure.

## Boundary

This acceptance authorizes implementation, synthetic/real-binary tests, and
portable-package construction only. It does not authorize opening real inputs
during implementation tests, submitting Darwin, running full MMseqs2 searches,
starting baselines, or training a model. Implementation and the immutable
package receive one combined review before real execution.
