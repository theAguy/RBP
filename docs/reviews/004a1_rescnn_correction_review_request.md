# Task 004A-1 correction review request

Review correction commit `b442eb4` on branch
`issue-003b-simple-baselines`, relative to reviewed implementation commit
`721d63b`.

Return **Approve**, **Approve with bounded corrections**, or **Stop**. Review
only; do not edit files, open real data/ignored artifacts/the former
checkpoint, or start Task 004A-2.

Required reading:

1. your original Task 004A-1 review;
2. `docs/reviews/004a1_rescnn_implementation_review_reconciliation.md`;
3. the complete diff `721d63b..b442eb4`; and
4. the two focused test files as they stand at `b442eb4`.

Please verify four points:

1. **C1:** the checkpoint file hash, explicit former-checkpoint rejection and
   exact complete identity are checked before `torch.load`; `weights_only=True`
   is used when supported; valid current-run final checkpoints still reload.
2. **C2:** `initialize_paired_model` cannot receive config identity, performs
   the accepted reset/build/hash/reset sequence, and the integrated test
   genuinely proves equal CNN initialization/order/tail/dropout plus a
   coefficient-dependent post-Adam update across the three loaded configs.
3. The additional bounded tests correctly cover unknown loss-config keys,
   batch-size variation, non-binary masks, invalid coefficients,
   selection-write rollback and exact generation paths.
4. No new scientific choice or work from Task 004A-2+ entered the amendment.

Focused evidence after the correction:

```text
python -m unittest tests.test_rescnn_004a_fidelity tests.test_rescnn_004a_contract
Ran 36 tests ... OK
Ran 36 tests ... OK
```

The runs used the same local Python 3.10 / PyTorch 1.12 source-only test
environment as the reviewed implementation. Python compilation and
`git diff --check` passed. No real input, ignored artifact, former checkpoint,
GPU or training job was accessed.

If approved, state explicitly that Task 004A-1 may close and Task 004A-2 may
be planned. Keep later-checkpoint observations deferred as recorded in the
reconciliation.
