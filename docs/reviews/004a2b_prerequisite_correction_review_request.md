# Task 004A-2B prerequisite correction — review request

**Requested verdict:** Approve or Stop. Review this bounded correction only.
Do not run or authorize Task 004A-2B.

## Why the correction was needed

The authorized recovery attempt stopped before Gate A because the accepted
Task 003B Phase-A manifest names the 303,582-row development aggregate
`fitting_sequence_count`, while Task 004A-2 internally names the identical
quantity `train_plus_validation_rows`. The wrapper also used Bash-4
associative arrays on macOS Bash 3.2. Full evidence is in
`docs/reviews/004a2b_phase_a_schema_stop.md`.

## Bounded changes

1. `runner_004a2._phase_a_bounds_from_payload` explicitly maps only
   `fitting.fitting_sequence_count` to `train_plus_validation_rows`. It also
   requires the accepted `['train', 'validation']` partition order and 122
   proteins. Every frozen numeric bound is unchanged.
2. `_verify_phase_a_bounds` still authenticates the whole manifest against
   SHA-256 `77922d6d...`, then applies that strict schema translation.
3. The recovery wrapper replaces `declare -A` with Bash-3-compatible indexed
   arrays without changing the three original evidence hashes or scientific
   command.
4. Regressions invoke the verifier against the exact tracked accepted
   manifest, reject changed counts/partitions, forbid `declare -A`, and run
   `/bin/bash -n`.
5. Both failed-attempt records remain immutable and documented. No new
   execution wrapper or scientific retry is authorized by this commit.

## Review boundary

Review the correction commit against `0a90052`, together with:

- `docs/tasks/004a2_local_data_contract_smoke.md`
- `docs/reviews/004a2b_prehash_sandbox_stop.md`
- `docs/reviews/004a2b_phase_a_schema_stop.md`
- `src/rbpbench/rescnn/runner_004a2.py`
- `scripts/run_004a2b_local_smoke_recovery.sh`
- `tests/test_rescnn_004a2_runtime.py`
- `manifests/task003b_phase_a_003b3.json`

The tracked Phase-A manifest is small aggregate evidence. Do not open or hash
the real CSV, membership, FASTA, ignored execution artifacts or former model
checkpoint. Do not run the recovery wrapper.

## Questions

1. Is the schema translation exact, explicit and fail-closed without changing
   any scientific count or accepted hash?
2. Do the regressions prove the exact accepted manifest now passes while
   count, partition and protein drift still stop?
3. Is the evidence-verification loop compatible with macOS Bash 3.2 while
   preserving the original stop-evidence hashes?
4. Is anything else blocking before a separately reviewed and authorized
   004A-2B retry wrapper may be prepared?

## Verification

The frozen focused suite was run twice with exactly four numerical threads:

```text
PYTHONPATH=src OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 \
OPENBLAS_NUM_THREADS=4 VECLIB_MAXIMUM_THREADS=4 \
/opt/miniconda3/envs/rbpbench-rescnn-004a2/bin/python -m pytest -q \
  tests/test_rescnn_004a_contract.py \
  tests/test_rescnn_004a_fidelity.py \
  tests/test_rescnn_004a2_data.py \
  tests/test_rescnn_004a2_runtime.py
```

Both runs: **61 passed, 20 subtests passed**, with the same two accepted
non-failing PyTorch warnings. The three new bounded regressions also passed in
isolation. `/bin/bash -n` and `git diff --check` are clean.

No 004A-2B wrapper was run. No real CSV, membership, FASTA, ignored artifact
or former checkpoint was opened or hashed during the correction or tests.
