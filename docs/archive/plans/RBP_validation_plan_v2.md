# Validating an RBP-binding predictor against published methods

**Project plan — version 2, revised after review**
Course project, Technion bioinformatics, winter 2026
15 Sep 2026

---

## 0. What changed in v2

All eight review points accepted. Two findings emerged from checking them, and both change the plan materially.

| # | Review point | Response |
|---|---|---|
| 1 | Add joint-vs-single-task ablation; DeepRiPe is multitask | **Accepted; my error.** Expanded to a 2×2 design — see §5.1 |
| 2 | Audit leakage; verify stratification; confirm mask-aware loss | **Accepted. Measured — far worse than assumed.** See §3.1, §3.2 |
| 3 | RBPNet reproduction is not faithful | **Accepted.** Demoted to exploratory; §4.3 gives the selection principle |
| 4 | Retrain for 101 nt; retrain in-house on all folds | **Accepted.** New information makes this cleaner — §4.4 |
| 5 | Raw AUROC primary; don't pick baselines on test | **Accepted** with one scoping note — §6.1 |
| 6 | Original *and* composition-matched evaluation | **Accepted** — §6.4 |
| 7 | Numeric decision rules, effect sizes, CIs | **Accepted.** Thresholds now prespecified — §8 |
| 8 | Dinucleotide-preserving shuffles, multiple per sequence | **Accepted** — §6.3 |

**Two new findings:**

- **Window overlap is pervasive.** 76.6% of rows share ≥300 nt of exact sequence with another row. The random split leaks badly. §3.1.
- **The in-house loss trains unknowns as negatives.** Undocumented, and it confounds the multitask ablation. §3.2.

**One correction from the project side:** the 500 nt windows are peak-centred and symmetric. Window size is therefore a clean nested ablation (101 ⊂ 251 ⊂ 500, same centre), not a confound.

---

## 1. The problem

RNA-binding proteins (RBPs) attach to RNA at specific sites; predicting those sites from sequence is an established deep-learning task with several published solutions.

A teammate built a single **multi-label** neural network predicting all 122 proteins jointly, on the hypothesis that proteins share binding preferences and a joint model transfers knowledge between them — especially to proteins with little data. That teammate has since left the project; there is no documentation beyond the code.

My role is **validation**: determine whether the approach genuinely outperforms established methods, and if so, why. A negative result is an acceptable outcome.

**Revised novelty framing.** v1 claimed existing methods train one model per protein. That is wrong — DeepRiPe is itself multitask. The in-house model's distinguishing features are (a) a residual CNN architecture, (b) a 500 nt input window, (c) 122 proteins jointly, and (d) a positive-unlabelled loss term (§3.2). Isolating which of these matters is now a core objective rather than an afterthought.

---

## 2. The data

### 2.1 Inventory

| File | Contents |
|---|---|
| `dataset_K562_multilabel_with_NEGs.csv` | 361,180 sequences × 122 protein labels. 724 MB |
| `intRBP ResCNN - for students.ipynb` | In-house model, training and evaluation code |
| `CNNMultiLabelResidual_20250812_123241.pth` | Trained weights, fold 0 only |
| `output_sequences.tsv` | Centre 101 nt, decoded — prepared for PrismNet |
| `out_tests/out/infer/*.probs` | PrismNet output, 100 of 122 proteins |

Source: ENCODE eCLIP, K562 cell line.

### 2.2 Format

Each row is 500 RNA letters, one-hot encoded (2,000 bits, groups of 4, order ACGT), **peak-centred and symmetrically extended**, plus signed integer labels: `+7` = protein 7 binds; `−18` = protein 18 does not.

Four real rows (centre 30 letters shown):

```
Row 0    ...TCCTTGCTGGACAGATCCATCTGTGTGTGC...
         binds: AQR              does not: —            unknown: 121 proteins

Row 1    ...ACACAGCAGGGGGCGGGACCCTCCCCTCTG...
         binds: —                does not: DDX43        unknown: 121 proteins

Row 2    ...CTGGATGAAGATCGTTCTGGGGCTCGCCGC...
         binds: SRSF1, TRA2A, ZNF622                    unknown: 119 proteins

Row 136  ...TCGTGACCCCAGCCCCGCCGGGCCGACCCG...
         binds: PHF6             does not: DGCR8        unknown: 120 proteins
```

