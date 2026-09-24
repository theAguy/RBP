# Reconciliation of Claude's Task 001B B3 planning review

## Outcome

Claude returned **approve with required changes**. The planning reviewer
accepts all six blockers and the B3B split recommendation. The reconciled plan
is `docs/tasks/001b_b3_hg38_preparation.md`.

No B3 execution is authorized by this reconciliation. B3A is a tiny-fixture
code/test correction only. B3B remains blocked until B3A is implemented and
accepted.

## Required findings

| Finding | Decision | Reconciliation |
|---|---|---|
| Remote-basename mismatch | Accept | Use exact frozen URL basenames for local files and checksum lookup; test a real NCBI-shaped `GCF_...` mismatch from the assembly label. |
| Malformed/duplicate checksum entries | Accept | Structured parser evidence reports malformed, duplicate, and conflicting entries; `stage_download` accumulates them as hard violations. |
| Missing guarded probe stage | Accept | Add a build-scoped, restart-safe, generation-selected probe that is distinct from B4 align/exact/report state. |
| Missing contig lengths | Accept | Persist validated `contig_lengths`, total-base agreement, and deterministic largest-contig selection. |
| Probe/shared 4-GiB budget gap | Accept | Retained probe tool outputs receive a 1-GiB live subcap and seed the same 4-GiB `BuildOutputBudget`, leaving at most 3 GiB for B4. |
| Probe retention undefined | Accept | Retain selected probe outputs/logs through B4 review; count them in both ledgers; authorize no B3 deletion. |

## Disk-budget interpretation

No new allowance is added to the frozen 30-GiB table. Probe candidate work
uses at most the existing 1-GiB environment/log margin; retained probe outputs
use at most 1 GiB carved from the existing 4-GiB build-output allowance. The
whole-run pre-probe check conservatively reserves 2 GiB. Candidate pattern,
contig, and smoke-query inputs are reproducibly hashed and discarded before
the immutable output generation is selected; only tool outputs/logs and
validation/resource evidence are retained.

## Accepted non-blocking improvements

- Fetch and validate the small checksum listing before the large FASTA.
- Do not reuse the mutable `_prepare_mapping_reads` helper for probe patterns.
- Stream the largest contig rather than materializing it in memory.
- Accept CRLF input safely.
- Generalize Git-commit provenance rather than coupling probe code to the
  derivation module.

## Execution gates

1. **B3A:** implement/test operational readiness with tiny fixtures only.
2. **B3B-1:** after B3A acceptance, download and derive hg38, then stop for
   independent source/reference-manifest review.
3. **B3B-2:** only after B3B-1 acceptance, build indices and run the guarded
   probe, then stop for B3 acceptance.
4. **B4:** remains unauthorized until the complete B3 gate passes.

The proposed wall-time/output/memory formulas are accepted as operational
gates subject to review of the real probe evidence: 1.5x length-scaled wall
projection below 4.5 hours, 2x length-scaled output projection within the
1-GiB probe share, and peak RSS plus 2 GiB fitting physical and measured
available/reclaimable memory.

## Scientific-policy boundary

All accepted changes are operational. Source values, contig inclusion policy,
sampling, mapper parameters, classification thresholds, and resource ceilings
remain frozen. Any pressure to change one stops the task for project-owner
review.
