# Validating an RBP-binding predictor against published methods

**Project plan — version 3, revised after second review**
Course project, Technion bioinformatics, winter 2026
15 Sep 2026

**Status:** conditionally approved for coordinate recovery, split construction and the pilot. **Not** approved for the full training grid.

---

## 0. What changed in v3

All second-round corrections accepted. Two of the reviewer's factual challenges were checked against primary sources; both were correct, and one exposed a further error of mine.

| Review item | Response |
|---|---|
| A vs C does not isolate joint training | **Accepted — my error.** Relabelled; **B vs C** is the causal test. §5.1 |
| Config D is far more expensive than budgeted | **Accepted.** D dropped; cost rationale in §5.1 |
| "PU learning" is the wrong term | **Accepted.** Now "unknown-as-negative penalty". §3.2 |
| λ values don't describe effective contribution | **Accepted — and I had the direction wrong.** §3.2 |
| Coordinates as prerequisite; locus grouping; interval-based leakage criterion | **Accepted.** §4.2, §5.2 |
| Keep the penalty; two objects of study | **Accepted.** §5.1 |
| Shuffle control not a pass/fail condition | **Accepted.** Demoted to diagnostic. §6.3, §8 |
| Pilot proteins become a development set | **Accepted.** Confirmatory test on the other 114. §5.3, §8 |
| Preserve the 500 nt arm; reduce folds | **Accepted.** §5.4, §10 |
| DeepRiPe uses 150 nt, not 101 | **Confirmed against the paper — my error.** §4.3 |
| Bootstrap must resample loci and proteins | **Accepted.** §6.5 |
| Verify the PrismNet checkpoint before discarding | **Done — invalidation now evidenced.** §3.4 |

**Further correction, not raised in review and also mine:** v1 and v2 both stated DeepRiPe's eCLIP model covers ~59 RBPs. **59 is the PAR-CLIP model.** The eCLIP model covers ~150 RBPs across K562 and HepG2. DeepRiPe is therefore a far better comparator than I represented, and likely covers most of our 122 proteins.

---

## 1. The problem

RNA-binding proteins (RBPs) attach to RNA at specific sites; predicting those sites from sequence is an established task with several published deep-learning solutions.

A teammate built a single **multi-label** network predicting all 122 proteins jointly, on the hypothesis that proteins share binding preferences and a joint model transfers knowledge between them — especially to data-poor proteins. That teammate has left; there is no documentation beyond the code.

My role is **validation**. A negative result is an acceptable outcome, and per §11 a methodological pivot may be the stronger contribution.

**Novelty framing.** The in-house model's distinguishing features are (a) a residual CNN architecture, (b) a 500 nt window, (c) 122 proteins trained jointly, and (d) an unknown-as-negative penalty. These are mutually confounded in the submitted model; separating them is a core objective. Note that joint training is *not* itself novel — DeepRiPe is multitask.

---

## 2. The data

### 2.1 Inventory

| File | Contents |
|---|---|
| `dataset_K562_multilabel_with_NEGs.csv` | 361,180 sequences × 122 protein labels. 724 MB |
| `intRBP ResCNN - for students.ipynb` | In-house model, training and evaluation code |
| `CNNMultiLabelResidual_20250812_123241.pth` | Trained weights, fold 0 only |
| `output_sequences.tsv` | Centre 101 nt, decoded — prepared for PrismNet |
| `out_tests/out/infer/*.probs` | PrismNet output, 100 of 122 proteins — invalid, see §3.4 |

Source: ENCODE eCLIP, K562.

### 2.2 Format

500 RNA letters per row, one-hot encoded (2,000 bits, groups of 4, order ACGT), **peak-centred and symmetrically extended**, plus signed integer labels: `+7` = protein 7 binds; `−18` = protein 18 does not.

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

### 2.3 Three label states

Every (sequence, protein) pair is **binds / does not bind / unknown**, and unknown dominates: a row carries information about **1.04 of 122** proteins on average. Evaluation must be masked; standard multi-label metrics are not computable; this is effectively **122 independent binary problems**.

### 2.4 Per-protein statistics

| Quantity | Value |
|---|---|
| Positives per protein | 506 – 2,000 |
| Negatives per protein | up to 1,651 |
| Labelled rows per protein | 1,012 – 3,651 |
| Class balance | ~55 / 45 |
| Rows with ≥2 positive labels | ~6,500 |
| Known negatives, total | 173,532 |