### 2.3 Three label states, not two

Every (sequence, protein) pair is **binds / does not bind / unknown**, and unknown dominates: a row carries information about **1.04 of 122** proteins on average.

Consequences: evaluation must be masked; standard multi-label metrics (Hamming loss, subset accuracy) are not computable; this is effectively **122 independent binary problems**.

### 2.4 Per-protein statistics (verified)

| Quantity | Value |
|---|---|
| Positives per protein | 506 – 2,000 |
| Negatives per protein | up to 1,651 |
| Labelled rows per protein | 1,012 – 3,651 |
| Class balance | ~55 / 45 |
| Rows with ≥2 positive labels | ~6,500 |
| Known negatives, total | 173,532 |

### 2.5 What "negative" means

Not a tested non-binder. eCLIP pulls down RNA bound to one protein; strong pile-ups are called **peaks** (the positives). Negatives are regions *not* called as peaks, chosen by whoever built the dataset. So a negative means **"no evidence of binding in this experiment"** — a region can look unbound because the RNA was lowly expressed or poorly covered.

Verified: negatives are **not** other proteins' sites (~1% overlap), and they are **compositionally different** from positives (mean GC 0.462 vs 0.528; positives GC-richer in 92 of 122 proteins).

The sampling procedure is undocumented and unrecoverable. This is the largest single unknown.

---

## 3. Diagnostics

### 3.1 Train/test leakage — severe *(new in v2)*

Method: index every offset of a random sample of rows; query all 361,180 rows. Detects overlap regardless of alignment. Hash collisions are negligible (<10⁻⁶ expected).

| Test | Result |
|---|---|
| Exact duplicate sequences | **0** |
| Reverse-complement duplicates | **0** |
| Rows sharing ≥150 nt with another row | **80.3%** |
| Rows sharing ≥300 nt with another row | **76.6%** |
| Median overlapping partners per affected row | 6 (max 306) |
| Rows overlapping a *different* protein's row | 73% |

The dataset is built from heavily overlapping genomic windows — expected, since RBP peaks cluster on the same transcripts. **A random row split places near-identical sequences in both train and test for roughly three-quarters of the data.**

Every number produced so far, including the in-house model's, is therefore unreliable, and the inflation is likely asymmetric: only the in-house model was trained on this split.

This becomes the highest-priority fix, and it substantially raises the value of recovering genomic coordinates, since grouping by locus is both easier and more correct than sequence clustering.

### 3.2 Split construction and loss — both confirmed problematic *(new in v2)*

**Stratification was a no-op.** Verified: `targets * masks` is *identical* to `targets`. Known negatives and unknowns both map to 0, so the 173,532 known negatives were invisible to the fold splitter. Folds were stratified on positives only, exactly as the reviewer suspected. Fix: construct folds from separate positive and known-negative indicators.

**The loss does not ignore unknowns — it trains them as negatives.** `masked_bce_with_soft_neg` has a correct mask-aware first term, then adds a second term pushing *every unknown label* toward zero, with `lambda_unknown = 1` (and `lambda_pos = 15`). Since unknowns are ~99% of entries, this is a large signal.

This is a defensible positive-unlabelled choice, but it was undocumented and it means **"joint training" and "unknowns-as-negatives" are confounded in the current model** — the same class of confound the reviewer identified in point 1. Hence the 2×2 design in §5.1.

*(Implementation note: a `criterion` object is constructed and passed into `train()`, which ignores it and calls `masked_bce_with_soft_neg` directly.)*

### 3.3 The GC confound

A predictor that does nothing but count G and C letters:

| Predictor | Mean AUROC |
|---|---|
| GC content alone | **0.729** |
| PrismNet (as run) | 0.619 |

GC content wins on 84 of 100 proteins. A model can score well on this benchmark by detecting composition rather than binding.

*Caveat added in v2:* these figures were computed on the leaky split and must be recomputed once §5.2 is done. The qualitative conclusion is unlikely to change — the GC gap is a property of how negatives were sampled, not of the split — but the numbers will move.

### 3.4 The existing PrismNet run is invalid

