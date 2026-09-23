# Correction handoff — Task 001B checkpoint B1

Claude, remain the implementation executor for **B1 only**. Correct every
blocking item in `docs/reviews/001b_b1_planning_review.md`. Do not start B2 or
weaken a requirement merely to retain current tests.

## Git and reading boundary

1. Verify `origin` is `https://github.com/theAguy/RBP.git`.
2. Work only on `issue-001b-coordinate-execution`.
3. Verify review commit `906b8bf` is an ancestor of `HEAD`.
4. Read, in order:
   - `docs/reviews/001b_b1_planning_review.md`;
   - `docs/tasks/001b_coordinate_feasibility_execution.md`;
   - `docs/reviews/001b_coordinate_execution_second_review.md`;
   - `docs/reviews/001b_coordinate_execution_reconciliation.md`;
   - `docs/handoffs/001b_b1_claude_executor_handoff.md`.

Commit the correction round locally on the same branch. Do not push, merge, or
rewrite the accepted planning/review history.

## Scope

Implement every item B1-R1 through B1-R9 plus the additional provenance
correction. In particular, do not substitute prose for executable guarantees:

- reference/manifest/index equality must be checked at every downstream stage;
- index manifests must cryptographically bind source reference, parameters,
  binary, build, and actual paths;
- a failed retry must preserve both accepted records and accepted artifacts;
- disk accounting must be mathematically correct, persistent across separate
  checkpoint invocations, volume-aware, and enforced while outputs grow;
- cleanup must be previewed before deletion, narrowly pinned, evidence/hash
  gated, and durably receipted without deleting its own only provenance;
- frozen input verification and explicit checkpoint stages must be mandatory,
  not documented conventions;
- download/derive must have a guarded, restart-safe fixture-tested CLI path
  ready before B3;
- mapping stderr warnings and failed reconciliation must block acceptance;
- masking claims must not infer hard repeat masking from assembly-gap `N`s.

Use attempt-specific temporary directories/files and atomic promotion for
multi-file outputs. Do not use a broad recursive delete in tests; every cleanup
test must create and constrain its own temporary target.

## Authorization boundary

You may use the already-created isolated `rbpbench-coord-001b` environment and
the installed pinned binaries on tiny synthetic fixtures.

You must not:

- open or hash `dataset_K562_multilabel_with_NEGs.csv`;
- request any NCBI human-reference/checksum URL;
- create a human-genome index or run real mapping;
- alter scientific thresholds, source assemblies, contig policy, sampling, or
  resource ceilings;
- begin the largest-contig SeqKit probe, which remains B3.

## Required regressions and verification

Add tests that demonstrably fail on `dda805f` for every review item, including:

- forced and non-forced reference mismatch at exact-match and report;
- foreign/same-size/split-directory index substitution;
- failed preflight, missing index, subprocess failure, timeout, and partial
  two-tool rerun preserving prior accepted evidence;
- sequential and cross-process disk-ledger math, real output growth stop, and
  retained-file accounting;
- cleanup preview ordering, pinned-root/reference/symlink refusal, missing or
  changed artifact/hash refusal, externalized complete provenance, and receipt;
- omitted execution-source spec and omitted/`all` real-stage selection refusal;
- local fake-transport acquisition/derivation through the actual CLI, including
  checksum-list/size mismatch and atomic failure;
- minimap2 mapping override/multipart warning refusal;
- failed reconciliation remaining retryable;
- masking status with lowercase, uppercase-only, and ambiguous/gap-rich input.

Run:

1. focused new regressions;
2. the complete suite twice with the isolated environment's real binaries on
   `PATH`;
3. `git diff --check` and a staged-file audit proving no generated or large
   artifacts are included.

## Return and stop

Return:

1. correction commit hash and complete changed-file list;
2. itemized B1-R1–R9 resolution;
3. focused regression names/counts;
4. both full-suite results and real-binary smoke count;
5. disk/cleanup safety-test evidence;
6. explicit confirmation that the real CSV and every NCBI human-reference URL
   were untouched;
7. any remaining gap, without continuing into a later checkpoint.

Stop after the local correction commit and end with exactly:

`Task 001B checkpoints B2–B7 were not started.`
