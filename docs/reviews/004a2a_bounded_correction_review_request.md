# Task 004A-2A bounded correction — review request

**Requested verdict:** Approve or Stop. The requested B1–B4 correction is
implemented. Do not open/hash real inputs and do not authorize or run
004A-2B as part of this review.

## Review boundary

Review the correction commit against `f9a805c`, together with:

1. `docs/tasks/004a2_local_data_contract_smoke.md`
2. `docs/reviews/004a2a_local_smoke_implementation_review.md`
3. `src/rbpbench/rescnn/data_004a2.py`
4. `src/rbpbench/rescnn/smoke_004a2.py`
5. `src/rbpbench/rescnn/runner_004a2.py`
6. `src/rbpbench/cli_rescnn_004a2.py`
7. `tests/test_rescnn_004a2_data.py`
8. `tests/test_rescnn_004a2_runtime.py`
9. `pyproject.toml`

## Corrections implemented

### B1 — independent Gate-B counting

Gate A retains its dense `_CountAccumulator` and `DevelopmentCounts`. Gate B
now uses a separate sparse `Counter[(partition, protein, label)]`
implementation and a separate `IndependentDevelopmentCounts` representation.
Only their public matrices are compared. A regression corrupts Gate A's
class accounting and proves Gate B detects it. A second regression mutates a
selected row's Gate-B labels and proves per-row content drift is refused.

### B2 — durable sanitized stop evidence

After every immutable input has been hash-bound, any exception records one
atomic `STOPPED.json` outside `generations/`. It contains the stage, bounded
exception class/message, repository-relative input evidence, available access
counters, structural test-blindness evidence, `selection_record_written:
false` and `retry_authorized:false`. The candidate is still removed. A prior
stop record refuses an unreviewed retry. A regression drives `execute()` into
a Gate-A lockstep failure and proves that the stop exists, no selection exists
and no candidate remains.

### B3 — executed-source binding

Before config/input hashing, the runner inspects every loaded `rbpbench.*`
module, requires its non-symlink `.py` source under `repo_root/src`, and hashes
exactly the unique loaded source-file set. The evidence includes repository-
relative paths and module names, including `rbpbench.baselines.data` and
`rbpbench.baselines.metrics`. Worktree cleanliness now includes untracked
files. A regression moves one loaded module's `__file__` outside the source
tree and proves refusal before `_input_evidence` is called.

### B4 — production-CNN paired smoke

A synthetic focused test runs the real 9,029,562-parameter
`CNNMultiLabelResidual` on the full 513-train/513-validation cache, all three
loss configurations, primary and repeat, exactly four threads. It proves
identical scientific signatures, `[256, 256, 1]` validation batches, 122/122
eligible outputs, safe checkpoint reload and combined checkpoint bytes below
1 GiB. The production runner no longer accepts an arbitrary model factory and
validates the real model class/parameter count on every construction.

All three initial-state hashes are now compared explicitly. A batch-normalized
test model whose running state changes without changing training-mode logits
proves the old implicit-logit check was insufficient.

### Folded-in hardening

- sanitized input paths are repository-relative;
- evidence labels zero test accesses as a structural
  branch-before-interpretation guarantee;
- `rbp-rescnn-smoke` now enters through an import-safe top-level CLI shim that
  sets all four numerical-thread environment variables before importing
  PyTorch; and
- the isolated editable installation was refreshed, its console script points
  to that shim, and the live environment still exactly matches
  `manifests/task004a2_local_environment.json`.

## Verification

The focused suite was run twice in the frozen environment with all numerical
thread variables set to four:

```text
PYTHONPATH=src OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 \
OPENBLAS_NUM_THREADS=4 VECLIB_MAXIMUM_THREADS=4 \
/opt/miniconda3/envs/rbpbench-rescnn-004a2/bin/python -m pytest -q \
  tests/test_rescnn_004a_contract.py \
  tests/test_rescnn_004a_fidelity.py \
  tests/test_rescnn_004a2_data.py \
  tests/test_rescnn_004a2_runtime.py
```

Both runs: **58 passed, 20 subtests passed**, with the same two non-failing
PyTorch warnings. The isolated real-CNN regression also passed independently
in 58.37 seconds. Python compilation and `git diff --check` are clean.

No real CSV, accepted membership/FASTA, former checkpoint, ignored Task 004A
artifact or GPU workload was opened or executed.

## Questions

1. Is Gate B now independent enough to catch a defect in Gate A's counting?
2. Does every post-hash failure preserve sufficient sanitized evidence while
   leaving no accepted/candidate generation and forbidding silent retry?
3. Does source binding prove that the imported code is the code whose files
   are hashed, including baseline label/metric dependencies?
4. Does the production-CNN synthetic test close the last unexecuted local
   model path at the frozen batch sizes and four-thread setting?
5. Is any Stop-level defect left within 004A-2A?
