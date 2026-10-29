# Task 004A-1 ResCNN source-evidence specification

**Status:** synthetic/source reconstruction implemented; no real dataset,
accepted FASTA, ignored artifact, former checkpoint or GPU was opened.

This document records what was extracted from the former teammate's notebook
and distinguishes it from the experimental controls introduced by Task 004A.
The executable frozen contract is `configs/models/task004a_v1.toml`.

## Source identity

The complete notebook `intRBP ResCNN - for students.ipynb` has SHA-256
`9a04f551ed9e5420c720074bf57f41f1c93ab92acc37c3b8ff44868e6b021b84`.
The implementation never trusts a notebook cell unless the complete notebook
hash and the relevant UTF-8 cell-source hash both match.

| Evidence | Cell | Cell-source SHA-256 | Meaning |
|---|---:|---|---|
| dataset parsing | 6 | `757b77757b8f467629123d4fd572b0780eaffe3fe84f5a8d42809c6ac3b5d905` | signed IDs become 122 target/mask columns |
| input dataset | 7 | `15eac805937228d4ce6e3b8cb47f9838a3b2053307e6ada1cc9153f2ac1eeae2` | 2,000 bits reshape to `[500,4]` float32 |
| architecture oracle | 8 | `2bc4917653698b2c38e690c184924b46c222ea2ebe632d7bf225993b6fff1e0c` | three residual blocks and dense classifier |
| loss oracle | 11 | `dbb61960cb79ee5bc727b03d7f3703a857a3f61a02899cd8af250d362a312f5a` | weighted known BCE plus unknown-negative BCE |
| evaluation | 12 | `abae3bad9e4fd78f9a6aee575cd985e85a8a1f594cef80996abf109a64a92c34` | sigmoid scores and known-label AUROC |
| update step | 13 | `8c1fcaa66627144b754007510a35c8c04de7b3dbe577c3e1c9bf8e30c2cb5118` | zero grad, forward, loss, backward, Adam step |
| label/base mapping | 17 | `f279df267773b75f4fdfebaff5bf79e08d1ac4b189b1e723d4a1b63a55b6ef75` | proteins 1--122 and A/C/G/T channel order |
| submitted constants | 22 | `b8fa0fadfd365e5ade84dffdda4d055018405132705dc44ca38524824644a3b4` | 30 epochs, batch 256, LR 1e-3, coefficients 15 and 1 |
| submitted orchestration | 24 | `1710e20f0bb62febecec9850163fa769bb46a74ef80e3e8ce5944a5d98b1ce5b` | fold, loaders, Adam, scheduler and final save |

Cells 8, 11 and 22 are executed directly as isolated, hash-checked oracles in
the focused tests. Other cells are descriptive source evidence; no notebook
data-loading or training cell is executed.

## Faithfully preserved scientific behavior

- The input is one supplied-orientation 500-nt sequence with A/C/G/T channels.
- One joint model produces 122 logits, with protein ID `k` at column `k-1`.
- Unsigned `k` or `+k` is known positive, `-k` is known negative and absence is
  unknown.
- The exact architecture has 9,029,562 learnable parameters. Every convolution,
  normalization, activation, pooling, dense and dropout default is explicit in
  the frozen config and clean implementation.
- Known-positive BCE receives multiplier 15 without renormalizing by summed
  weights. Known terms are divided by the number of known entries. Unknown
  entries are separately trained toward zero and divided by the number of
  unknown entries.
- Adam starts at `1e-3`. `ReduceLROnPlateau(mode="max", factor=0.5,
  patience=2)` receives macro validation AUROC. The fidelity artifact is the
  epoch-30 state; there is no early stopping or best-epoch selection.

## Controlled experimental-scaffolding changes

These are deliberate controls, not claims about the former notebook:

1. The accepted components-v2 train/validation/test assignment replaces the
   former row-level multilabel fold.
2. Test labels and sequences are rejected before interpretation. Only train
   updates weights, and only validation drives the scheduler and development
   metrics.
3. Training uses `drop_last=True`. The accepted training count leaves a
   one-sample tail, which cannot pass the dense training-mode `BatchNorm1d`.
   Validation retains its partial final batch.
4. Strict float32 and deterministic settings replace the notebook's implicit
   runtime defaults. TF32, AMP and warning-only deterministic fallback are
   forbidden.
5. Three paired loss configurations share identical initialization, sample
   order, dropped row and model-stochastic random streams. They change only
   `(positive multiplier, unknown coefficient)`: `(15,1)`, `(15,0)`, `(1,0)`.
6. Whole runs are transactional. An interrupted run has no accepted
   generation and restarts at epoch 0; mid-run resume is unsupported.
7. Validation reports per-protein AUROC/AP, honest macro averages and
   `pooled_known_entry_AP`. Threshold optimization is excluded.

## Synthetic acceptance evidence

The focused tests verify direct notebook initialization, state tensors,
train/eval logits and gradients; hand-calculated loss components; the exact
parameter count; singleton-tail handling; paired RNG streams; strict runtime
settings; partition-first test blindness; compact one-hot encoding; exactly
122 scheduler outputs; collapse diagnostics; validation-only prediction
schema; nested artifact inventory; whole-run rollback; and final-checkpoint
save/reload identity.

Task 004A-1 does not demonstrate real-data joins, GPU resource suitability or
scientific performance. Those remain checkpoints 004A-2 through 004A-5.
