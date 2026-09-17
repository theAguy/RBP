# Executor handoff — Task 001A

Claude, act as the implementation executor for **Task 001A only**. Do not
re-plan the parent study, download human references, or start real mapping.

## Read before editing

Read these files in order:

1. `docs/tasks/001a_coordinate_pipeline_implementation.md`
2. `docs/tasks/001_coordinate_recovery_feasibility.md`
3. `docs/reviews/001_coordinate_recovery_reconciliation.md`
4. `docs/DATA.md`
5. `docs/DECISIONS.md`
6. `CONTRIBUTING.md`

The parent task has completed second review and received project-owner resource
approval. Its scientific definitions are locked. If two instructions conflict,
stop and report the exact conflict rather than choosing silently.

## Environment boundary

Your Linux execution environment has about 3 GiB RAM and 8.5 GiB free disk. It
is not the approved host for human-genome indexing or mapping. You may implement
code and run tiny fixture tests there. Task 001B will later run on the local
16-GiB macOS x86_64 host after the planning reviewer accepts 001A.

Do not install tools globally. Do not upload the dataset or sequences to any
service. Do not use the real 724-MB CSV in Task 001A.

## Git boundary

Before editing, verify that `main` has the reviewed baseline commit and that
`origin` points to `https://github.com/theAguy/RBP.git`. Then create and work
only on `issue-001a-coordinate-pipeline`.

If either condition is absent when you receive this handoff, stop and report
the exact Git discrepancy. Do not replace the reviewed baseline, invent another
remote, or commit directly to `main`.

## Execution instructions

- Implement exactly the required deliverables and tests in Task 001A.
- Preserve existing files and unrelated work.
- Keep generated or large files out of Git.
- Use deterministic algorithms and explicit schemas; never rely on row-order
  arrays without canonical sample IDs.
- Do not change scientific constants or expand dependency scope without written
  approval.
- If external mapping binaries are unavailable, unit-test command construction
  and parsers with fixtures and make the integration test skip explicitly.
- Run all existing and new tests plus `git diff --check`.
- Commit the bounded implementation on the feature branch, but do not merge or
  push directly to `main`.

Return the seven-item handoff requested at the end of Task 001A. End with the
exact sentence: `Task 001B was not started.`
