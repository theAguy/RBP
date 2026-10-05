# Task 002C-R2P — portable guarded-probe package

## Purpose

Build and test the **offline package** that will later run Task 002C-R2 on a
collaborator's 64-GiB Apple-Silicon Mac.  This is packaging and launcher work,
not an execution authorization.  The package may run exactly the three R2
resource probes (500, 251, and 101 nt) and must be structurally unable to
perform R3 full edge discovery, component construction, reassignment, model
training, or any audit.

The scientific question remains unchanged: can the fixed direct-search
relation be measured safely before we authorize its all-vs-all use to create
components v2?

## Inputs and trust boundary

The future bundle contains only the already accepted decoded 500/251/101-nt
FASTA files, their tracked decode manifest, the R2 source code and its exact
native-arm64 runtime.  It must **not** contain the raw CSV, labels, previous
partition assignments, component results, reference files, or model files.

Before it opens a FASTA or launches MMseqs2, the launcher must verify its own
immutable inventory and then verify:

- macOS on native Apple Silicon (no Rosetta);
- the exact bundled Python/runtime inventory and the native arm64 MMseqs2
  version and SHA-256 already frozen for portable execution;
- the accepted decode manifest and all three FASTA path/size/SHA-256 entries;
- at least 64 GiB installed RAM, at least 24 GiB currently available RAM, and
  at least 100 GiB free disk space; and
- a new, absent output root.

The bundle must be self-contained and offline.  It may remove a quarantine
attribute only from its own private runtime directory.  It must not create,
alter, or inspect paths outside the supplied bundle/output location.

## Fixed operational boundary

The single launcher has exactly these stages, in this order:

1. `probe_500`
2. `probe_251`
3. `probe_101`

They use the accepted R2 implementation unchanged: one deterministic,
label-blind set of 10,000 query IDs per width against the full 361,180-record
target FASTA; frozen direct-search flags; at most four threads; live RAM,
disk, swap, pressure, time, result-density, cap, and projection gates.

Every stop is final for this package.  No automatic retry, flag change,
partial continuation, or conditional R3 call is allowed.  A successful R2
run returns resource evidence only and still stops for a new review.

## Return contract

The launcher must always try to create exactly one drag-and-drop return ZIP,
named `RBP_002C_R2_RETURN_<UTC timestamp>_<host>.zip`, plus its unpacked
return directory.  It must include a manifest, inventory, checksums,
commands, logs, host/preflight snapshots, sanitized stage summaries, selected
query IDs/digest, and the relative path/size/SHA-256 of each excluded raw
artifact.

It must never include raw FASTA sequence, labels, MMseqs2 databases, raw TSV
results, or any model/partition artifact.  It records either `SUCCESS` (all
three R2 probes passed) or `STOPPED` with the first failure and its traceback.

## This checkpoint: implementation and synthetic verification only

Implement the package builder/launcher and test them solely with generated
tiny fixtures and a fake executable.  In particular, do **not** copy a real
runtime, build a real archive, open ignored decoded FASTAs, launch real
MMseqs2, access the network, or run a probe.

The later package-build checkpoint will operate on the accepted real inputs,
verify the finished archive independently, and stop before the collaborator
execution.  The collaborator execution requires its own explicit handoff.

## Acceptance

Accept this checkpoint only if synthetic tests prove:

- inventory tampering, host/runtime/FASTA mismatch, missing resource evidence,
  an existing output root, and a forbidden stage all fail before MMseqs2;
- the package invokes only the fixed R2 stage enum and produces no direct-edge
  or components-v2 artifact;
- both successful and stopped paths create sanitized, checksum-complete return
  packages without forbidden contents; and
- a failed probe does not retry or start a later width.
