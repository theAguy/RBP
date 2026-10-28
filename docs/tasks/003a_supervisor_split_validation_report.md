# Task 003A — Supervisor-facing split validation report

**Status:** planning review approved with bounded corrections; corrections
reconciled before implementation

**Phase:** 3A, descriptive validation before any baseline or model training

**Execution host:** local project Mac; no Darwin, GPU, MMseqs2, network, or
model execution is required

## Objective

Create a reproducible, scientifically careful set of figures, tables, and a
short supervisor-facing report demonstrating:

1. why the former teammate's row-level split is not leakage-safe;
2. why the intermediate v1 component assignment was rejected;
3. how components v2 corrected the construction/audit mismatch;
4. that the final split passes all frozen component, assignment, and leakage
   gates;
5. which per-protein label imbalances remain and how they constrain later
   interpretation; and
6. whether simple sequence-composition properties differ materially among
   train, validation, and test.

Task 003A is descriptive only. It does not train a baseline or neural model,
inspect predictions, tune a similarity threshold, modify membership, choose a
new split, or reopen Task 002C.

## Scientific boundary

- The components-v2 membership is immutable.
- All figures must be computed from accepted, hash-bound evidence or from a
  fresh deterministic streaming calculation over frozen inputs.
- No model prediction or performance metric may be read.
- No figure may compare quantities with different denominators without
  explicit panel separation and denominator labels.
- “Zero leakage” must be phrased as “zero detected cross-partition
  relationships under the frozen 500/251/101-nt rules.”
- Direct similarity edges, v1 cluster co-membership, connected components,
  exact/reverse-complement groups, and audit hits must remain distinct terms.
- Per-protein imbalance is a disclosure, not a reason to split components or
  silently refreeze membership.
- Large-sample p-values are not used as the primary evidence for sequence-
  composition balance. Report effect sizes and distributional summaries.

## Frozen inputs

Before analysis, the runner must verify:

| Input | Expected evidence |
|---|---|
| Final Task 002C closure manifest | `manifests/sequence_partitions_002c_v2.json`, SHA-256 `b6f6f16fab4e6afc23c16a8dc5b3476130719d579f637cd3cf18002cc7fb7419` |
| Final production return | 65,438,907 bytes, SHA-256 `ee781d1266b0b589dea7b05857eadd2a60fc311bc0a60d4d6c5b69854f210091` |
| Former-split/non-MMseqs diagnostics | `manifests/sequence_non_mmseqs_audits_002c2c.json`, SHA-256 `991a43a61fcdcbfa0aa5734fd8bf7801b029cc34a02ad1d3b400b1c5773d31e8` |
| Rejected v1 assignment manifest | `manifests/sequence_assignment_002c2b.json`, SHA-256 `28aa6687fc335ffcba36eb441ebf2d55ae25565349fc8dfcb48a29be566267f6` |
| Rejected v1 audit return | 433,289 bytes, SHA-256 `d84b7b1125e9bf8ad8e60aba717dbdf119d53c1c5ada7465c3f42a99adb610cf` |
| Rejected v1 component membership | `artifacts/teammate_run_results/20260928T091014Z_87391_arm64/final_component_result/component_membership.tsv.gz`, 14,578,797 bytes, SHA-256 `6000c340056ba8204432e7f4c417fb811f8a3d1a5b1c091dea98461862c7b692` |
| Rejected v1 component report | `artifacts/teammate_run_results/20260928T091014Z_87391_arm64/final_component_result/component_report.json`, 13,036,977 bytes, SHA-256 `b8b5872a4cc5061c562de871ec4500876fcdb72afcab069b21ab2bb44cb3e186` |
| Frozen dataset audit | `manifests/dataset_audit.json`, SHA-256 `e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c` |
| Protein registry | `configs/proteins.tsv`, SHA-256 `374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9` |
| Frozen CSV | 724,425,277 bytes, SHA-256 `982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945` |
| Accepted decoded FASTAs | hashes and sizes from `manifests/sequence_decode_002b2.json` |