### 2.5 What "negative" means

Not a tested non-binder. eCLIP pulls down RNA bound to one protein; strong pile-ups are called **peaks** (positives). Negatives are regions *not* called as peaks. A negative means **"no evidence of binding in this experiment"** — a region can look unbound because the RNA was lowly expressed or poorly covered.

Verified: negatives are **not** other proteins' sites (~1% overlap), and are compositionally different from positives (mean GC 0.462 vs 0.528; positives GC-richer in 92 of 122 proteins). The sampling procedure is undocumented and unrecoverable.

---

## 3. Diagnostics

### 3.1 Train/test leakage — severe

Method: index every offset of a random sample of rows; query all 361,180. Detects overlap regardless of alignment. Expected hash collisions <10⁻⁶.

| Test | Result |
|---|---|
| Exact duplicate sequences | **0** |
| Reverse-complement duplicates | **0** |
| Rows sharing ≥150 nt with another row | **80.3%** |
| Rows sharing ≥300 nt with another row | **76.6%** |
| Median overlapping partners per affected row | 6 (max 306) |
| Rows overlapping a *different* protein's row | 73% |

The dataset is built from heavily overlapping genomic windows, since RBP peaks cluster on the same transcripts. **A random row split places near-identical sequences in both train and test for roughly three-quarters of the data.** Every number produced so far is unreliable, and inflation is likely asymmetric — only the in-house model was trained on this split.

The 306-partner row is plausibly a repeat or low-complexity region rather than one locus, which is exactly the failure mode that makes sequence clustering unsuitable as the primary grouping rule (§5.2).

### 3.2 Split construction and loss

**Stratification was a no-op.** Verified: `targets * masks` is *identical* to `targets`. Known negatives and unknowns both map to 0, so the 173,532 known negatives were invisible to the fold splitter. Fix: build folds from separate positive and known-negative indicators.

**The loss trains unknowns as negatives.** `masked_bce_with_soft_neg` has a correct mask-aware first term, then adds a second pushing every unknown label toward zero, with `lambda_unknown = 1`, `lambda_pos = 15`.

**Terminology, corrected:** this is an **unknown-as-negative penalty** (equivalently, an unlabelled-negative regulariser). It is *not* a positive–unlabelled learning method — treating every unlabelled example as negative is not a statistically valid PU risk estimator, and v2's use of "PU" was wrong.

**Magnitude, corrected — v2 had this backwards.** Both terms are mean-normalised over their own support (`/masks.sum()` and `/unknown_mask.sum()`), so "unknowns are 99% of entries" does *not* make the penalty large. At initialisation, with BCE ≈ ln 2 everywhere:

- masked term ≈ 0.693 × (15 × 0.538 + 1 × 0.462) ≈ **5.9**
- unknown term ≈ 0.693 × 1 ≈ **0.69**

Roughly **8.5 : 1 in favour of the masked term**, driven by `lambda_pos = 15`. v2 called the penalty "a large signal"; that was unsupported.

It is not negligible either: it is a small persistent downward push on ~121 outputs per sample, and for those outputs it is the only signal they ever receive, so it plausibly shapes calibration and the decision surface while contributing little to total loss. **Both loss components are logged separately every epoch**, and A vs B (§5.1) settles the question empirically rather than by argument.

*(Implementation note: a `criterion` object is constructed and passed into `train()`, which ignores it and calls `masked_bce_with_soft_neg` directly.)*

### 3.3 The GC confound

| Predictor | Mean AUROC |
|---|---|
| GC content alone | **0.729** |
| PrismNet (as run) | 0.619 |

GC wins on 84 of 100 proteins. Computed on the leaky split; to be recomputed after §5.2. The qualitative conclusion should survive — the GC gap is a property of negative sampling, not of the split — but the numbers will move.

### 3.4 The PrismNet run is invalid — evidence chain

v2 asserted this from the input tensor alone, which the reviewer correctly noted is insufficient, since PrismNet has an official sequence-only mode. Verified against source:

1. `tools/main.py` builds output filenames as `identity = p_name + '_' + arch + '_' + mode`. Our files are `AATF_PrismNet_pu_…`, so **PrismNet itself recorded the runtime mode as `pu`**.
2. `prismnet/model/PrismNet.py`: `mode="pu"` → `n_features = 5`; `"seq"` → `4` with `forward` slicing `input[:,:,:,:4]`; `"str"` → `1` slicing `input[:,:,:,4:]`.
3. The first layer is `Conv2d(1, base_channel, kernel_size=(11, h_k), bn=True, same_padding=True)`, so `pu` builds a width-5 kernel.
4. Our cached tensor is `(361180, 1, 101, 4)` — width 4.
5. `same_padding=True` means a width-5 kernel over width-4 input **pads rather than errors**, which is why the run completed and produced plausible output.
6. `main.py` also sets `args.nstr = 1` when `mode == 'pu'`, which drives `use_structure` in the loader. The 3-column TSV would have failed to parse a structure column; the cached `.npz` bypassed that path.

**Conclusion:** a structure-expecting model consumed structure-free input, silently. Mean AUROC 0.619, **19 of 100 proteins below chance** (FUS 0.273, EWSR1 0.311, FXR1 0.343).

**Residual check, to complete before discarding:** locate the checkpoints and read `conv.weight.shape`, which is `(base_channel, 1, 11, 5)` for a `pu` model and `(…, 11, 4)` for `seq`. Record the exact filename and config alongside. The models directory in the shared folder is empty; this is tracked as an open item.

### 3.5 Coverage is not random

| | PrismNet covers | PrismNet skips |
|---|---|---|
| Count | 100 | 22 |
| Median positives available | 1,999 | 1,289 |
| Baseline difficulty (GC AUROC) | 0.729 | 0.704 |

It covers the well-studied, data-rich proteins; its average is mildly flattered.

---

## 4. Design decisions

### 4.1 Rebuild and retrain, not legacy installs

PrismNet needs Python 3.6 / PyTorch 1.1; DeepRiPe needs TensorFlow 1.x. Colab provides Python 3.12 / PyTorch 2.x with no way to change the Python version.

Reimplementing in modern PyTorch removes the dependency problem, gives identical inputs, and removes two confounds of the pretrained route: differently-defined negatives, and probable overlap between our test set and their ENCODE K562 training data.

**Cost:** we evaluate published *architectures*, not published *models*. Stated in every results table. Mitigated by matching published hyperparameters, reporting parameter counts and training curves, and the fidelity checks in §9.

### 4.2 Coordinate recovery is a prerequisite

Per review, coordinate recovery is now a **prerequisite for the confirmatory experiment**, not a bonus.

Recover by aligning the 500 nt sequences to the human genome (a 500-mer is essentially unique); retain uniquely-mapped rows with strand. Estimated half a day, no GPU. Risks: an older genome build (two candidates, both quick to test) or spliced rather than contiguous sequences (immediately detectable).

Coordinates also enable the structure and region-annotation inputs for the native-configuration comparison (§4.4), and region/expression matching for the composition-matched evaluation (§6.4).

### 4.3 Competitors, and their true native configurations

Selection principle: **reimplement only configurations the original authors published.**

| Method | Native sequence window | Native output | Sequence-only published? | Coverage | Role |
|---|---|---|---|---|---|
| DeepRiPe | **150 nt** (+250 nt region) | multi-label binary | **Yes — confirmed** | ~150 RBPs, eCLIP K562+HepG2 | **Core.** Multitask comparator |
| PrismNet | **101 nt** | per-sequence binary | Yes — ships a `seq` mode | 100 of our 122 | **Core.** Per-protein comparator |
| RBPNet | ~101 nt | per-nucleotide counts | **No binary mode exists** | own list | **Exploratory only** |
| In-house | **500 nt** | multi-label binary | n/a | 122 of 122 | Method under test |

*Corrections in v3:* DeepRiPe's window is 150 nt, not 101 — v2's claim that "101 nt is the competitors' native window" was wrong. And DeepRiPe's eCLIP coverage is ~150 RBPs; the 59 figure used in v1/v2 is the PAR-CLIP model.

DeepRiPe's sequence-only ablation is confirmed published: *"we trained the DeepRiPe model without using region type information as input."* The "to verify" flag is removed.