PrismNet's loader reads a **4-column** TSV and builds a **5-channel** input: four sequence channels plus one icSHAPE structure channel from column 4. Our TSV has 3 columns; the cached tensor is `(361180, 1, 101, 4)`. Pretrained `_pu_` weights trained *with* structure are being fed input *without* it.

Result: mean AUROC 0.619, median 0.611, and **19 of 100 proteins score below chance** (FUS 0.273, EWSR1 0.311, FXR1 0.343). Systematically inverted, not merely weak. These numbers will not be reported.

### 3.5 Coverage is not random

| | PrismNet covers | PrismNet skips |
|---|---|---|
| Count | 100 | 22 |
| Median positives available | 1,999 | 1,289 |
| Baseline difficulty (GC AUROC) | 0.729 | 0.704 |

It covers the well-studied, data-rich proteins; its average is mildly flattered by its own coverage choices.

---

## 4. Design decisions

### 4.1 Rebuild and retrain, rather than install legacy code

PrismNet requires Python 3.6 / PyTorch 1.1; DeepRiPe requires TensorFlow 1.x. Colab provides Python 3.12 / PyTorch 2.x and does not permit changing the Python version.

Reimplementing the architectures in modern PyTorch and training them on our data removes the dependency problem, gives genuine apples-to-apples inputs, and removes two confounds in the pretrained route: differently-defined negatives (unfair to them) and probable train/test overlap with ENCODE K562 (unfair to us).

**Cost:** we evaluate published *architectures*, not published *models*. This must be stated in every results table. Mitigation: match published hyperparameters where stated, report parameter counts and training curves, and run the fidelity checks in §9.

### 4.2 Sequence-only headline comparison

The in-house model uses only letters. PrismNet additionally wants RNA structure; DeepRiPe additionally wants gene-region annotation. Both are looked up by **genomic coordinate**, which the dataset lacks.

Sequence-only is the fair primary comparison regardless — extra inputs the in-house model never had would make a win uninterpretable. The coordinate-enabled version is a **secondary experiment** quantifying what that extra data is worth.

Coordinates are likely recoverable by aligning the 500 nt sequences to the genome (a 500-mer is essentially unique). Estimated half a day, no GPU. After §3.1, this is worth doing early: locus-grouped folds are the cleanest fix for leakage.

### 4.3 Which competitors, and why

Selection principle: **reimplement only configurations the original authors published.**

| Method | Native output | Sequence-only published? | Role |
|---|---|---|---|
| DeepRiPe | multi-label binary | Yes (paper ablates sequence-only — *to verify*) | **Core.** Also the multitask comparator |
| PrismNet | per-sequence binary | Yes — ships a `seq` mode | **Core.** Faithful sequence-only competitor |
| RBPNet | per-nucleotide count profile | **No binary mode exists** | **Exploratory only** |

RBPNet is demoted not arbitrarily but because it has no published binary-classification configuration; training an RBPNet-shaped network on peak labels would be an "RBPNet-inspired classifier." If count tracks and coordinates become available it can be restored. Reported separately and labelled as such.

### 4.4 Window size as a nested ablation

The 500 nt windows are peak-centred and symmetric, so 101 ⊂ 251 ⊂ 500 share a centre. Window size is a clean experimental axis.

Every model is **trained and tested at each window size** — no inference-time cropping of a 500 nt-trained model. The 101 nt setting is the competitors' native window; 500 nt is the in-house model's. Both are reported.

### 4.5 Build the yardstick before the comparison

Trivial baselines are built first, on the leakage-safe split, and prespecified (§6.2) so none is selected on test results.

---

## 5. Experimental design

### 5.1 The ablation grid

Because architecture, multitask learning and the PU loss term are mutually confounded in the current model:

| Config | Architecture | Training | Loss |
|---|---|---|---|
| A | In-house ResCNN | joint, 122 outputs | with unknown penalty *(as built)* |
| B | In-house ResCNN | joint, 122 outputs | masked only, no unknown penalty |
| C | In-house ResCNN | one model per protein | masked only |
| D | In-house ResCNN | one model per protein | with unknown penalty |
| E | DeepRiPe | joint (native) | native |
| F | PrismNet `seq` | per protein (native) | native |

A vs C isolates joint training. A vs B isolates the PU term. C vs F isolates architecture. A vs E compares two multitask approaches.

*(D is the least interesting cell — include only if budget allows; it completes the 2×2.)*