The final return must additionally pass its sidecar, internal inventory, and
return-series verification before any figure is promoted. The final membership
inside the return must hash to
`ca527da4f0c0615bcb9d31c6fc705523238e8fb8f4751473ccc2af3ee0aecddb`.
The rejected v1 membership must independently reconstruct exactly 173,465
components before it contributes to a table, figure, or former-fold result.

### Former-fold evidence contract

The accepted former-fold headline values—26,765 crossing components,
45,937/72,236 affected holdout rows (63.593%), and 120,760/288,944 affected
training rows (41.794%)—were computed against the **rejected v1 component
grouping of 173,465 components**, not against the final v2 grouping. The
per-width values are connected-cluster co-membership results and may be direct
or transitive; they are not direct-edge counts.

Because components v2 only merges v1 components and never splits one, the
v1-based former-fold crossing values are lower bounds for the same fold under
the final relation. Task 003A will also recompute the former fold against the
accepted v2 membership after first reproducing the recorded fold-0 train and
holdout index digests. The v1 reproduction and the new v2 recomputation must be
shown as distinct results. Failure to reproduce either recorded fold digest is
a hard stop; the accepted split itself is never changed.

## Implementation design

Implement a reusable, tested module under `src/rbpbench/analysis/` and a thin
script entry point. The analysis must:

- stream the CSV and FASTAs rather than materialize dense 361,180-by-122
  matrices;
- read accepted ZIP members directly or extract only into a transactional
  generation under the output root;
- reconcile all 361,180 canonical IDs exactly once;
- fail on missing, foreign, duplicated, stale, or hash-mismatched evidence;
- write raw computed summaries/tables before plotting;
- make figures only from those versioned summary tables;
- use deterministic ordering, bins, typography, dimensions, and colors;
- write into a new generation and atomically promote only after all checks;
  and
- include a provenance manifest with input hashes, commands, environment
  versions, output inventories, elapsed time, and peak memory when available.

No scientific statistic may be transcribed manually into plotting code. Every
headline value in captions must be drawn from the generated summary tables.

## Required outputs

### A. Machine-readable tables

At minimum:

1. `split_summary.tsv` — row/component counts, fractions, giant-component
   gates, audit counts, v1-based legacy headline values with their grouping
   basis, and the separately labelled Task-003A v2 recomputation.
2. `component_size_distribution.tsv` — component size and number of components
   for v1 and v2.
3. `edge_width_overlap.tsv` — exact overlap categories of normalized row-pair
   edges across 500/251/101 nt; this must not call order-dependent merging
   unions “unique contributions.”
4. `protein_partition_counts.tsv` — one row per protein × partition with known
   positive/negative counts, fractions of each protein/class total, deviation
   in percentage points, and >3-pp flags.
5. `protein_balance_summary.tsv` — per-protein maximum train/validation/test
   deviations and evaluation minima.
6. `sequence_composition_summary.tsv` — per width × partition summaries for GC
   fraction, mononucleotide Shannon entropy, and maximum homopolymer length.
7. `sequence_composition_effects.tsv` — pairwise partition standardized mean
   differences plus a distributional distance statistic; p-values may be
   recorded only as secondary information and must not drive interpretation.
8. `audit_matrix.tsv` — all 18 width/direction combinations with query/target
   counts and violation count; positive-control status is recorded once per
   width because controls were run per width, not per direction.

### B. Main supervisor figures

Produce publication-quality SVG, PDF, and 300-dpi PNG variants with consistent,
colorblind-safe partition colors and explicit captions.

#### Figure 1 — Why the split had to change

A process schematic with three clearly labelled states:

```text
Former row split -> v1 component split -> accepted components-v2 split
```

Show the failure and decision at each transition. Label the recorded 63.593%
affected-holdout result as computed against v1 components, and show the new v2
recomputation separately if it passes its reproduction gates. Do not imply
that either former-fold rate and the rejected-v1 4,792 pair count share a
common denominator.