RBPNet remains exploratory because it has **no published binary-classification configuration** — a principled exclusion, not an arbitrary one. Restorable if count tracks and coordinates become available.

### 4.4 Two window experiments, not one

The three native windows are 101 / 150 / 500. "Only published configurations" and "every model at a common length" therefore cannot both hold. v2 conflated them. Split:

**Experiment W1 — controlled-input architecture comparison.** All models trained and tested at **150 nt**. Chosen because it is native for DeepRiPe, the core multitask comparator, and PrismNet's adaptation is a mechanical dense-layer resize. Every non-native run is labelled an **adaptation** in all tables.

**Experiment W2 — native-configuration comparison.** PrismNet @ 101, DeepRiPe @ 150, in-house @ 500, each as published. No adaptation, but inputs differ by design — reported as "each method at its intended operating point", never as a controlled comparison.

**Experiment W3 — window curve.** In-house configs A/B/C at 101 / 251 / 500, nested crops of the same peak centre. Isolates the contribution of the long window to the in-house method specifically. No competitor is run at 500 nt and called faithful.

### 4.5 Sequence-only for the headline

The in-house model uses only letters. With coordinates recovered, W2 can optionally give PrismNet its structure channel and DeepRiPe its region channel — reported as a separate "native inputs" row that quantifies what the extra data is worth, never mixed into the sequence-only comparison.

---

## 5. Experimental design

### 5.1 The ablation grid — relabelled

| Config | Architecture | Training | Loss |
|---|---|---|---|
| **A** | In-house ResCNN | joint, 122 outputs | with unknown-as-negative penalty *(as submitted)* |
| **B** | In-house ResCNN | joint, 122 outputs | masked only |
| **C** | In-house ResCNN | one model per protein | masked only |
| **E** | DeepRiPe | joint (native) | native |
| **F** | PrismNet `seq` | per protein (native) | native |

**Valid comparisons:**

- **B vs C — the clean causal test of joint learning**, holding loss fixed at masked-only. This is the multitask claim.
- **A vs B** — effect of the unknown-as-negative penalty under joint training.
- **C vs F** — architecture, holding training mode fixed.
- **A vs E** — two multitask approaches.
- **A** alone — does the submitted recipe work on a leakage-safe split?

**A vs C is not a valid isolation of multitask learning** and will not be presented as one; it changes both training mode and loss. v2 claimed otherwise; that was an error.

**Config D dropped.** Reproducing the unknown penalty per protein requires each single-protein model to see all 361,180 rows rather than ~3,650 — roughly two orders of magnitude more compute than C. D is needed only to estimate the interaction between training mode and penalty, which is not required for the core B-vs-C conclusion.

**Two objects of study, kept separate:** *(i)* does the teammate's submitted recipe (A) work when retrained on a leakage-safe split; *(ii)* does joint learning itself help when unknowns are properly masked (B vs C). The penalty is retained rather than deleted, so *(i)* remains answerable.

### 5.2 Leakage-safe splitting

**Primary — locus grouping (requires §4.2):**

1. Map rows to unique genomic coordinates; retain uniquely-mapped rows.
2. Build connected components of **overlapping 500 nt genomic intervals**; assign each component wholly to one fold.
3. Stratify assignment on **separate positive and known-negative counts per protein**.
4. **Quarantine** ambiguous and unmapped rows — excluded from the confirmatory analysis, reported as a count.
5. **Re-run the §3.1 sequence-overlap audit** on the resulting split to confirm the leak is actually gone.

**Acceptance criterion:** no original genomic interval overlaps across folds. This replaces v2's "zero cross-fold sharing of ≥150 nt", which the reviewer correctly noted is both window-dependent and insufficient for a 101 nt experiment.

**Fallback — sequence clustering**, used only if coordinate recovery fails, and retained regardless as an independent leakage audit. Single-linkage on shared substrings is *not* the primary rule: repeats and low-complexity regions create giant transitive components that do not correspond to one locus, consistent with the 306-partner row observed in §3.1. Component-size distribution reported either way.

**Gene/transcript grouping** answers a stricter and different question — generalisation to unseen *genes* rather than unseen *loci*. Optional sensitivity analysis only.

### 5.3 Development set and confirmatory set

Eight proteins, prespecified, spanning baseline difficulty and data volume, all with documented binding motifs:

