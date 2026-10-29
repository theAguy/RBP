# Task 003B final baseline acceptance

**Verdict:** accepted. Task 003B is complete.

## Boundary and execution

Phase B ran once after the separately accepted Phase A. It revalidated the
frozen CSV, components-v2 membership, three decoded FASTAs, Phase-A manifest,
selection record and every saved model artifact before test access. It loaded
the saved train-plus-validation models and performed zero fits. The test run
completed locally in 108.62 seconds with one numerical thread.

The run evaluated 122 proteins, four baselines and three widths, producing
1,464 protein/baseline/width metric rows and 743,352 predictions over 61,946
known test protein-row pairs. Unknown labels were excluded, not treated as
negative. All 57,598 test rows had at least one known protein label.

Every prediction identity was unique. An independent pass using scikit-learn
recomputed AUROC and average precision for all full and GC-matched groups; the
largest difference from the stored metrics was `1.33e-15`. All 366 prevalence
groups had AUROC exactly 0.5. The accepted imbalance disclosure also reproduced
exactly: 86 proteins/218 cells overall and 54 proteins/117 cells in
validation/test were flagged; no flagged protein was removed.

## Descriptive test results

Unweighted macro means across all 122 proteins:

| Width | Baseline | AUROC | Average precision | GC-matched AUROC | GC-matched AP |
|---:|---|---:|---:|---:|---:|
| 500 | Prevalence | 0.5000 | 0.5724 | 0.5000 | 0.5000 |
| 500 | GC | 0.7156 | 0.7483 | 0.5066 | 0.5103 |
| 500 | 3-mer | 0.8336 | 0.8637 | 0.7182 | 0.7250 |
| 500 | 6-mer | 0.8220 | 0.8559 | 0.7221 | 0.7267 |
| 251 | Prevalence | 0.5000 | 0.5724 | 0.5000 | 0.5000 |
| 251 | GC | 0.7179 | 0.7504 | 0.5054 | 0.5106 |
| 251 | 3-mer | 0.8275 | 0.8587 | 0.7098 | 0.7157 |
| 251 | 6-mer | 0.8035 | 0.8378 | 0.7016 | 0.7047 |
| 101 | Prevalence | 0.5000 | 0.5724 | 0.5000 | 0.5000 |
| 101 | GC | 0.7109 | 0.7462 | 0.5038 | 0.5094 |
| 101 | 3-mer | 0.8049 | 0.8374 | 0.6822 | 0.6848 |
| 101 | 6-mer | 0.7738 | 0.8107 | 0.6670 | 0.6684 |

These are descriptive point estimates, not significance tests and not a basis
for selecting a width after viewing test. They support three limited findings:

1. GC alone is strongly predictive in the full test set, but its AUROC falls
   to approximately 0.50 after deterministic within-bin GC matching. This is
   expected and validates the sensitivity analysis.
2. Ordered 3-mer and 6-mer composition retain substantial discrimination after
   GC matching, so their signal is not explained by total GC content alone.
3. The longer 500-nt input is descriptively stronger than 101 nt for the
   composition baselines: mean AUROC differences are +0.0287 for 3-mer and
   +0.0482 for 6-mer; 500 nt is higher for 97/122 and 103/122 proteins,
   respectively. This is compatible with a useful longer context, but does not
   prove that a future neural model benefits by the same amount.

The 3-mer and 6-mer results are reference baselines, not competitors to the
former teammate's ResCNN. Task 003B did not run the ResCNN, DeepRiPe,
Multi-resBind or PrismNet-seq, so it cannot yet answer which predictive model
is best.

## GC-matched limitation

The matched subset is deterministic, uses Phase-A training-derived decile
edges, balances positive and negative test examples within each bin, and never
replaces examples. Retention varies by protein from 10.2% to 89.3% (50 to 554
rows). Matched results therefore remove the gross GC-composition advantage but
can be noisier for proteins with low retention. They remain secondary.

## Closure and next step

The closure manifest is
`manifests/task003b_simple_baselines.json`. Row-level predictions remain under
the Git-ignored artifact generation and are hash-bound by the manifest.

The next scientific task is Task 004: reproduce the former teammate's joint
ResCNN and the prespecified competitors on this same accepted split and these
same 500/251/101 windows. Component-aware uncertainty and paired comparisons
must be applied uniformly to every method at that later stage.
