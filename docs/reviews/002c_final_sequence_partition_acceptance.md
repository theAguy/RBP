# Task 002C final components-v2 partition acceptance

**Verdict:** accepted and closed

**Accepted production return:**
`RBP_002C_R3R5_RETURN_001_SUCCESS_20261026T031324Z_newton8.zip`

**Return SHA-256:**
`ee781d1266b0b589dea7b05857eadd2a60fc311bc0a60d4d6c5b69854f210091`

**Execution source commit:**
`185afbc38a5116632761239e5730974c1bb13836`

**Tracked closure manifest:** `manifests/sequence_partitions_002c_v2.json`

## Verdict

Task 002C is complete. The final components-v2 membership is accepted as the
locked train/validation/test split for all later baselines and models. The
historical former-teammate fold and the intermediate v1 assignment remain
diagnostic evidence only and must not be used for model comparison.

This acceptance changes no similarity threshold, component, partition, or
model result. It records the already completed, reviewed production execution.

## Evidence integrity

- The return sidecar and ZIP checksum were verified.
- `verify_return_series` found exactly one return, status `SUCCESS`, terminal
  and non-resumable.
- The return inventory and internal checksums passed.
- MMseqs2 was version 18.8cc5c, Bioconda build `hd6d6fdc_0`, binary SHA-256
  `d6d1bf1b50c095eb0cb66f685a7fb1d9b8b69497e1e88416fd48f28e313cc773`.
- The run used four CPUs and a 96-GiB Slurm allocation on Darwin/Newton host
  `newton8`; no GPU or model/baseline execution was involved.

## Components-v2 result

| Measure | Result |
|---|---:|
| Canonical rows | 361,180 |
| Components | 169,699 |
| Singleton components | 118,943 |
| Largest component | 708 rows (0.1960%) |
| Largest 20 components | 1.8085% of rows |
| 500-nt direct edges | 943,435 |
| 251-nt direct edges | 217,571 |
| 101-nt direct edges | 102,759 |
| v1 components merged by v2 | 6,406 |
| v2 components formed from v1 merges | 2,640 |
| Rows in merged v1 components | 54,610 |
| v1 components split by v2 | 0 |

The 5% single-component and 20% top-20 giant-component gates both passed.
Reordered component construction was identical. An independent breadth-first
search reconstruction reproduced all 169,699 components.

## Assignment result

| Partition | Rows | Fraction | Deviation from target |
|---|---:|---:|---:|
| Train | 246,017 | 68.1148% | -1.8852 percentage points |
| Validation | 57,565 | 15.9380% | +0.9380 percentage points |
| Test | 57,598 | 15.9472% | +0.9472 percentage points |

- No component is split across partitions.
- Primary and reordered-repeat assignments are byte-identical.
- Every protein has at least 30 known positives and 30 known negatives in
  validation and test.
- The observed minima are 97 positives (protein 93) and 80 known negatives
  (protein 53).
- No repair step was needed.
- Final membership SHA-256 is
  `ca527da4f0c0615bcb9d31c6fc705523238e8fb8f4751473ccc2af3ee0aecddb`.

## Balance disclosure

The split passes all hard floors and global row-balance limits, but whole
components constrain per-protein stratification:

- 86/122 proteins have at least one train/validation/test positive-or-negative
  cell more than three percentage points from target;
- 218/732 total cells are flagged;
- 54 proteins and 117 cells are flagged when restricted to validation/test.

These are mandatory disclosures, not failures under the frozen acceptance
contract. Later results must report the actual known-positive/known-negative
counts per protein, flag imbalanced proteins, and use appropriate uncertainty.

## Independent leakage gates

- Independent exact/reverse-complement audit: zero cross-partition groups at
  500, 251, and 101 nt.
- Fresh audit inputs were regenerated from final membership and reconciled by
  ID and sequence hash.
- Fresh MMseqs2 databases passed lookup and convert-to-FASTA round trips.
- Deterministic self-hit/construction-edge positive controls passed.
- All 18 directed searches completed: three widths, three unordered partition
  pairs, and both query/target directions.
- All 18 reported zero qualifying cross-partition hits.
- No audit-discovered edge and no remediation cycle were needed.

The supported statement is “zero detected cross-partition relationship under
the frozen 500/251/101-nt similarity and exact/reverse-complement rules.” It is
not a claim that every possible biological or coordinate relationship has
been excluded.

## Historical result

The former notebook's exact fold 0 is not leakage-safe. Of 72,236 holdout
rows, 45,937 (63.593%) belong to a **v1 component** also represented in
training. This recorded v1-grouping result is a lower bound under the final v2
relation because v2 only merges v1 components and never splits them. The
intermediate v1 assignment is also rejected: its first fresh directed search
(500 nt, train to validation) found 4,792 qualifying pairs among 3,576
distinct rows (1,400 train queries and 2,176 validation targets). The audit
stopped there by design, so the other 17 directed searches were not run and
4,792 is a lower bound rather than a complete v1 total. Components v2 were
built specifically to close that construction/audit mismatch.

## Boundary after closure

Task 002C trained no model and used no prediction to build or accept the split.
Phase 3 baselines may now begin. All future methods must use the same locked
membership and may not tune preprocessing, similarity rules, or split
membership using validation/test performance.