| Protein | Known motif | GC baseline (leaky) | Positives |
|---|---|---|---|
| TARDBP | UG repeats | 0.537 | 2,000 |
| ELAVL1 | AU-rich | 0.538 | 1,999 |
| PTBP1 | CU-rich | 0.569 | 2,000 |
| IGF2BP2 | — | 0.582 | 2,000 |
| HNRNPC | poly-U | 0.680 | 516 |
| PUM2 | UGUANAUA | 0.710 | 2,000 |
| QKI | ACUAAY | 0.825 | 1,998 |
| RBFOX2 | UGCAUG | 0.841 | 1,999 |

These eight are a **development set**. They calibrate the GPU budget, exercise every fidelity check, and validate the motif and shuffle diagnostics — and anything they influence (thresholds, architecture choices, hyperparameters) makes them contaminated for inference.

**Therefore the primary confirmatory test runs on the remaining 114 proteins. All-122 results are reported as secondary.** This follows the reviewer's first option rather than attempting to freeze every rule before looking, since it is robust to accidental contamination and costs nothing.

### 5.4 Folds

**Three leakage-safe folds** for the core comparison. Where a fold-based design is too expensive (the window curve), one locked group-aware train/validation/test split with three training seeds, stated explicitly per experiment.

The in-house model is retrained under the same regime as every competitor. The existing fold-0 checkpoint is used only as a historical reference point, never as a comparison arm.

---

## 6. Metrics

### 6.1 Primary

**Per-protein AUROC, macro-averaged, reported raw.** *Pick a random binding site and a random non-site; AUROC is the probability the model ranks the binding site higher.* Rank-based, so differing output scales remain comparable and no threshold can be tuned.

AUROC-minus-baseline is **secondary and diagnostic only** — it cancels in head-to-head comparisons on shared proteins. Its one use is aggregating across different protein sets (§7).

### 6.2 Prespecified baselines

Fixed before any test result; **all reported**, none selected post hoc:

1. Random (0.5)
2. GC content, logistic regression
3. k-mer logistic regression, k = 3
4. k-mer logistic regression, k = 6

Where a single baseline is needed for stratification it is **#2 (GC)**, fixed in advance.

### 6.3 Biological-validity diagnostics

Neither is a pass/fail gate.

**Dinucleotide-preserving shuffle.** Ten Altschul–Erikson shuffles per positive sequence; report the change in score distribution and in AUROC against real negatives, median over shuffles. Reported as evidence, not a criterion: shuffled RNA carries no known binding label, and failure to collapse to 0.5 does not prove a model relies only on composition.

**Motif recovery.** For the eight development proteins, run motif discovery on top-scoring sequences and compare to ATtRACT / CISBP-RNA. Together with the shuffle result this forms the biological-validity evidence; neither alone is sufficient.

### 6.4 Evaluation sets

- **Original**, for comparability with existing work.
- **Composition-matched**, as sensitivity analysis: negatives resampled per protein to match positives' GC distribution; with coordinates, additionally matched on region type and expression/coverage.

Composition matching bounds how much apparent signal is compositional. It does not manufacture verified biological negatives.

### 6.5 Statistics — corrected

- **Within-protein AUROC uncertainty:** bootstrap at **locus/component level**, not row level. Rows from one locus are correlated; row-level resampling understates uncertainty.
- **Macro mean and paired model differences:** resample **proteins as paired units**.
- 2,000 resamples; 95% CIs reported throughout.
- **Effect sizes alongside every p-value** — matched-pairs rank-biserial correlation for paired tests.
- Wilcoxon signed-rank as supporting evidence; **win counts descriptive only**.
- Per-protein DeLong tests only where a specific protein is discussed.

### 6.6 Diagnostic analyses (budget permitting)

Performance vs. available training data per protein (tests the multitask hypothesis directly); **GC difficulty analysed continuously**, not only by the <0.60 split; learning curves at 25/50/100%; runtime, parameter count, number of models to maintain.

### 6.7 Excluded

| Metric | Why |
|---|---|
| AUPRC as headline | Advantage is imbalance handling; data is ~55/45. Secondary column |
| Accuracy, F1, anything thresholded | Score scales differ enormously; the original notebook tunes thresholds on the evaluation set |
| Hamming loss, subset accuracy | Need the full 122-label vector; we have 1.04 |
| Micro-averaging | Mixes score scales; data-rich proteins dominate |
| Model-agreement correlations, ensembles | First to cut per triage |
| Count of proteins above AUROC 0.8 | Arbitrary threshold; dropped |

