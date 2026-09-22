# Review request — Task 001B coordinate-feasibility execution

## Role

Claude, act as the second reviewer, not the executor. Review
`docs/tasks/001b_coordinate_feasibility_execution.md` against the accepted
parent task and the merged Task 001A implementation. Do not edit files, install
software, download references, create indexes, read the real CSV, or run real
mapping during this review.

## Read in order

1. `docs/tasks/001b_coordinate_feasibility_execution.md`
2. `docs/tasks/001_coordinate_recovery_feasibility.md`
3. `docs/reviews/001_coordinate_recovery_reconciliation.md`
4. `docs/COORDINATES.md`
5. `docs/DECISIONS.md`
6. `configs/coordinate_feasibility.toml`
7. `src/rbpbench/coordinates/commands.py`
8. `src/rbpbench/coordinates/runner.py`
9. `src/rbpbench/coordinates/manifest.py`
10. `CONTRIBUTING.md`

Task 001A was accepted and merged into `main` as `ad36864`; PR #1 contains the
review history. The 001B branch is for the next bounded task. Scientific
thresholds, mapper roles, sampling, and contig policy remain frozen.

## Specific questions

1. Does the proposed NCBI RefSeq source/filter procedure implement the parent
   task's matched policy for chromosomes, mitochondrial sequence,
   unlocalized scaffolds, and unplaced scaffolds while excluding alternates,
   patches, decoys, and separate HLA contigs?
2. Are the source accession/version choices sufficiently pinned and auditable,
   including the full-source MD5 plus locally computed SHA-256 and the derived
   FASTA/contig manifest?
3. Does the B1 readiness work close the real execution gaps left deliberately
   outside 001A, especially `bwa index`, minimap2 `.mmi` preparation/use,
   index-to-reference binding, provenance, restart invalidation, and safe
   cleanup?
4. Is the proposed minimap2 index interface compatible with the frozen
   `splice:sr` mapping command, or must the plan constrain additional index
   parameters to prevent preset/index incompatibility?
5. Is the SeqKit 2.13.0 real-binary smoke sufficient to verify BED6 semantics,
   both-strand search in one invocation, and the absence of double counting?
6. Are the B0–B7 gates small enough to prevent an unattended multi-hour run
   and strong enough to catch stale or mismatched state before proceeding?
7. Can any restart path attach a new reference, manifest, or mapper index to an
   older mapping/report without rerunning the required upstream stages?
8. Is cleanup narrowly scoped and ordered so neither source/derived FASTAs nor
   irreplaceable mapping outputs can be deleted accidentally?
9. Are the Git/artifact boundaries sufficient for a second collaborator to
   reproduce the work without committing human references, decoded sequences,
   or raw alignment files?
10. Identify any unresolved scientific, provenance, resource, or execution
    blocker. Distinguish mandatory corrections from optional improvements.

## Requested response format

- Verdict: `approve`, `approve with required changes`, or `do not approve`.
- Required changes, numbered and tied to exact task sections.
- Optional improvements, clearly separated.
- Explicit confirmation that no Task 001B execution was performed during the
  review.

Do not prepare an executor handoff. The planning reviewer will reconcile your
review first.
