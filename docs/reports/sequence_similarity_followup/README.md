# Follow-up audit of sequence similarity

This audit was performed after the plausibility of the sequence-similarity
finding was questioned. It independently re-read the accepted Task 002C
normalized edge sets and all three decoded FASTAs. It did not rerun MMseqs2.

## Main conclusion

The large edge counts are real, but they are not caused by duplicated complete
sequences. They are overwhelmingly caused by different, shifted windows that
overlap exactly over the minimum length allowed by the frozen rule.

| Width | Direct edges | Exact full duplicates | Exact forward shifted overlap | Exact RC relationships | Needs MMseqs mismatch/gap detail |
|---:|---:|---:|---:|---:|---:|
| 500 | 943,435 | 0 | 923,037 (97.84%) | 0 | 20,398 (2.16%) |
| 251 | 217,571 | 0 | 212,841 (97.83%) | 0 | 4,730 (2.17%) |
| 101 | 102,759 | 0 | 97,808 (95.18%) | 19 (0.018%; 2 exact full RC and 17 shifted RC) | 4,932 (4.80%) |

“Exact forward shifted overlap” is a conservative category: the two strings
are not equal, but one window's prefix is exactly equal to a suffix of the
other for at least the required coverage. The remaining category is not a
rejection. Those pairs were accepted by MMseqs2 and need its raw alignment
columns to separate mismatches, gaps and strand.

## Why width 500 produced many more relationships

The frozen rules require at least 90% identity. Coverage is 80% for width 500
and 95% for widths 251 and 101. For an exact shifted overlap, this means:

- width 500: at least 400 bases, so shifts of 1–100 bases can pass;
- width 251: at least 239 bases, so shifts of 1–12 bases can pass;
- width 101: at least 96 bases, so shifts of 1–5 bases can pass.

The observed exact-shift distribution has exactly these ranges. For shifts
1–12, the counts are nearly identical between the 500- and 251-base data. For
shifts 1–5, they are nearly identical in all three data sets. This is strong
evidence that the same underlying windows are being cropped at different
widths, not that MMseqs2 invented unrelated matches.

Of the 251-base edges, 99.44% are also 500-base edges. Of the 101-base edges,
96.88% are also 500-base edges.

## Exact uniqueness and reverse complements

All 361,180 complete sequences are unique at widths 500, 251 and 101. There
are no exact forward duplicate pairs at any width.

There are only two exact full reverse-complement pairs, both at width 101:

- `row_85204` / `row_123985`
- `row_248981` / `row_263506`

At width 101, another 17 edges have an exact shifted reverse-complement
overlap. Thus only 19 of 102,759 direct 101-base edges are proven here to be
exact reverse-complement relationships. No exact reverse-complement edge was
found at widths 500 or 251.

This does not yet give the total number of reverse-strand MMseqs2 alignments.
The sanitized return contains normalized endpoints but deliberately omits the
raw per-edge alignment columns. Some of the 20,398 / 4,730 / 4,932 remaining
pairs could be reverse-strand alignments with mismatches or gaps.

## Component-size distribution

The graph contains 169,699 connected components over 361,180 rows:

| Component size | Components | Rows | Fraction of all rows |
|---:|---:|---:|---:|
| 1 | 118,943 | 118,943 | 32.93% |
| 2 | 23,723 | 47,446 | 13.14% |
| 3–5 | 17,580 | 63,875 | 17.69% |
| 6–10 | 5,816 | 43,241 | 11.97% |
| 11–25 | 2,798 | 43,447 | 12.03% |
| 26–100 | 779 | 32,505 | 9.00% |
| >100 | 60 | 11,723 | 3.25% |

The largest component contains 708 rows (0.196% of the data). The largest 20
components together contain 1.81% of the data. Therefore the graph is not one
giant family; it consists mainly of singletons and many small families.

## Concrete three-row example

`row_0`, `row_142347` and `row_204689` form one component.

At width 500:

- `row_0` and `row_142347` share an exact 499-base overlap (shift 1);
- `row_142347` and `row_204689` share an exact 494-base overlap (shift 6);
- `row_0` and `row_204689` share an exact 493-base overlap (shift 7).

They are three different 500-base strings, but almost all of their content is
the same underlying stretch at slightly different starting positions. The
same shifts appear after cropping to 251 and 101 bases. At 101 bases, only the
shift-1 pair reaches the 95% coverage threshold, which explains why that
width's component graph is sparser.

The complete sequences for this example and the exact reverse-complement
pairs are recorded in `sequence_similarity_audit.json` or the source FASTAs.

## What is proven and what remains

Proven from the accepted local evidence:

- the direct-edge counts exclude self-hits and collapse query/target symmetry;
- all edge endpoints belong to the canonical 361,180-row universe;
- complete sequences are unique;
- at least 95–98% of edges are exact shifted overlaps;
- exact reverse complements are extremely rare;
- component sizes are bounded and there is no giant component.

Still needed for a complete per-edge similarity histogram:

- retrieve the three retained raw MMseqs2 TSVs, or rerun output conversion
  with an explicit schema;
- report identity, aligned coverage, gap/indel count and strand for every edge;
- inspect the remaining 2–5% separately, including their low-complexity or
  repetitive-sequence content.

The machine-readable results were produced by
`scripts/analyze_sequence_similarity_followup.py` and are in
`sequence_similarity_audit.json`.
