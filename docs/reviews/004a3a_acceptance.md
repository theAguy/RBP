# Task 004A-3A acceptance

**Verdict:** Approve.

Task 004A-3A is accepted and closed. The accepted implementation is the
combined result of:

- `d13179a` — initial synthetic GPU-smoke tooling;
- `e658161` — bounded E1–E6 correction; and
- `89b34e5` — bounded F1–F2 correction.

## Accepted corrections

E1–E6 establish complete data-free discovery evidence, authenticated
full-validation metric counts and reviewed subset-building code, pre-cache GPU
identity checks, a complete hash-bound portable bundle, deterministic
cross-process checkpoint paths, and a discovery-derived reviewed Slurm limit.

F1 moves discovery validation to a standard-library-only module, packages the
discovery return before validation, preserves unusable partition-limit
evidence and keeps the discovery Python compatible with Python 3.6. F2
canonicalizes the narrow representational differences between PyTorch and
`nvidia-smi` GPU UUIDs while retaining fail-closed validation.

## Verification accepted

The final focused suite was reported twice with four threads:

- 95 passed, 62 subtests passed, no skips, 71.36 seconds;
- 95 passed, 62 subtests passed, no skips, 71.60 seconds.

Both runs contained only the two previously documented non-failing PyTorch
warnings. Four targeted F1/F2 regressions were copied onto exact parent
`e658161` and failed there: the standard-library discovery module and MaxTime
parser were absent, archive creation followed the PyTorch-loading validator,
and UUID comparison was literal. The same regressions pass on `89b34e5`.

## Authorization boundary

This record accepts and closes 004A-3A only. It does **not** authorize or
start 004A-3B discovery, 004A-3C environment/subset freezing, 004A-3D GPU
execution, or 004A-4 training. Each remains separately reviewed and explicitly
owner-authorized.