### 5.2 Leakage-safe splitting

1. Cluster sequences by shared exact subsequence (single-linkage on ≥100 nt shared content, using the index from §3.1).
2. Assign whole clusters to folds, stratified on **separate positive and known-negative counts per protein**.
3. **Acceptance criterion:** zero cross-fold row pairs sharing ≥150 nt. Verified and reported before any training.
4. If coordinates are recovered, group by locus/transcript instead — preferable and simpler.

Note that clustering may produce large components (one observed row had 306 partners), which could make folds unbalanced. If so, report component-size distribution and consider chromosome-level grouping once coordinates exist.

### 5.3 Pilot, before full execution

Eight prespecified proteins spanning baseline difficulty, data volume, and — deliberately — all with well-documented binding motifs, so the pilot also validates the motif-recovery check:

| Protein | Known motif | Current GC baseline | Positives |
|---|---|---|---|
| TARDBP | UG repeats | 0.537 | 2,000 |
| ELAVL1 | AU-rich | 0.538 | 1,999 |
| PTBP1 | CU-rich | 0.569 | 2,000 |
| IGF2BP2 | — | 0.582 | 2,000 |
| HNRNPC | poly-U | 0.680 | 516 |
| PUM2 | UGUANAUA | 0.710 | 2,000 |
| QKI | ACUAAY | 0.825 | 1,998 |
| RBFOX2 | UGCAUG | 0.841 | 1,999 |

The pilot calibrates the GPU budget, exercises every fidelity check, and validates the shuffle and motif controls before committing to the full grid.

---

## 6. Metrics

### 6.1 Primary

**Per-protein AUROC, macro-averaged, reported raw.** Interpretation: *pick a random binding site and a random non-site; AUROC is the probability the model ranks the binding site higher.* Rank-based, so models with different output scales remain comparable, and no threshold can be tuned.

**AUROC minus baseline is secondary and diagnostic only.** The reviewer is correct that it cancels in head-to-head comparisons on shared proteins. Its one remaining use is aggregating across *different* protein sets (§7), where centring reduces between-protein variance — reported as such, never as a primary result.

### 6.2 Prespecified baselines

Fixed before seeing any test results; **all are reported**, none selected post hoc:

1. Random (0.5 by construction)
2. GC content, logistic regression
3. k-mer logistic regression at k = 3
4. k-mer logistic regression at k = 6

Where a single "baseline" is needed for stratification, it is **#2 (GC)**, fixed in advance.

### 6.3 Controls

**Dinucleotide-preserving shuffle.** For each positive sequence, generate **10** Altschul–Erikson dinucleotide-preserving shuffles. Recompute AUROC using shuffled positives against real negatives, taking the median over shuffles. A composition-driven model scores unchanged; a motif-driven model collapses toward 0.5.

**Motif recovery.** For the eight pilot proteins, run motif discovery on each model's top-scoring sequences and compare to ATtRACT / CISBP-RNA. As the reviewer notes, the shuffle control alone proves order-sensitivity, not biological relevance — motif recovery is what connects the two, so it is load-bearing rather than optional.

### 6.4 Evaluation sets

Both reported:

- **Original**, for comparability with the existing work.
- **Composition-matched**, as sensitivity analysis: negatives resampled per protein to match the positives' GC distribution. If coordinates are recovered, additionally match on region type and expression/coverage.

Composition matching does not manufacture verified biological negatives; it bounds how much of the apparent signal is compositional.

### 6.5 Statistics

- Mean and median per-protein AUROC with **95% bootstrap CIs** (2,000 resamples, stratified within protein).
- **Paired differences** between models with CIs; Wilcoxon signed-rank as supporting evidence.
- **Effect sizes reported alongside every p-value** — matched-pairs rank-biserial correlation for paired tests.
- **Win counts are descriptive**, not a pass/fail criterion.
- Per-protein DeLong tests only where a specific protein is discussed, not as a systematic sweep.

### 6.6 Diagnostic analyses (budget permitting)

Performance vs. available training data per protein (tests the multitask hypothesis directly); difficulty-stratified results; learning curves at 25/50/100% of data; runtime, parameter count and number of models to maintain.

### 6.7 Excluded

