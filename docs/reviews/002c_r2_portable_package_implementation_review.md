# Task 002C-R2P portable-package implementation review

## Verdict

**Approve with three bounded delivery corrections.**

Commit `f01c206` has the right core design: immutable inventory verification
precedes FASTA access; host/runtime and resource checks fail closed; execution
can call only the three fixed R2 probes; and the return path excludes raw
sequence and MMseqs2 artifacts.  The focused review suite passes locally:

```text
105 tests passed
```

No real data, runtime, package, or MMseqs2 execution was used in this review.

## P1 — make the bundle a shareable archive

The builder currently creates only a directory.  The intended deliverable for
the collaborator is one folder **and** a hash-verified `.tar.gz` archive.  Add
an explicit `--archive` option (or equivalent fixed build action) that creates
`<bundle>.tar.gz` only after the immutable input manifest is complete, writes
`<bundle>.tar.gz.sha256`, and refuses an existing archive.  Cover archive
content/checksum verification with a synthetic test.

Include `PROMPT_FOR_CLAUDE_OR_CODEX.txt` beside `RUNBOOK.md`.  It must tell a
collaborator's AI to run only `RUN_002C_R2_PROBE.command`, return only the R2
return ZIP, and never authorize or begin R3.  This is an operational aid, not
an additional executable path.

## P2 — a sanitation fallback is a stopped run

If `assert_return_clean()` detects raw sequence-like data, `package_return()`
removes the full return and writes a minimal one.  It currently preserves the
prior `SUCCESS` status and makes `execute()` return exit code zero.  That is
misleading: the evidence cannot safely be returned, so the checkpoint cannot
be accepted.

On this fallback, force the effective status to `STOPPED`, record the guard
failure, and return a non-zero execution code.  Add a regression that plants
sequence-like log text after an otherwise successful fake probe and asserts
`STOPPED`, `minimal_return: true`, and non-zero exit status.

## P3 — ship an R2-only source subset

The builder currently copies all of `src/rbpbench`, including unrelated
direct-edge/components-v2, assignment, audit, and R3-capable modules.  The
launcher does not import them, but the package should be structurally narrow
as promised—not merely rely on its default entry point.

Copy a manifest-defined, explicit source subset sufficient for the launcher
and `resource_probe_r2` dependencies.  It must include package initializers,
the R2 module, command/guard helpers, and required generic
coordinates/data helpers; it must exclude `direct_edges.py`,
`components_v2.py`, `runner_002c.py`, audit/assignment modules, and the old
portable 002C-3 launcher.  Add a synthetic bundle assertion for both the
required subset and excluded modules.  No scientific flags or R2 runtime logic
may change.

## Correction boundary

Make only P1–P3 source/test/documentation changes.  Do not build a real
bundle, read real decoded FASTAs or other ignored artifacts, run real MMseqs2,
or start R3.  A later, separately reviewed checkpoint will create the actual
folder/archive from accepted inputs.
