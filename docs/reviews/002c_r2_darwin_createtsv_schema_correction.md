# Task 002C-R2 Darwin `createtsv` schema convergence correction

## Evidence and root cause

Darwin Slurm job 451600 produced a checksum-complete `STOPPED` return. Its
500-nt search and `createtsv` command both exited successfully. The first
rendered row was:

```text
row_113711\trow_113711\t897\t1.00\t4.007E-276\t0\t499\t500\t0\t499\t500\t0\t499\t0\t652
```

The parser rejected it because synthetic tests had modeled `createtsv` as
exactly `query<TAB>target`. The real pinned MMseqs2 18.8cc5c search/alignment
result contains the same endpoint fields followed by alignment evidence. This
is an interface mismatch in our parser, not a failed search, changed relation,
resource failure or corrupt input. The stopped return is bound in
`manifests/sequence_r2_darwin_parser_stop.json`; it is not accepted R2
resource evidence and does not authorize R3.

## Corrected contract

- A raw search row must contain at least two tab-separated fields.
- The first two fields are the non-empty query and target IDs and undergo all
  existing selection/universe/grouping/duplicate/self-hit/cap checks.
- Trailing fields are opaque. Their semantics are not reimplemented or used
  to alter the similarity decision already made by MMseqs2.
- Every raw byte, including all trailing fields, remains in per-query,
  per-block and projected-output measurements.
- The observed column-count histogram and minimum/maximum are returned as
  schema evidence.
- Canonical normalized direct-edge artifacts remain exactly two columns.

The exact real row is a tracked regression fixture. The synthetic end-to-end
probe now emits production-shaped 15-column rows by default. Tests also cover
mixed/opaque trailing fields, exact byte accounting, invalid/missing
endpoints, grouping, duplicates and normalized-artifact strictness.

## Convergence audit and plan revision

The future R3 direct-edge parser contained the same assumption, so it was
corrected before R3 implementation/execution. This is the only plan revision:
raw MMseqs rows and normalized edge artifacts now have explicitly different
schemas. No identity, coverage, strand, sensitivity, result cap, width,
sample, resource gate or checkpoint boundary changed.

The diagnostic classifier, Slurm adapter and package return sanitizer were
also reviewed for dependencies on a two-column row. None interprets the raw
alignment tail. A fresh package may be built only after the focused and broad
synthetic suites pass and the archive inventory is reverified. The new package
still authorizes one R2 attempt only; it can never continue into R3.