| Metric | Why |
|---|---|
| AUPRC as headline | Advantage is imbalance handling; data is ~55/45. Secondary column only |
| Accuracy, F1, anything thresholded | Score scales differ enormously; the existing notebook tunes thresholds on the evaluation set |
| Hamming loss, subset accuracy | Need the full 122-label vector; we have 1.04 |
| Micro-averaging | Mixes score scales; data-rich proteins dominate |
| Model-agreement correlations, ensembles | Interesting but first to cut per review triage |
| Count of proteins above AUROC 0.8 | Arbitrary threshold; dropped per review |

---

## 7. Unequal protein coverage

Largely dissolves in the retrained design — we train for all 122 proteins. It applies only to the secondary pretrained-weights experiment.

1. **Never average across different protein sets.** A mean over 100 and a mean over 59 are different quantities.
2. **Compare pairwise on each pair's own overlap**; never compare one such row to another.
3. **Use paired differences**, so per-protein difficulty cancels.
4. **Report coverage as a column.** The in-house model covers 122/122 with one model — a genuine advantage that is otherwise invisible.
5. **Test for coverage bias**, as in §3.5.

---

## 8. Decision rules — prespecified

Thresholds fixed now, before any result. Where a value is provisional it is marked; the pilot may revise it *once*, before the full run, and any revision is recorded.

**Definitions**

- **Clear margin** — mean per-protein AUROC improvement **≥ 0.02**, with the 95% bootstrap CI on the mean paired difference excluding zero. *(Provisional; to be sanity-checked against pilot variance.)*
- **Hard proteins** — those whose prespecified GC baseline AUROC is **< 0.60** on the leakage-safe split. Under the current (leaky) evaluation this would be ~29 of 122; membership is re-derived after §5.2, the threshold is fixed.
- **Passes the shuffle control** — median AUROC with dinucleotide-shuffled positives **≤ 0.55**, and a drop of **≥ 0.10** from the real-data AUROC.
- **Leakage-safe** — zero cross-fold row pairs sharing ≥150 nt of exact sequence.

**The claim "the in-house approach outperforms existing methods" is supported only if all of:**

1. It beats every prespecified baseline by a clear margin, macro-averaged. *If not, nothing else matters.*
2. It beats DeepRiPe and PrismNet-seq by a clear margin in paired comparison, with CIs reported.
3. The advantage holds on the hard proteins, not only the easy ones.
4. The advantage holds at matched window size (both 101 and 500 nt).
5. It passes the shuffle control.
6. Config A or B beats config C or D — i.e. joint training contributes, rather than the architecture alone.

**Other outcomes, and what each means**

- *Comparable accuracy, but 122 proteins in one model and cheaper to train* — a legitimate positive result. Stated in advance so it is not retrofitted.
- *Wins on low-data proteins, ties elsewhere* — supports the multitask hypothesis specifically. Scientifically the most interesting outcome.
- *Gains vanish under the leakage-safe split* — then the headline finding is about evaluation methodology, and the deliverable is a benchmark critique. A valid outcome.
- *Nothing beats the trivial baselines* — the finding is about the dataset's negative sampling, with a recommendation for reconstruction. Also valid.

---

## 9. Pre-execution deliverables

Produced and circulated **before** any full-scale training run.

- [ ] **Frozen data manifest** — SHA-256 of each source file, row count, sample IDs, the 122-protein index mapping, encoding spec (ACGT one-hot, 500 nt, peak-centred).
- [ ] **Leakage report** — duplicate and overlap statistics (§3.1), cluster-size distribution, cross-fold overlap after splitting, against the §8 acceptance criterion.
- [ ] **Fold-balance report** — positives and known-negatives per protein per fold, computed from separate indicators.
- [ ] **Loss audit** — written confirmation of which loss terms each config uses and how unknowns are treated, per config.
- [ ] **Pilot results** — the eight proteins of §5.3, full pipeline, all controls.
- [ ] **Fidelity checks** — parameter count, layer summary and training curve for each reimplementation, against published figures where available.
- [ ] **GPU budget** — §10, refined by the pilot.
- [ ] **Output schema** — tidy tables, not row-ordered `.npy`:
  `sample_id, protein, fold, window, config_id, config_hash, score`
  plus a config registry mapping `config_id` to architecture, loss, hyperparameters and code commit.

---