#### Figure 2 — Leakage evidence before and after correction

Use separate panels:

- former-fold component/row crossing rates with explicit denominators and an
  explicit v1-versus-v2 grouping label;
- rejected v1 first-audit result, labelled as only the first directed search
  (500 nt, train to validation), with 4,792 qualifying pairs among 3,576
  distinct rows (1,400 train queries and 2,176 validation targets); and
- final 3-by-6 audit matrix with zero violations and positive controls noted
  once per width.

Do not use a single bar axis that makes unlike rates/counts appear directly
comparable. The rejected-v1 audit stopped after that first failure by design;
17 of 18 directed searches were not run, so 4,792 is a lower bound rather than
the total v1 leakage. Any displayed rate must use row counts from the rejected
v1 assignment. Never claim the former AUROC was inflated by a measured amount.

#### Figure 3 — Component structure and giant-component gates

- v1 and v2 component-size histograms or complementary cumulative
  distributions on appropriate log scales;
- direct annotation of component counts, singleton counts, largest component,
  and top-20 fraction; and
- visible 5% single-component and 20% top-20 stop gates where meaningful.

#### Figure 4 — What each protected width contributed

- direct edge counts at 500, 251, and 101 nt;
- an UpSet-style or equivalent exact intersection view showing edge-set
  overlap across widths; and
- a separate exact/RC annotation; and
- a textual v1-protection summary: 6,406 v1 components merged into 2,640 v2
  components, covering 54,610 rows.

The figure must distinguish pair counts from the number of union operations
that happened to merge components in one application order. The stored
`v1_protected_co_membership.pair_count` is a star-join implementation artifact
(summed members minus one), not a biological or direct-similarity pair count;
it must not appear on the edge-count axis or in the edge-overlap view.

#### Figure 5 — Final partition sizes and component integrity

- achieved row fractions against 70/15/15 targets;
- row counts; and
- explicit statement that 0/169,699 components are split.

#### Figure 6 — Per-protein label balance

- two aligned heatmaps, one for known positives and one for known negatives;
- columns train/validation/test and values as percentage-point deviations from
  the relevant 70/15/15 target;
- protein ordering fixed by maximum absolute evaluation deviation, with names
  and IDs available in the accompanying table;
- each protein row annotated with that protein's total known-positive or total
  known-negative count, which is the denominator for its cells;
- a visible ±3-pp reporting boundary; and
- a compact panel or table for the most imbalanced proteins, including protein
  25 as an explanatory example.

The caption must explain that the denominator is all known positives or all
known negatives for that protein across the dataset—not within-partition
prevalence. Mark the achieved global row fractions
68.11%/15.94%/15.95% as a visual reference, but retain the prespecified
70%/15%/15% targets for >3-percentage-point flags so the report reproduces the
accepted 86-protein/218-cell all-partition result and the 54-protein/117-cell
evaluation-only result.

#### Figure 7 — Evaluation support counts

Show validation and test known-positive/known-negative counts per protein,
preferably on a log scale, with the hard floor of 30 and observed minima of 97
positives and 80 known negatives. Distinguish count sufficiency from fraction
balance.

#### Figure 8 — Sequence composition across partitions

For 500, 251, and 101 nt, compare train/validation/test distributions of:

- GC fraction;
- normalized mononucleotide Shannon entropy; and
- maximum homopolymer run length.

Use fixed deterministic bins or quantile summaries rather than bandwidth-
sensitive decorative density curves. Report effect sizes; with 361,180 rows,
small p-values alone are not evidence of a meaningful shift.

The interpretation is prespecified before computation:

- absolute standardized mean difference (SMD) at least 0.10 is called
  "notable"; a smaller absolute SMD is called "negligible";
- Kolmogorov-Smirnov `D` and robust quantiles are reported alongside SMD as
  descriptive distribution summaries, not as inferential tests;