---

## 7. Unequal protein coverage

Largely dissolves in the retrained design — we train for all 122. Applies mainly to the secondary pretrained-weights experiment.

1. Never average across different protein sets.
2. Compare pairwise on each pair's own overlap; never compare one such row to another.
3. Use paired differences, so per-protein difficulty cancels.
4. Report coverage as a column. The in-house model covers 122/122 with one model.
5. Test for coverage bias, as in §3.5.

---

## 8. Decision rules — frozen

Fixed now. **No rule below may be changed after examining comparative pilot performance.** If any is changed, the change is recorded with its justification and the development set is already excluded from the confirmatory analysis (§5.3).

**Definitions**

- **Clear margin** — mean per-protein AUROC improvement **≥ 0.02**, with the full 95% CI on the mean paired difference reported.
- **Hard proteins** — prespecified GC baseline AUROC **< 0.60** on the leakage-safe split. Descriptive cutoff; GC difficulty is **also analysed continuously**, since the subgroup may become small after resplitting.
- **Advantage holds on hard proteins** — mean paired improvement **≥ 0.02** within the subgroup, **with its CI reported**. The subgroup CI is *not* required to exclude zero, as the subgroup may be small.
- **Leakage-safe** — no original genomic interval overlaps across folds; confirmed by re-running the §3.1 audit.

**The claim "the in-house approach outperforms existing methods" is supported only if all of:**

1. Config A beats every prespecified baseline by a clear margin on the 114 confirmatory proteins. *If not, nothing else matters.*
2. Config A beats DeepRiPe (E) and PrismNet-seq (F) by a clear margin in paired comparison under **W1**, the controlled-input experiment, with CIs.
3. The advantage holds on hard proteins, per the definition above.
4. **B beats C by a clear margin** — joint learning contributes, not the architecture alone.

**Reported alongside, not as gates:** W2 native-configuration results; the W3 window curve; the shuffle and motif diagnostics; A vs B for the penalty's effect.

**Other outcomes**

- *Comparable accuracy, one model for 122 proteins, cheaper to train* — a legitimate positive result, stated in advance so it is not retrofitted.
- *Wins on low-data proteins, ties elsewhere* — supports the multitask hypothesis specifically; scientifically the most interesting outcome.
- *Gains vanish under the leakage-safe split* — pivot to §11.
- *Nothing beats the trivial baselines* — the finding concerns negative sampling; pivot to §11.

---

## 9. Pre-execution deliverables

Circulated **before** any full-scale training run.

- [ ] **Frozen data manifest** — SHA-256 per source file, row count, sample IDs, 122-protein index mapping, encoding spec.
- [ ] **Coordinate recovery report** — genome build, unique-mapping rate, strand distribution, quarantined row count.
- [ ] **Leakage report** — §3.1 statistics, component-size distribution, and the post-split re-audit against the §8 criterion.
- [ ] **Fold-balance report** — positives and known-negatives per protein per fold, from separate indicators.
- [ ] **Loss audit** — per config, which terms are active and how unknowns are treated; both loss components logged per epoch with their measured ratio over training.
- [ ] **PrismNet checkpoint record** — exact filename, config, and `conv.weight.shape` for each checkpoint used (§3.4).
- [ ] **Pilot results** — the eight development proteins, full pipeline, all diagnostics.
- [ ] **Fidelity checks** — parameter count, layer summary, training curve per reimplementation, against published figures where available; every non-native configuration labelled an adaptation.
- [ ] **GPU budget**, refined by the pilot.
- [ ] **Output schema** — tidy tables, not row-ordered `.npy`:
  `sample_id, protein, fold, window, config_id, config_hash, score`
  plus a config registry mapping `config_id` to architecture, loss, hyperparameters, window and code commit.

---

## 10. GPU budget

Assumptions: Colab T4; in-house ResCNN ≈ 2–4 min/epoch at 500 nt, batch 256, 30 epochs; per-protein configs train 122 small models on ~3,650 rows each.

