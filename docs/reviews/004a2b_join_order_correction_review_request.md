# Task 004A-2B join-order correction — review request

**Requested verdict:** Approve or Stop. Review this bounded correction only.
Do not run or authorize Task 004A-2B.

## Cause and correction

The accepted membership is serialized lexically (`row_0`, `row_1`,
`row_10`, ...), whereas the accepted CSV/FASTA are serialized by numeric row
index (`row_0`, `row_1`, `row_2`, ...). The prior Gate-A/Gate-B code zipped
all three streams and therefore stopped on valid row 2.

The correction parses the membership once per gate into a validated numeric
ID index. It requires:

- canonical `row_<nonnegative integer>` IDs;
- exactly one record per numeric ID;
- the complete contiguous universe `row_0..row_<N-1>`;
- nonempty component IDs and only train/validation/test partitions.

CSV and FASTA remain streamed together in numeric row order. For each index,
the gate retrieves exactly that membership record and retains the existing
FASTA-ID check, component-integrity check, field parsing, count reconciliation,
test-blind branch and content digests. A final count equality check catches a
membership or CSV/FASTA tail mismatch. No scientific value or model behavior
changes.

## Regressions

The correction must prove that:

1. a synthetic membership serialized in the exact lexical pattern now gives
   the same Gate-A result as numeric serialization;
2. Gate B produces the same content digest/counts under lexical serialization;
3. test rows remain structurally blind;
4. duplicate, missing and foreign membership IDs fail closed; and
5. the pre-existing FASTA-ID, length, content, count-independence and model
   boundary tests remain green.

## Review boundary

Review the correction commit against `05651e7`, together with:

- `docs/tasks/004a2_local_data_contract_smoke.md`
- `docs/reviews/004a2b_lockstep_order_stop.md`
- `src/rbpbench/rescnn/data_004a2.py`
- `src/rbpbench/rescnn/runner_004a2.py`
- `tests/test_rescnn_004a2_data.py`
- `tests/test_rescnn_004a2_runtime.py`

Do not open or hash real CSV, membership, FASTA, ignored artifacts or model
checkpoints. Do not modify/delete the stopped output. Do not prepare or run a
retry wrapper.

## Questions

1. Does the new index authenticate membership identity independently of file
   order while refusing duplicates, gaps and foreign IDs?
2. Do Gate A and Gate B still join every numeric CSV/FASTA row to exactly its
   own membership record and reject row-count/tail mismatch?
3. Is test blindness unchanged because partition lookup still occurs before
   any test label or sequence interpretation?
4. Is the bounded memory cost proportionate for 361,180 small membership
   records under the existing 4-GiB available/peak gates?
5. Is any Stop-level defect left before a separately prepared and authorized
   recovery attempt?

## Verification

The focused suite was run twice in the frozen CPU environment with all four
numerical-thread variables fixed to four:

```text
PYTHONPATH=src OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 \
OPENBLAS_NUM_THREADS=4 VECLIB_MAXIMUM_THREADS=4 \
/opt/miniconda3/envs/rbpbench-rescnn-004a2/bin/python -m pytest -q \
  tests/test_rescnn_004a_contract.py \
  tests/test_rescnn_004a_fidelity.py \
  tests/test_rescnn_004a2_data.py \
  tests/test_rescnn_004a2_runtime.py
```

Both runs: **64 passed, 20 subtests passed**, with the same two accepted
non-failing PyTorch warnings. `git diff --check` and Python compilation are
clean.

No real CSV, membership, FASTA, ignored stopped artifact or model checkpoint
was opened or hashed. No 004A-2B wrapper or real-data stage ran.