## 10. GPU budget

Assumptions: Colab T4; in-house ResCNN ≈ 2–4 min/epoch at 500 nt, batch 256; 30 epochs; per-protein models train on ~3,650 rows each and are much cheaper individually but number 122.

| Run | Estimate |
|---|---|
| Joint config, 1 fold, 1 window | ~2 h |
| Per-protein config (122 models), 1 fold, 1 window | ~3 h |
| Full 122 proteins @ 101 nt, 5 folds, configs A/B/C/E/F | ~50 h |
| 500 nt, 3 folds, configs A/C/E | ~22 h |
| Pilot | ~5 h |
| **Total** | **~75 GPU-hours** |

Free Colab supplies roughly 3–4 h/day, implying 3–4 weeks of wall-clock. Recommended reductions in priority order: drop config D; 3 folds instead of 5 at 500 nt; run the window ablation on the pilot eight only. Colab Pro or a Technion GPU node would remove the constraint. The pilot will replace these estimates with measurements.

---

## 11. Priorities

Per review triage, in order:

1. Leakage-safe split (§5.2) — now the top item on measured evidence
2. Trivial baselines (§6.2)
3. Joint-vs-single-task ablation (§5.1)
4. DeepRiPe
5. PrismNet-seq as the faithful sequence-only competitor

First to cut: model-agreement correlations, ensembles, extensive per-protein significance testing, the AUROC>0.8 count. RBPNet stays exploratory throughout.

---

## 12. Open questions for the reviewer

1. **Leakage fix without coordinates.** Given that 76.6% of rows share ≥300 nt with another row, is single-linkage sequence clustering acceptable as the grouping criterion, or should coordinate recovery become a hard prerequisite? Clustering risks large components that make folds unbalanced; we would report the component-size distribution either way.

2. **The unknown-label penalty.** This wasn't in v1 and so wasn't in the review. Is the 2×2 grid in §5.1 the right way to handle it, or should the PU term be removed outright so that the in-house model is compared on the same loss as the competitors?

3. **Are the §8 thresholds right?** Specifically the 0.02 margin and the 0.60 hard-protein cutoff — both are judgement calls made without pilot variance estimates.

4. **Budget triage.** If ~75 GPU-hours is unavailable, which does more damage: dropping to 3 folds, or dropping the 500 nt arm entirely and running everything at the competitors' native 101 nt?

5. **Scope.** If the leakage-safe split collapses the in-house model's advantage, is pivoting to a benchmark-methodology report an acceptable deliverable for this course?

---

## Appendix — verified facts

Computed directly from the project files, not taken from documentation.

| Fact | Value |
|---|---|
| Rows | 361,180 |
| Proteins | 122 |
| Sequence | 500 nt, one-hot ACGT, peak-centred |
| `output_sequences.tsv` | centre 101 nt, row-aligned with the CSV |
| Cached PrismNet tensor | `(361180, 1, 101, 4)` — 4 channels; PrismNet needs 5 |
| Mean known labels per row | 1.04 of 122 |
| Mean positive labels per row | 0.56 |
| Rows with ≥2 positives | ~6,500 |
| Known negatives, total | 173,532 |
| Positives per protein | 506 – 2,000 |
| Labelled rows per protein | 1,012 – 3,651 |
| Exact duplicate sequences | 0 |
| Reverse-complement duplicates | 0 |
| Rows sharing ≥150 nt with another row | 80.3% |
| Rows sharing ≥300 nt with another row | 76.6% |
| Rows overlapping a different protein's row | 73% |
| `targets * masks` == `targets` | True — stratification ignored negatives |
| Unknown-label penalty | present, `lambda_unknown = 1`, `lambda_pos = 15` |
| Negatives that are another protein's positive | ~1% |
| Mean GC, positives / negatives | 0.528 / 0.462 |
| Proteins where positives are GC-richer | 92 of 122 |
| GC-only baseline, mean AUROC | 0.729 |
| PrismNet as run, mean AUROC | 0.619 |
| PrismNet below chance | 19 of 100 proteins |
| GC baseline beats PrismNet | 84 of 100 proteins |
| PrismNet coverage bias | covers median 1,999 positives; skips 1,289 |

*All AUROC figures above were computed on the leaky split and will be recomputed after §5.2.*
