# Task 002B real sequence grouping — second-review request

## Requested verdict

Review `docs/tasks/002b_real_sequence_grouping.md` as a plan only. Return one
of: **approve**, **approve with bounded corrections**, or **reject**, with
specific reasons. Do not implement code, open the real CSV, run MMseqs2, or
begin any 002B checkpoint.

## Context

Task 001 coordinate recovery was closed after full-reference indexing exceeded
the local machine's memory. Task 002 is the accepted fallback: construct one
label-blind sequence-similarity component universe before assigning a locked
70/15/15 split. Task 002A is accepted at commit `ec08a71`; its real pinned
MMseqs2 fixtures verify the exact identity, coverage, strand, and result-cap
semantics.

Task 002B must now operate on the real 361,180-row dataset without allowing a
long or failed computation to corrupt evidence or silently weaken the
scientific rule. The proposed plan therefore separates orchestration, decode,
resource probes, each full width, and final union/report.

## Questions for the reviewer

1. Do the checkpoint boundaries adequately prevent accidental progression
   from implementation to real data, from one expensive width to the next,
   or from components to partition assignment?
2. Is the deterministic 10,000-ID, label-blind probe a useful and scientifically
   neutral resource gate? Is the proposed 10-GiB probe peak/10-GiB available-
   memory launch gate appropriate on a 16-GiB host?
3. Are the 50-GiB combined artifact ceiling, 80-GiB free-space floor, four
   threads, 8-GiB split-memory limit, sequential widths, and 12-hour per-job
   timeout reasonable?
4. Does retaining `--max-seqs 361180` correctly favor scientific completeness,
   with resource failure treated as a stop rather than permission to lower it?
5. Are immutable generation records, exact upstream digests, member and
   representative reconciliation, and candidate-directory disk monitoring
   sufficient for restart safety?
6. Is the proposed deterministic component artifact sufficient to hand off to
   002C without retaining raw MMseqs2 internal databases indefinitely?
7. Are the 5%/20% giant-component gates and proposed aggregate
   GC/entropy/homopolymer/repeat diagnostics sufficient to distinguish a real
   biological similarity family from a low-complexity/repeat-driven collapse?
8. Is any requested evidence using labels, predictions, coordinates, or other
   information that would violate label-blind grouping?
9. What is genuinely blocking before 002B-1, and what should be deferred so we
   avoid repeating Task 001's correction loop?

## Scope discipline

Please prioritize scientific correctness, resource safety, and recoverability.
Do not request a second clustering package, coordinate retry, partition
optimizer, baseline model, training code, or cosmetic framework work. Any
suggested correction should identify the exact failure it prevents and the
earliest checkpoint that needs it.
