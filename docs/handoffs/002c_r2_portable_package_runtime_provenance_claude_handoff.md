# Task 002C-R2P Claude executor handoff — final runtime-provenance correction

Implement only R4 in
`docs/reviews/002c_r2_portable_package_runtime_provenance_correction.md`.
Work on `issue-002c-partition-assignment`; before editing verify the expected
origin, clean tracked worktree, and that `96eb48f` is an ancestor of `HEAD`.
Commit locally, without push or merge.

Read the R2P task, initial handoff, P1–P3 review, this review, and the
builder/launcher/tests before editing.

Use temporary generated runtime trees, manifests, locks, and fake tools only.
Do not open/list/hash/copy any real runtime, FASTA, artifact, prior bundle,
CSV, reference, or model input.  Do not build a real bundle, use the network,
run real MMseqs2, or start R3.

Require the builder to receive and verify an explicit expected runtime manifest
and its pinned hash **before** copying the runtime.  It must check all files
and permitted symlinks and reject missing, extra, escaping, or mismatching
entries.  Copy the verified manifest and the small environment lock into the
bundle; bind their hashes in the package config/summary and surface the
expected-runtime-manifest hash in the return status.  Retain the current fixed
MMseqs2 hash/version check as a second independent gate.

Add the four negative synthetic cases and the positive archive/inventory case
specified in the review.  Run R2/package-focused synthetic tests only.  Return
the commit, changed files, test results, synthetic-only proof, hygiene checks,
and remaining real-build prerequisites.  End exactly with:

**Task 002C-R2 real package build, collaborator execution, and Task 002C-R3
full edge discovery were not started.**
