# Reconciliation — Task 001 second review

## Outcome

The second reviewer returned **approve with required changes**. All twelve
required changes were incorporated into Task 001. Execution remains blocked
only on project-owner approval for tool installation, reference downloads, and
the 30-GiB peak disk allowance.

The reviewer disclosed that they authored the earlier v1–v5 plans. Their review
is therefore useful but not statistically independent; this is recorded rather
than obscured.

## Required changes

| Item | Decision | Reconciliation |
|---|---|---|
| R1 execution host/RAM | Accept | Named the local 16-GiB macOS x86_64 host, prohibited the 3-GiB device VM, limited concurrency, and added a RAM stop. |
| R2 enriched sample | Accept, redesign | Replaced the original quota-first sample with a 5,000-row label-blind representative stratum, quota supplement, then filler. Only the representative stratum drives the headline gate. |
| R3 primary mapper | Accept with corrected rationale | BWA-MEM 0.7.19 is now primary and minimap2 2.31 remains splice-aware. Official minimap2 documentation does not establish the reviewer's claimed ~300-nt limit; BWA was selected because its documented range includes 500 nt and it adds an independent mapping algorithm. |
| R4 independent uniqueness | Accept, strengthen | SeqKit 2.13.0 exact, both-strand substring search is required for every proposed exact-unique call, not merely 500. |
| R5 score-gap units | Accept | Primary secondary-locus criteria now use coverage and identity. MAPQ and 2/5/10% score gaps are diagnostics only and are not compared across tools. |
| R6 block coordinates | Accept | Added a required per-row mapping table with BED12-shaped blocks and full alignment evidence. |
| R7 strand | Accept | Strand is persisted and summarized explicitly. |
| R8 per-protein precision | Accept | The audit is labelled a gross-failure screen; severe alerts are numerically defined and moderate effects are deferred to full mapping. |
| R9 negative control | Accept | Added 100 deterministic dinucleotide-preserving shuffled controls, excluded from scientific rates. |
| R10 input hashes | Accept | Added verified SHA-256 hashes for the audit manifest and protein configuration. |
| R11 both builds poor | Accept | Added a third-reference/provenance review branch before sequence-clustering fallback. |
| R12 disk with BWA | Accept without raising ceiling | Builds are indexed and processed sequentially; reproducible cache indices may be removed after their commands and hashes are captured. Peak new disk remains capped at 30 GiB. |

## Optional improvements

All four were adopted:

- distinct locus counts are reported;
- contiguous versus splice-rescued rates are headline diagnostics;
- the expected exact-match build signature is prespecified;
- exact released versions of minimap2, BWA, and SeqKit are pinned.

## Remaining approval

Before execution, the project owners must approve:

1. installation of BWA 0.7.19, minimap2 2.31, and SeqKit 2.13.0 in an isolated
   project environment;
2. official hg38/GRCh38 and hg19/GRCh37 reference downloads under the matched
   primary-assembly contig policy;
3. peak new disk use up to 30 GiB, with at least 80 GiB remaining;
4. execution on the named local macOS host with at most four mapping/indexing
   threads.
