# Task 003B simple sequence baselines — planning review request

## Requested verdict

Review `docs/tasks/003b_simple_sequence_baselines.md` as a scientific and
implementation plan. Do not implement code and do not open the real CSV,
accepted FASTAs, final membership or test artifacts.

Return one of:

- `Approve`;
- `Approve with bounded corrections`; or
- `Stop`.

Raise only issues that can change scientific validity, test blindness,
reproducibility or realistic execution. Cosmetic refinements are non-blocking.

## Context

Task 002C accepted and froze a leakage-safe split with 169,699 connected
components and zero detected cross-partition relationships under the frozen
rules. Task 003A explained why that split replaces the former teammate's
row-level fold. Task 003B is the first predictive experiment.

It deliberately implements only four inexpensive reference points:

1. training prevalence;
2. GC-content logistic regression;
3. ordered 3-mer-frequency logistic regression; and
4. ordered sparse 6-mer-frequency logistic regression.

It runs all three biologically relevant widths: 500, 251 and 101 nt. It does
not run 150 nt and does not run the former ResCNN or competitors.

## Frozen decisions to assess

- Unknown labels are excluded, never treated as negatives.
- Validation tuning is limited to eight frozen development proteins.
- One C is selected per fitted baseline and width from
  `[0.01, 0.1, 1.0, 10.0]`, with a smaller-C tie-break.
- Pilot: train only → validation only, with a hard prohibition on test access.
- Final: after explicit authorization, refit train+validation and score test
  once without changing code/config.
- AUROC is primary; average precision is secondary.
- Primary results use all known labelled rows; GC-matched evaluation is a
  secondary frozen diagnostic.
- 6-mer features are sparse and processed one width at a time.
- Point estimates are reported now; component-aware confidence intervals are
  deferred until methods are compared together.

## Questions

1. Does the plan prevent all test-set influence before the explicit final
   authorization?
2. Are the four baselines and ordered k-mer definitions scientifically clear
   and comparable across 500/251/101 nt?
3. Is choosing one C per baseline/width across the eight development proteins
   preferable to per-protein test-adjacent tuning?
4. Are the unweighted loss, fixed solver, C grid and deterministic tie-break
   sufficiently frozen?
5. Is the prevalence baseline an appropriate deterministic replacement for an
   arbitrary random-score baseline?
6. Does the GC-matched diagnostic avoid leakage and post-hoc selection?
7. Are the prediction, count reconciliation and sparse-memory contracts
   sufficient for later model comparison?
8. Is deferring component-aware confidence intervals to the paired comparison
   scientifically acceptable?
9. Is any remaining issue genuinely blocking before synthetic implementation?

## Review boundary

Do not request neural-model implementation, coordinates, a new split,
different similarity thresholds, additional window lengths, external motif
databases or a full Task 004 comparison. Those are outside Task 003B.
