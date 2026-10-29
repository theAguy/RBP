# Task 004A ResCNN reconstruction — independent planning review request

## Requested verdict

Review `docs/tasks/004a_rescnn_reconstruction_and_development_pilot.md` as a
scientific, fidelity and execution plan. Do not implement code, train a model,
open the real CSV/FASTA/membership, or inspect ignored prediction artifacts.

Return one evidence-backed verdict:

- `Approve`;
- `Approve with bounded corrections`; or
- `Stop`.

Raise only issues that can change faithful reconstruction, scientific
interpretation, test blindness, deterministic reproducibility or feasible GPU
execution. Cosmetic additions are non-blocking.

## Context

Tasks 002C and 003A accepted a leakage-safe components-v2 train/validation/test
split. Task 003B then established prevalence, GC, 3-mer and 6-mer reference
baselines on that split. No neural model has yet been run on it.

The original notebook trains a joint 122-output residual CNN at 500 nt. Its
known-label BCE gives positives 15 times the ordinary element weight, and a
separately normalized term pushes unknown entries toward zero. It creates its
own row-level fold and saves the final epoch. Task 004A proposes to preserve
the network/loss/optimizer behavior while replacing the unsafe experimental
scaffolding with the accepted split and versioned execution.

## Proposed scientific boundary

- 500 nt only, because it is the only literal notebook architecture.
- Joint 122-output training for every config.
- Three loss configs: `(positive, unknown) = (15,1), (15,0), (1,0)`.
- Full 30 epochs, final-epoch checkpoint, no early stopping/best-epoch
  selection because the notebook has neither.
- Train gradients only; validation scheduling/metrics only; no test access.
- Three frozen seeds, with a one-seed convergence gate before the remaining
  two.
- Eight development proteins may guide engineering decisions; the scheduler
  retains the notebook's all-eligible-output macro AUROC statistic.
- Local implementation and bounded smoke; Newton one-GPU resource probe and
  pilot only after implementation acceptance.

## Questions requiring explicit review

1. Is limiting fidelity Task 004A to 500 nt correct, given that 251/101 require
   changing the flatten dimension, padding, or adaptive pooling and therefore
   define different architectures?
2. Does the architecture specification, parameter-count gate and independent
   oracle comparison sufficiently establish notebook fidelity?
3. Does the exact batchwise loss reconstruction preserve the unusual
   normalization? Do the three configs isolate the unknown penalty and
   positive multiplier one change at a time?
4. Is final epoch after 30 epochs the correct fidelity checkpoint, rather than
   silently adding validation-selected checkpointing or early stopping?
5. Is retaining the notebook's all-output validation AUROC for the scheduler
   compatible with restricting engineering judgments to the eight development
   proteins?
6. Are the fixed seeds and staged one-seed-then-two-seed execution sufficient
   to measure variability without enabling favorable seed selection?
7. Does the cache/streaming boundary genuinely prevent test labels and
   sequences from influencing development while permitting whole-file hash
   verification and sequential traversal?
8. Are float32/no-AMP/no-compile, optimizer defaults, scheduler defaults and
   deterministic-loader rules frozen precisely enough?
9. Are the local-versus-Newton responsibilities and resource gates
   proportionate? Is any additional GPU-specific evidence required before the
   full pilot?
10. Are validation AUROC/AP, decomposed loss, gradients and resource evidence
    sufficient for this engineering pilot without F1 threshold optimization?
11. Does any proposed behavior inadvertently use the test set, alter the
    submitted scientific model or make the later controlled comparison unfair?
12. Is any remaining issue genuinely blocking before 004A-1 synthetic
    implementation?

## Review boundary

Do not request a competitor implementation, test evaluation, coordinates, a
new split, new similarity thresholds, motif analysis, 150-nt inputs or the
full 251/101 window study. If a concern belongs to a later controlled or
confirmatory task, label it deferred rather than blocking Task 004A.
