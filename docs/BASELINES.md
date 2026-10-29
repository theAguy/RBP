# Simple sequence baselines

Task 003B implements deterministic reference models on the accepted
components-v2 split:

- training prevalence;
- GC-content logistic regression;
- ordered 3-mer-frequency logistic regression; and
- ordered sparse 6-mer-frequency logistic regression.

Every model is evaluated independently at 500, 251 and 101 nt. Unknown labels
are excluded. The former teammate fold is never used.

## Environment

```bash
uv venv .venv-003b-baselines --python /Users/guyassa/.local/bin/python3.12
uv pip install --python .venv-003b-baselines/bin/python \
  -r manifests/task003b_environment_003b1.lock.txt
```

Use one numerical thread for deterministic, resource-bounded runs:

```bash
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
```

## Synthetic verification

```bash
PYTHONPATH=src .venv-003b-baselines/bin/python tests/test_baselines_003b.py
```

The tests use generated sequences, labels and memberships only. They do not
open the real CSV, accepted FASTAs, final membership or test predictions.

## Execution boundary

The pilot command accepts only train labels/features for fitting and validation
labels/features for scoring. Test rows may pass through whole-file hash or
stream verification, but their labels are not parsed and their features are not
constructed or retained.

The accepted pilot freezes all nine regularization choices. Final execution is
split into two independently selected stages:

- `final-phase-a` fits all 1,098 logistic models (122 proteins × three fitted
  baselines × three widths) on train plus validation, records prevalence and
  training-derived GC bins, and serializes coefficients/scalers. It rejects
  `--authorize-test` and never parses a test label or builds a test feature.
- `final-phase-b` verifies the accepted Phase-A manifest, selection record and
  every model artifact before it reads test labels or sequences. It requires
  `--authorize-test`, loads the saved models without refitting, scores test
  once, and runs the training-GC-bin sensitivity analysis. Predictions carry
  a deterministic GC-matched indicator so full and matched metrics can be
  regenerated from the prediction file before the generation is accepted.

Phase A is run with the same immutable CSV, membership and three FASTAs as the
pilot, plus the accepted `manifests/task003b_pilot_003b2.json`. A successful
selection record is written to
`artifacts/task003b_simple_baselines/selected/final_phase_a.json`.

Phase B additionally requires the accepted
`manifests/task003b_phase_a_003b3.json`. It recomputes the accepted split's
per-protein balance disclosure from the frozen CSV and membership and checks
the published totals before scoring. Flagged proteins remain in every result;
aggregate output is stratified by the flag. Phase B is descriptive only: it
does not select a baseline or width from test performance and makes no
significance claim.

Generated row-level predictions remain under the Git-ignored
`artifacts/task003b_simple_baselines/` tree. Tracked manifests contain only
hashes, counts and aggregate results.
