# Task 003B-2 membership-order correction

The first real pilot attempt stopped before opening the CSV or any FASTA.
The accepted membership is a complete TSV sorted lexicographically by sample
ID (`row_0`, `row_1`, `row_10`, ...), whereas the synthetic membership fixture
was numerically ordered.

The correction makes membership row order explicitly irrelevant:

- parse only canonical `row_<non-negative-integer>` IDs;
- reject duplicates, missing IDs and IDs outside the expected universe;
- verify that every component belongs to exactly one partition;
- reconstruct the in-memory membership in numeric row order before joining the
  sequential CSV.

New regressions cover the real lexicographic pattern and duplicate, missing and
foreign IDs. No threshold, split, label rule, baseline or model setting changed.
No test label or sequence was accessed by the stopped attempt.
