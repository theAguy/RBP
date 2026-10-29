# Task 004A-1 implementation review request

## Requested verdict

Review commit `721d63b` on branch `issue-003b-simple-baselines` and return one
of:

- **Approve**;
- **Approve with bounded corrections**; or
- **Stop**.

This is review only. Do not modify files, open real/ignored data, run GPU work,
or begin Task 004A-2.

## Required reading

Read these tracked files in order:

1. `docs/tasks/004a_rescnn_reconstruction_and_development_pilot.md`
2. `docs/reviews/004a_rescnn_reconstruction_planning_reconciliation.md`
3. `docs/reports/004a1_rescnn_source_evidence.md`
4. `configs/models/task004a_v1.toml`
5. all files under `src/rbpbench/rescnn/`
6. `tests/test_rescnn_004a_fidelity.py`
7. `tests/test_rescnn_004a_contract.py`
8. the source of notebook cells 6, 7, 8, 11, 12, 13, 17, 22 and 24 in
   `intRBP ResCNN - for students.ipynb`, without executing data/training cells.

Confirm the notebook's complete SHA-256 before trusting any cell. Do not open
the real CSV, accepted FASTA, accepted membership, ignored artifacts or former
model checkpoint.

## Implementation boundary

Commit `721d63b` adds only the source/synthetic checkpoint:

- exact frozen config and source-evidence report;
- literal 500-nt, 122-output ResCNN;
- direct, hash-checked notebook architecture/loss/hyperparameter oracles;
- exact decomposed submitted loss and two ablations;
- partition-first compact data contract with synthetic test-blindness proof;
- labelled paired RNG streams and deterministic epoch-order evidence;
- strict float32/determinism assertions;
- known-label validation metrics, 122-output scheduler gate and collapse
  diagnostics;
- recursive whole-run artifact inventory with atomic promotion/rollback; and
- atomic final-epoch checkpoint save/reload validation.

It does not include a real-data runner, GPU environment, training job or any
Task 004A-2+ execution.

## Evidence already produced

Focused command, run twice in the local cached PyTorch 1.12/Python 3.10
environment:

```text
python -m unittest \
  tests.test_rescnn_004a_fidelity \
  tests.test_rescnn_004a_contract
```

Both runs: `Ran 28 tests ... OK` (1.661 s and 1.368 s).

The repository-wide synthetic run in the existing Python 3.12 scientific
environment collected successfully and returned:

```text
1160 passed, 33 skipped, 56 failed
```

Every failure was in pre-existing coordinate/split modules and attributable
to unavailable real-artifact state, host RAM detection, absent pinned
MMseqs2, or the legacy exact environment. The two new ResCNN modules skipped
cleanly there because that environment intentionally has no PyTorch. Commit
`721d63b` modifies no pre-existing executable module.

`git diff --check` and Python compilation passed before commit. Only the 15
reported source/config/docs/test files were committed. No real input or
ignored output was accessed.

## Questions for the reviewer

1. Does the clean model match notebook cell 8 exactly, including all formerly
   implicit PyTorch defaults, 9,029,562 learnable parameters and the 500-nt
   boundary?
2. Is direct cell extraction sufficiently bound and isolated? Are the
   same-seed state, train/eval logits and gradient comparisons adequate?
3. Does the loss reproduce cell 11 for `(15,1)`, `(15,0)` and `(1,0)`, while
   correctly failing on invalid tensors and zero denominators?
4. Does the frozen config fully specify architecture, labels, encoding,
   optimizer, scheduler, loss configurations and determinism without a silent
   caller override?
5. Is `drop_last=True` correctly confined to training, with the deterministic
   omitted row and validation tail preserved?
6. Are labelled initialization/loader/model-stochastic streams sufficient for
   the required paired comparison? Identify any place where config identity
   could accidentally influence a stream.
7. Does the deferred-field synthetic contract prove partition-first test
   blindness at the 004A-1 boundary? What additional real-data proof, if any,
   belongs specifically in 004A-2 rather than this checkpoint?
8. Are the AUROC/AP aggregation names and exactly-122-output scheduler gate
   scientifically correct, and are technical-collapse diagnostics distinct
   from scientific underperformance?
9. Does the transactional writer hash every nested artifact, reject additions
   or drift, roll back failed selection writes and forbid mid-run resume?
10. Is the trusted-current-run checkpoint loader sufficiently separated from
    the forbidden former checkpoint? The former checkpoint was deliberately
    not opened in this source-only checkpoint.
11. Are any tests falsely passing because the direct notebook oracle and clean
    implementation share an unintended dependency?
12. Is there any genuine scientific, correctness, provenance or test-blindness
    blocker before planning and executing the bounded local Task 004A-2 smoke?

For every correction, state the exact failure it prevents and the earliest
checkpoint that needs it. Do not request cosmetic refactors or work belonging
to Task 004A-2 through 004A-5.