| Experiment | Configs | Regime | Estimate |
|---|---|---|---|
| **W1** controlled input @ 150 nt | A, B, C, E, F | 3 folds | ~36 h |
| **W2** native configurations | PrismNet@101, DeepRiPe@150, in-house@500 | 3 folds | ~21 h |
| **W3** window curve | A, B, C @ 101/251/500 | locked split, 1 seed | ~21 h |
| Development set / pilot | all | — | ~6 h |
| **Total** | | | **~84 h** |

Higher than v2's estimate because the design grew — dropping D saved less than splitting W1/W2/W3 cost. Free Colab supplies ~3–4 h/day, so this is 3–4 weeks of wall-clock.

Reductions in priority order: W3 on the development proteins only; W2 to one fold; drop config B from W3. Colab Pro or a Technion GPU node removes the constraint. The pilot replaces these estimates with measurements.

---

## 11. The methodology pivot

If the advantage collapses after removing leakage, the report becomes a reproducibility and benchmark-design result rather than a model comparison. Per review this is scientifically defensible and may be the stronger contribution. It would quantify:

- performance under random vs. locus-grouped splitting;
- how inflation scales with the amount of sequence overlap between train and test;
- the effect of treating unknowns as negatives;
- the effect of GC-matched evaluation;
- which conclusions from the original evaluation survive.

**Action item:** confirm with the course instructor that this satisfies the expected deliverable.

---

## 12. Priorities

1. Coordinate recovery (§4.2) — now a prerequisite
2. Leakage-safe split and post-split audit (§5.2)
3. Trivial baselines (§6.2)
4. Development-set pilot (§5.3)
5. B vs C joint-vs-single ablation (§5.1)
6. DeepRiPe (E), then PrismNet-seq (F)

First to cut: model-agreement correlations, ensembles, extensive per-protein significance testing. RBPNet stays exploratory throughout.

---

## 13. Open items

| Item | Status |
|---|---|
| Negative sampling procedure | **Unknown**, unrecoverable. Largest remaining unknown |
| Genomic coordinates | Now a prerequisite. Recovery unattempted |
| PrismNet checkpoints | Models directory empty; needed for the §3.4 residual check |
| Original train/test split file | On the departed teammate's Drive; reproducible from seed, unconfirmed |
| Genome build | Unknown; two candidates, both quick to test |
| Reimplementation fidelity | Risk of under-training a competitor; mitigated by §9 |
| Compute budget | ~84 h against free-Colab capacity |
| Instructor sign-off on the §11 pivot | Not yet sought |

---

## Appendix — verified facts

Computed directly from the project files or checked against primary sources.

| Fact | Value |
|---|---|
| Rows | 361,180 |
| Proteins | 122 |
| Sequence | 500 nt, one-hot ACGT, peak-centred, symmetric |
| `output_sequences.tsv` | centre 101 nt, row-aligned with the CSV |
| Cached PrismNet tensor | `(361180, 1, 101, 4)` |
| PrismNet `pu` mode | `n_features = 5`; first conv kernel `(11, 5)`, `same_padding=True` |
| PrismNet output filename mode field | `pu` — recorded by PrismNet itself |
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
| Unknown penalty, loss ratio at init | masked : unknown ≈ 8.5 : 1 |
| Negatives that are another protein's positive | ~1% |
| Mean GC, positives / negatives | 0.528 / 0.462 |
| Proteins where positives are GC-richer | 92 of 122 |
| GC-only baseline, mean AUROC | 0.729 |
| PrismNet as run, mean AUROC | 0.619 |
| PrismNet below chance | 19 of 100 proteins |
| GC baseline beats PrismNet | 84 of 100 proteins |
| DeepRiPe sequence window | **150 nt** (+250 nt region) |
| DeepRiPe eCLIP coverage | **~150 RBPs**, K562 + HepG2 (59 is the PAR-CLIP model) |
| DeepRiPe sequence-only ablation | Published — confirmed |

*All AUROC figures were computed on the leaky split and will be recomputed after §5.2.*

**Sources for external facts:** DeepRiPe — Ghanbari & Ohler, *Genome Research* 30:214 (https://genome.cshlp.org/content/30/2/214.full). PrismNet — source code at https://github.com/kuixu/PrismNet (`tools/main.py`, `prismnet/model/PrismNet.py`).
