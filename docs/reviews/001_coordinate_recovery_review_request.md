# Review request — Task 001 coordinate-recovery feasibility

**Status:** completed. The reviewer returned `approve with required changes`.
The planning response is recorded in
[`001_coordinate_recovery_reconciliation.md`](001_coordinate_recovery_reconciliation.md).
This request is retained unchanged below as review provenance.

Please review `docs/tasks/001_coordinate_recovery_feasibility.md` as a
scientific and implementation plan. Do not execute it yet.

## Context

We have 361,180 one-hot-encoded 500-nt human RNA windows and sparse labels for
122 RBPs. The original row-level split is vulnerable to leakage because
overlapping windows from the same locus may cross folds. Coordinates are not
model inputs; we want them to group loci before model comparison.

The proposed next task maps a deterministic, label-covered 10,000-row sample to
both hg38 and hg19 using contiguous and splice-aware minimap2 modes. It reports
unique, ambiguous, low-quality, and unmapped sequences and audits retention by
protein/class before authorizing full mapping.

Local preflight found no reference FASTA and no installed aligner. `samtools
1.11`, Conda-compatible environment managers, and sufficient disk are present.

## Questions for the second reviewer

1. Is the deterministic sampling scheme large and representative enough for a
   feasibility decision while guaranteeing all 122 protein/class pairs?
2. Is minimap2 with `sr` plus `splice:sr` an appropriate two-stage diagnostic
   for exact 500-nt sequences? If not, name a specific replacement and explain
   what failure it prevents.
3. Should the references be UCSC whole-genome FASTAs or matched
   primary-assembly-only FASTAs? Please state the contig policy you recommend.
4. Are 98% coverage, 99% identity, MAPQ 30, and a 5% second-best score gap a
   defensible provisional definition of a usable unique mapping?
5. Is the handling of split/spliced alignments sufficient for constructing
   future locus-overlap components?
6. Are the build-choice rule and the positive/negative retention audit protected
   from outcome-driven selection?
7. Are any required outputs, tests, failure modes, or provenance records
   missing?
8. Does the proposed 30 GiB new-disk ceiling and 80 GiB remaining-space floor
   look reasonable for this machine?

## Requested response format

Please return:

- **Decision:** `approve`, `approve with required changes`, or `block`.
- **Required changes:** numbered, concrete changes needed before execution.
- **Optional improvements:** useful changes that are not gate blockers.
- **Answers:** direct answers to questions 1–8.
- **Scope check:** confirm that you did not expand this into full mapping, fold
  construction, or model training.

If recommending a different mapper, reference, or threshold, include the exact
proposed configuration and the evidence or reasoning behind it. Do not modify
the task or begin implementation; the planning reviewer will reconcile the
feedback into the authoritative ticket.
