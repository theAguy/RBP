# Task 002C-R2P portable package — final runtime-provenance correction

## Verdict

**Approve the P1–P3 corrections, with one final fail-closed runtime binding
requirement before a real bundle is built.**

Commit `96eb48f` now produces and verifies a shareable archive, correctly
turns an unsafe-return fallback into `STOPPED`, and ships only R2-required
project source.  Its focused synthetic suite passes: **112 tests**.

## R4 — bind the complete runtime before copying it

The builder currently validates only `bin/mmseqs` against its known hash, then
creates a new bundle inventory from the entire supplied runtime.  That proves
the copied runtime will not change *after* the bundle is made, but it does not
prove that every other executable/library in the supplied runtime came from
the accepted native-arm64 environment.

For an offline executable handoff, that distinction matters.  A modified
Python library or shared object could be packaged without detection while the
MMseqs2 hash still matches.

Before copying any runtime file, require an explicit expected runtime manifest
and its SHA-256.  Verify every regular file and permitted symlink under the
runtime prefix against it (path, type, byte size/hash or link target), reject
missing/extra/escaping paths, and then record the verified expected-manifest
hash in `R2_PACKAGE_CONFIG.json` and the bundle summary.  Copy the small,
human-readable environment lock into the bundle as well.  At launch,
verification of the immutable bundle inventory plus the recorded expected
runtime-manifest hash must make that provenance visible in the return status.

Use the already accepted arm64 runtime/environment evidence as the source of
truth at the later real build; do not invent or re-pin it during this source
checkpoint.

Add synthetic tests for a modified non-MMseqs runtime file, an extra runtime
file, a changed symlink, and a mismatched expected-manifest hash.  Each must
fail before bundle creation.  Also test that the expected runtime manifest and
environment-lock file appear in the finished archive/inventory.

## Boundary

Make only this R4 source/test/documentation change.  Do not access a real
runtime, decoded FASTAs, ignored artifacts, previous bundle, or real package;
do not run real MMseqs2 or R3.  After R4 is accepted, the next task is the
single real package build and local archive verification.
