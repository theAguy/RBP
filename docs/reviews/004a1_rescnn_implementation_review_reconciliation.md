# Task 004A-1 implementation-review reconciliation

**Review verdict:** Approve with bounded corrections.

**Current status:** both required corrections and the small same-boundary
hardening items are implemented; Task 004A-2 remains unstarted pending final
review of this amendment.

## Review boundary

The reviewer statically checked implementation commit `721d63b`, independently
verified the complete notebook hash and the nine source-cell hashes, and did
not open real data, ignored artifacts or the former checkpoint. The reviewer
found the architecture, direct notebook oracles, loss, config, test-blindness
boundary, metrics and transactional design faithful. No Stop-level issue was
found.

## C1 — checkpoint authentication before deserialization

The prior loader computed schema and run-identity checks only after
`torch.load`, and callers could supply an incomplete expected-identity map.
That was insufficient before 004A-2's save/reload smoke.

The corrected loader now:

1. requires and recomputes the expected checkpoint file SHA-256 before any
   deserialization;
2. refuses the frozen former-checkpoint SHA-256 explicitly;
3. requires exactly source/config/environment hashes, seed and config ID;
4. validates those values against the frozen Task 004A domain;
5. uses `weights_only=True` whenever the installed PyTorch exposes that
   argument; and
6. only then loads and validates schema, final epoch, complete identity and
   canonical model-state hash.

Tests prove that hash mismatch, partial identity and the former hash all stop
before `torch.load` is called.

## C2 — integrated paired-config start and update proof

The original tests independently covered seed streams, epoch ordering, dropout
and model initialization, but did not exercise the complete CNN/loss/update
sequence for all three configurations.

`initialize_paired_model` is now the single required start sequence: derive
the labelled streams, reset initialization RNG, build and hash the complete
CNN, then reset the model-stochastic RNG immediately before the first
training-mode forward. It accepts no config ID or loss coefficient.

The integrated synthetic regression loads all three frozen loss configs and
proves:

- identical complete-CNN initial-state hashes;
- identical epoch order and one dropped tail row for `N mod batch = 1`;
- every admitted training batch has at least two samples;
- byte-identical training-mode logits before the first update, including the
  shared dropout realization; and
- different post-Adam model-state hashes for `submitted` and
  `joint_standard`, demonstrating that the reviewed coefficient change
  actually affects the update.

## Additional same-boundary hardening

The amendment also implements the reviewer's small 004A-1 items:

- unknown keys in any `[[loss_configs]]` table fail closed;
- batch-size variation is compared directly with the notebook loss oracle;
- non-binary masks and negative/zero coefficients are rejected;
- a monkeypatched selection-record write failure proves the previously
  accepted record/generation survive and the new generation is discarded; and
- selected generation paths must exactly match
  `generations/<stage>_<12 lowercase hex>`.

## Correctly deferred findings

These observations belong to later reviewed checkpoints and were not pulled
into the source-only amendment:

- 004A-2 must construct loss, Adam and scheduler only from the frozen config;
- 004A-2 must use unshuffled validation and compute metrics on float32 sigmoid
  scores, matching notebook evaluation semantics;
- 004A-2 must supply the real partition-first supplier/counter proof and
  selection record with `test_accessed: false`;
- compact-cache construction and peak memory must be measured before 004A-3;
  and
- the focused suite must be repeated and environment-bound in the eventual
  Newton PyTorch/CUDA environment.

No real CSV, accepted FASTA, membership, ignored artifact, former checkpoint,
GPU or training job was accessed while implementing this amendment.
