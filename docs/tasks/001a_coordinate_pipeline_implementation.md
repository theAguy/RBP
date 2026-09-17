# Task 001A — Coordinate-pipeline implementation

**Status:** scientifically and operationally approved
**Parent:** `001_coordinate_recovery_feasibility.md`
**Suggested branch:** `issue-001a-coordinate-pipeline`

## Objective

Implement and fixture-test the reusable coordinate-feasibility pipeline. This
subtask ends before human-reference downloads, full-size indexing, or mapping
the 10,000-row feasibility sample.

The parent task and its reconciliation are authoritative. This subtask narrows
execution order; it does not change scientific thresholds.

## Preconditions

- A reviewed initial commit exists on `main`.
- A GitHub remote is configured, or the project owners explicitly authorize
  local-only branch work until the remote is added.
- Work occurs on `issue-001a-coordinate-pipeline`, never directly on `main`.
- The executor has read the parent task, reconciliation, data contract,
  decision log, and contribution rules.

If the Git baseline or remote precondition is absent, report it before editing.
Do not invent a repository URL or commit directly to an unborn `main` branch.

## Required implementation

1. Add a frozen, human-readable configuration containing every seed,
   threshold, tool version, contig policy, resource limit, and output path from
   the parent task.
2. Implement deterministic three-stratum sampling. Stable ranks must use
   SHA-256 over an explicitly encoded field string; Python's process-randomized
   `hash()` is forbidden.
3. Implement strict one-hot decoding and round-trip validation.
4. Implement deterministic dinucleotide-preserving shuffled controls with
   tests that verify preservation, changed sequence, reproducibility, and
   exclusion from scientific denominators.
5. Implement command construction for BWA-MEM and minimap2 without invoking a
   shell through interpolated strings. Log resolved commands and versions.
6. Implement SAM/alignment parsing, collinear-block construction, coverage,
   identity, secondary-locus handling, strand retention, and the mode-specific
   categories defined by the parent task.
7. Implement the SeqKit exact-occurrence result parser and the rule that exact
   uniqueness requires agreement with the primary mapper.
8. Implement report-table generation and reconciliation checks for row,
   category, label-observation, stratum, and control counts.
9. Implement a preflight that reports OS, architecture, physical RAM, free
   disk, CPU count, executable versions, reference hashes, and input hashes.
   It must fail closed when the parent task's host/resource rules are violated.
10. Provide a restart-safe runner with explicit stages. Downloads and mapping
    must require an explicit flag and must not occur merely by importing a
    module or running unit tests.

Prefer small modules with typed records and explicit schemas. Reusable logic
belongs under `src/rbpbench/coordinates/`, not in a notebook.

## Required deliverables

- `configs/coordinate_feasibility.toml`
- a reproducible environment specification or lock input
- `src/rbpbench/coordinates/` implementation modules
- a package CLI or documented runner entry point
- tiny sequence, SAM/alignment, and exact-match fixtures
- focused unit tests for every scientific rule above
- an optional integration smoke test that skips clearly when external binaries
  are unavailable
- reference/artifact manifest schemas or templates
- concise usage documentation identifying the 001A/001B boundary

Exact filenames inside the coordinate package may differ if the executor gives
a clear reason, but the public data contracts and required outputs may not.

## Acceptance checks

- Existing tests still pass.
- New tests cover the representative/quota/filler sampler, all terminal mapping
  categories, secondary-locus ambiguity, split blocks, both strands, exact-match
  disagreement, negative controls, and count reconciliation.
- Repeated fixture runs are byte-identical except for isolated timing fields.
- No test needs the 724-MB CSV, a human reference, or network access.
- No raw sequence, reference, index, SAM/BAM/PAF, or generated artifact is
  staged in Git.
- `git diff --check` passes.
- The executor supplies exact commands and results for tests and the dry run.

## Stop conditions

- A required scientific rule is ambiguous or cannot be represented without
  changing the parent task.
- A proposed dependency conflicts with the pinned tools or Python requirement.
- The implementation would require downloading a human reference or mapping
  real feasibility rows.
- The working tree contains overlapping user changes that cannot be preserved.
- The Git baseline/branch prerequisite is not satisfied.

## Out of scope

- Installing the human-genome mapping environment on Claude's Linux VM.
- Downloading hg38/GRCh38 or hg19/GRCh37.
- Reading or mapping the 10,000-row sample.
- Producing the real feasibility report or choosing a build.
- Constructing folds, baselines, or models.
- Changing thresholds, contig policy, mapper selection, or sampling design.

## Handoff back to the planning reviewer

Return:

1. commit hash and branch;
2. concise file/change summary;
3. exact verification commands and results;
4. dry-run output location;
5. any skipped integration check and why;
6. assumptions or unresolved risks;
7. explicit confirmation that Task 001B was not started.
