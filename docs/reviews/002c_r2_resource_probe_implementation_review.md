# Task 002C-R2 guarded probe implementation — review

## Verdict

**Approve with bounded corrections.**

Commit `8de909b` has the right R2 boundary and structure: fixed width stages,
label-blind query selection, complete-target enforcement, frozen direct-search
argv, injectable resource monitoring, atomic selection records, and a
sanitized return schema. The planning reviewer independently reran the stated
focused suite: **78 tests passed**.

The following corrections are required before acceptance because they affect
whether a successful probe gives a trustworthy, fail-closed R3 decision. They
do not change any scientific flag, threshold, width, or task boundary.

## F1 — bound direct-result parsing memory

`analyze_probe_result()` currently stores a Python `set` containing every
`(query, target)` pair to detect duplicates. A real 10,000-query/full-target
probe can produce millions of rows, making memory grow with the output that R2
is supposed to measure.

Replace it with bounded streaming validation. Require the raw `createtsv`
output to be grouped by query; reject a query that reappears after its group
ends. Within the current query group only, retain seen target IDs to detect a
duplicate pair, then release that set before the next query. The selection has
only 10,000 IDs and a single query can report at most the 361,180 target IDs,
so memory is explicitly bounded. If real MMseqs output does not satisfy this
grouping contract, stop for review rather than silently buffering the complete
result.

Add tests for a duplicate within a group, a query reappearing later, and a
large multi-query synthetic stream proving no all-pair set is retained.

## F2 — stop immediately on a warning

`run_probe_stage()` currently executes `createdb(query)`, `createdb(target)`,
`search`, and `createtsv` before inspecting the target/search warning lists.
Therefore a target-database or search warning can still launch a later step.

Check the applicable warning result immediately after each guarded command,
before launching the next one. Test that a target-database warning prevents
search and that a search warning prevents `createtsv`.

Use precise warning/error patterns. A bare `split` match is too broad and may
match benign text or a filesystem path. Detect warning lines and the explicit
multi-part, override, OOM/cannot-fit, and truncation conditions relevant to the
task.

## F3 — measure the complete width stage's disk and retained upper bound

The current transient calculation uses only the search command's free-disk
drop. The R2 contract requires `probe_start_free_disk - probe_min_free_disk`
over the entire width, including both database creations, search, TSV
rendering, and temporary files. Record that whole-stage start/minimum and use
it for the 20-GiB conservative transient gate.

The current `retained_bytes` comes only from `result*` files. R2 cannot yet
know the final normalized-edge size, but it can safely project a retained
upper bound of `max(raw result-database bytes, rendered TSV bytes)`. Record
both raw quantities and use this upper bound for the 25-GiB gate. Label it as
an upper-bound estimate, not as actual R3 retained output.

Add threshold tests where database creation or TSV rendering, rather than the
search command alone, creates the worst free-disk minimum, and where a TSV is
larger than the result database.

## F4 — include a peak measurement for short-lived children

The live process-tree sampler does not run when a child exits within the first
poll interval, leaving `peak_rss_kib` at zero. That could make a fast but
memory-intensive subprocess appear free and incorrectly pass the projected
48-GiB gate.

After each child is reaped, include a best-available child RSS measurement
(for example the existing `peak_rss_kib_of_children()` helper), combine it
conservatively with the live sampler, and record the source/limitation. A
cumulative-child measurement is acceptable here because it can only make the
stage estimate more conservative. An unavailable post-run measurement must
fail closed. Add a regression for a child completing before the first poll.

## F5 — validate the canonical universe and FASTA header IDs

R2 converts the supplied universe directly to a `frozenset`, allowing an
empty, tab-containing, or newline-containing ID to bypass a canonical-ID
contract. `read_fasta_strict()` can likewise accept an empty header if it
appears in the supplied universe.

Add an R2-local canonical-universe/header validator and reject invalid IDs
before selection or FASTA processing. Do not import a direct-edge writer or
broaden R2's boundary. Add tests for invalid universe IDs and an empty FASTA
header.

## F6 — report block byte density, not only row density

The task requires hit rows **and hit bytes** for each of the ten deterministic
blocks. The implementation currently reports only a list of row densities.
Record, per block, query count, hit rows, raw UTF-8 TSV bytes, rows/query, and
bytes/query. Apply the 1.5 heterogeneity gate to both per-query row density
and per-query byte density; either excess stops the probe. Keep all data as
aggregate metrics—never retain raw result rows/edges.

## Boundary and return

Make only these narrow source/test/doc changes. Keep tests synthetic, do not
run real MMseqs2 or read real artifacts, and do not implement the portable
package preflight in this correction. The later package review must still bind
the accepted arm64 binary, decode manifest, and three FASTA hashes before real
execution.

Return the correction commit, changed files, focused test results, synthetic
boundary proof, `git diff --check`, and worktree status. End with:

**Task 002C-R2 real package execution and Task 002C-R3 full edge discovery
were not started.**
