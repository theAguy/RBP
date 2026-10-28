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

The final stage requires `--authorize-test` and remains unavailable until a
completed pilot freezes all nine regularization choices. Final execution will
fit and verify every train-plus-validation model before the test-scoring phase
is permitted to start.

Generated row-level predictions remain under the Git-ignored
`artifacts/task003b_simple_baselines/` tree. Tracked manifests contain only
hashes, counts and aggregate results.