- rows within one component are not independent, so no row-level p-value is
  reported in the main text and any uncertainty interval must use a
  component-level bootstrap; and
- maximum homopolymer length is discrete and heavy-tailed, so its quantiles
  and KS `D` are primary and SMD is secondary.

### C. Supplementary figures/tables

- complete per-protein counts and flags;
- all component-size bins;
- edge-overlap counts;
- all 18 audit records;
- full sequence-composition effect-size table; and
- an explicit claims/limitations box.

### D. Reports and package

Create:

1. a concise `docs/reports/003a_supervisor_split_validation.md` that embeds or
   links every main figure and states allowed/not-allowed claims;
2. a self-contained supervisor PDF with the same results and captions;
3. an artifact folder containing figures, tables, the report PDF, provenance,
   and a `README.md`; and
4. `manifests/task003a_split_validation_report.json`, containing only accepted
   aggregate results and output hashes—never sequences or row-level labels.

The PDF and figure package are presentation products, not new scientific
inputs. The TSV tables and manifest are the numerical source of truth.

## Definitions for composition analysis

For one sequence of length `L`:

- `GC_fraction = (G + C) / L`;
- normalized mononucleotide entropy is
  `-sum_b p_b log2(p_b) / 2`, where `b` is A/C/G/T, so the value lies in
  `[0,1]`; and
- maximum homopolymer length is the longest consecutive run of one identical
  nucleotide.

These are descriptive sequence properties, not binding labels and not model
features in this task. The exact formulas must be tested on tiny fixtures.

For pairwise partition comparisons, standardized mean difference must use a
documented pooled-standard-deviation formula. Also report robust quantiles and
Kolmogorov-Smirnov `D`. Apply the prespecified `|SMD| >= 0.10` descriptive
threshold above; do not infer independence or scientific significance from
the number of rows.

## Required tests

Use synthetic fixtures to cover:

- archive/manifest/hash drift;
- duplicate/missing/foreign membership IDs;
- component-size reconstruction and v1/v2 reconciliation;
- edge-set overlap with duplicate/reversed/self pairs;
- protein-cell denominator and percentage-point calculations;
- strict >3-pp flag boundary behavior;
- positive/negative and unknown-label separation;
- GC, entropy, and homopolymer formulas;
- streaming result equality with an in-memory tiny reference;
- audit-matrix completeness and direction uniqueness;
- deterministic table/figure source hashes;
- caption values derived from summaries rather than literals; and
- transaction failure preserving a prior accepted report.

## Acceptance gates

- Every frozen input hash and size matches.
- Final return verification succeeds before analysis.
- Every generated headline value reproduces its accepted source where an
  accepted source already exists.
- The v1 membership reconstructs exactly 173,465 components, and the legacy
  fold train/holdout index digests reproduce before the v2-grouping
  recomputation is accepted.
- Every row ID and component ID reconciles exactly.
- Protein/class totals reproduce the accepted assignment summary.
- Figures regenerate identically from unchanged tables, apart from documented
  non-content metadata in formats that cannot suppress it.
- Captions state denominators and do not overclaim causality or AUROC impact.
- The supervisor report clearly distinguishes former split, rejected v1, and
  accepted v2.
- No model, prediction, baseline, test metric, MMseqs2 search, network request,
  or split mutation occurs.

## Resource plan

Run locally and sequentially. Stream the 724-MB CSV and the 500/251/101 FASTAs.
Avoid dense row-by-protein matrices and retain only aggregate tables. Expected
peak memory should remain below 4 GiB; if implementation exceeds 8 GiB or
requires Darwin, stop and review the design rather than transferring the task.

## Review boundary

One planning review resolves genuinely blocking scientific or presentation
issues before implementation. The reviewer should not request optional UI,
formatting, or pipeline-generalization work. After the bounded corrections are
incorporated, implementation and local execution proceed without another
planning loop. A final acceptance review checks numerical reconciliation and
claim wording once.
