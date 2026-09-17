# Validating an RBP-binding predictor against published methods

**Project plan — version 4, revised after third review**
Course project, Technion bioinformatics, winter 2026
16 Sep 2026

**Status:** approved for coordinate recovery, leakage-safe splitting and the development pilot. Full-grid approval pending the §9 deliverables, the mapping-retention report, frozen folds, the DeepRiPe supervision spec, and a measured pilot budget.

---

## 0. What changed in v4

All third-round corrections accepted. One was checked against the primary source and produced a finding that changes the DeepRiPe design.

| Review item | Response |
|---|---|
| Separate the scientific claims | **Accepted.** Four independent hypotheses, each with its own rule. §8 |
| Make A/B/C window-specific | **Accepted.** `Config@window` notation throughout |
| DeepRiPe grouping and loss ambiguity | **Accepted, and verified.** Grouping confirmed; our data collapses it. §4.3, §5.1 |
| Pilot must preserve joint training | **Accepted.** §5.3, budget revised |
| Coordinate-recovery acceptance criteria | **Accepted.** §4.2 |
| Prespecify CV prediction combination | **Accepted and frozen:** per-fold AUROC, then averaged. §6.5 |
| Calibration for A vs B | **Accepted.** Brier and log loss, penalty analysis only. §6.6 |
| IGF2BP2 has no documented motif | **Accepted.** Replaced with U2AF2. §5.3 |

**New finding.** DeepRiPe trains *several* multitask networks grouped by peak abundance — three for PAR-CLIP (`model-high/mid/low`), **five per cell line for eCLIP** (>10⁴, 7,000–10⁴, 4,000–7,000, 2,000–4,000, 1,000–2,000 peaks). Applying that rule to our data:

| DeepRiPe eCLIP bin | Our proteins |
|---|---|
| >10,000 | 0 |
| 7,000–10,000 | 0 |
| 4,000–7,000 | 0 |
| 2,000–4,000 | **57** |
| 1,000–2,000 | **43** |
| below their lowest bin (<1,000) | **22** |

Our dataset caps positives at 2,000 — 68 of 122 proteins sit exactly at the cap, and the full range is 506–2,000. DeepRiPe's grouping exists to absorb 10–100× differences in peak abundance; our data spans under 4×. **The heterogeneity the grouping was designed for has already been removed by the dataset's construction.** This makes a single 122-output network a defensible adaptation, but it remains an adaptation, and §4.3 now specifies two DeepRiPe configurations rather than one.

---

## 1. The problem

RNA-binding proteins (RBPs) attach to RNA at specific sites; predicting those sites from sequence is an established task with several published deep-learning solutions.

A teammate built a single **multi-label** network predicting all 122 proteins jointly, on the hypothesis that proteins share binding preferences and a joint model transfers knowledge between them. That teammate has left; there is no documentation beyond the code.

My role is **validation**. A negative result is acceptable, and per §11 a methodological pivot may be the stronger contribution.

**Novelty framing.** The in-house model's distinguishing features are (a) a residual CNN architecture, (b) a 500 nt window, (c) 122 proteins trained jointly, and (d) an unknown-as-negative penalty. These are mutually confounded in the submitted model. Joint training is *not* itself novel — DeepRiPe is multitask.

---

## 2. The data

### 2.1 Inventory

| File | Contents |
|---|---|
| `dataset_K562_multilabel_with_NEGs.csv` | 361,180 sequences × 122 protein labels. 724 MB |
| `intRBP ResCNN - for students.ipynb` | In-house model, training and evaluation code |
| `CNNMultiLabelResidual_20250812_123241.pth` | Trained weights, fold 0 only |
| `output_sequences.tsv` | Centre 101 nt, decoded — prepared for PrismNet |
| `out_tests/out/infer/*.probs` | PrismNet output, 100 of 122 proteins — invalid, §3.4 |

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

Every (sequence, protein) pair is **binds / does not bind / unknown**; unknown dominates at **1.04 of 122** known per row. Evaluation must be masked; standard multi-label metrics are not computable; this is effectively **122 independent binary problems**.

### 2.4 Per-protein statistics

| Quantity | Value |
|---|---|
| Positives per protein | 506 – 2,000 (68 proteins at the 2,000 cap) |
| Negatives per protein | up to 1,651 |
| Labelled rows per protein | 1,012 – 3,651 |
| Class balance | ~55 / 45 |
| Rows with ≥2 positive labels | ~6,500 |
| Known negatives, total | 173,532 |

### 2.5 What "negative" means

Not a tested non-binder. eCLIP pulls down RNA bound to one protein; strong pile-ups are called **peaks** (positives). Negatives are regions *not* called as peaks — meaning **"no evidence of binding in this experiment"**, which a region can satisfy merely by being lowly expressed or poorly covered.

Verified: negatives are **not** other proteins' sites (~1% overlap), and are compositionally different from positives (mean GC 0.462 vs 0.528; positives GC-richer in 92 of 122 proteins). The sampling procedure is undocumented and unrecoverable.

---

## 3. Diagnostics

### 3.1 Train/test leakage — severe

Index every offset of a random sample of rows; query all 361,180. Detects overlap regardless of alignment; expected hash collisions <10⁻⁶.

| Test | Result |
|---|---|
| Exact duplicate sequences | **0** |
| Reverse-complement duplicates | **0** |
| Rows sharing ≥150 nt with another row | **80.3%** |
| Rows sharing ≥300 nt with another row | **76.6%** |
| Median overlapping partners per affected row | 6 (max 306) |
| Rows overlapping a *different* protein's row | 73% |

**A random row split places near-identical sequences in both train and test for roughly three-quarters of the data.** Every number produced so far is unreliable, and inflation is likely asymmetric — only the in-house model was trained on this split.

The 306-partner row is plausibly a repeat or low-complexity region rather than one locus — exactly why sequence clustering is unsuitable as the primary grouping rule (§5.2).

### 3.2 Split construction and loss

**Stratification was a no-op.** `targets * masks` is *identical* to `targets`; the 173,532 known negatives were invisible to the fold splitter. Fix: build folds from separate positive and known-negative indicators.

**The loss trains unknowns as negatives.** `masked_bce_with_soft_neg` has a correct mask-aware first term, then adds a second pushing every unknown label toward zero, with `lambda_unknown = 1`, `lambda_pos = 15`.

This is an **unknown-as-negative penalty** (an unlabelled-negative regulariser), *not* a positive–unlabelled learning method — treating every unlabelled example as negative is not a valid PU risk estimator.

**Magnitude.** Both terms are mean-normalised over their own support, so "unknowns are 99% of entries" does not make the penalty large. At initialisation, BCE ≈ ln 2 everywhere:

- masked term ≈ 0.693 × (15 × 0.538 + 1 × 0.462) ≈ **5.9**
- unknown term ≈ 0.693 × 1 ≈ **0.69**

Roughly **8.5 : 1 in favour of the masked term**. It is not negligible either — a small persistent downward push on ~121 outputs per sample, and for those outputs the only signal they receive, so it plausibly shapes calibration while contributing little to total loss. Hence the calibration metrics in §6.6. Both components are logged per epoch.

*(A `criterion` object is constructed and passed into `train()`, which ignores it and calls `masked_bce_with_soft_neg` directly.)*

### 3.3 The GC confound

| Predictor | Mean AUROC |
|---|---|
| GC content alone | **0.729** |
| PrismNet (as run) | 0.619 |

GC wins on 84 of 100 proteins. Computed on the leaky split; to be recomputed after §5.2.

### 3.4 The PrismNet run is invalid — evidence chain

1. `tools/main.py` builds filenames as `identity = p_name + '_' + arch + '_' + mode`. Our files are `AATF_PrismNet_pu_…`, so **PrismNet recorded the runtime mode as `pu`**.
2. `prismnet/model/PrismNet.py`: `mode="pu"` → `n_features = 5`; `"seq"` → 4 with `forward` slicing `input[:,:,:,:4]`; `"str"` → 1.
3. First layer: `Conv2d(1, base_channel, kernel_size=(11, h_k), bn=True, same_padding=True)` — `pu` builds a width-5 kernel.
4. Our cached tensor is `(361180, 1, 101, 4)` — width 4.
5. `same_padding=True` means a width-5 kernel over width-4 input **pads rather than errors**, which is why the run completed with plausible output.
6. `main.py` sets `args.nstr = 1` when `mode == 'pu'`, driving `use_structure`. The 3-column TSV would have failed to parse a structure column; the cached `.npz` bypassed that path.

**Conclusion:** a structure-expecting model consumed structure-free input, silently. Mean AUROC 0.619; **19 of 100 proteins below chance** (FUS 0.273, EWSR1 0.311, FXR1 0.343).

**Residual check, required before discarding:** locate the checkpoints and read `conv.weight.shape` — `(base_channel, 1, 11, 5)` for `pu`, `(…, 11, 4)` for `seq`. Record filename and config. Models directory is empty; tracked as open.

### 3.5 Coverage is not random

| | PrismNet covers | PrismNet skips |
|---|---|---|
| Count | 100 | 22 |
| Median positives available | 1,999 | 1,289 |
| Baseline difficulty (GC AUROC) | 0.729 | 0.704 |

---

## 4. Design decisions

### 4.1 Rebuild and retrain, not legacy installs

PrismNet needs Python 3.6 / PyTorch 1.1; DeepRiPe needs TensorFlow 1.x. Colab provides Python 3.12 / PyTorch 2.x with no way to change the Python version.

Reimplementation removes the dependency problem, gives identical inputs, and removes two confounds of the pretrained route: differently-defined negatives, and probable overlap between our test set and their ENCODE K562 training data.

**Cost:** we evaluate published *architectures*, not published *models*. Stated in every results table; mitigated by §9 fidelity checks.

### 4.2 Coordinate recovery — prerequisite, with acceptance criteria

Align the 500 nt sequences to the human genome; retain uniquely-mapped rows with strand. Estimated half a day, no GPU.

**Because quarantining rows can introduce selection bias, the coordinate report must contain:**

- unique-mapping rate overall;
- **retention by protein and by positive/negative class**;
- **GC and repeat-content differences between retained and quarantined rows**;
- usable positives and negatives remaining per protein, against the §5.3 minimum;
- genome build and alignment-quality criteria (MAPQ threshold, mismatch allowance);
- explicit handling of **splice-junction sequences and multimappers**.

**Spliced alignments:** where a sequence maps across exons, overlap groups are built from **aligned exon blocks**, not from a single genomic bounding interval — a bounding interval would merge unrelated loci across a long intron.

After grouping, the §3.1 sequence-overlap audit is re-run as the final leakage check.

If retention is materially unequal across proteins or classes, that is reported as a limitation and the affected proteins are flagged, not silently dropped.

### 4.3 Competitors and their true native configurations

Principle: **reimplement only configurations the original authors published**, and label every departure an adaptation.

| Method | Native sequence window | Native training structure | Sequence-only published? | Coverage |
|---|---|---|---|---|
| DeepRiPe | **150 nt** (+250 nt region) | **5 networks per cell line**, binned by peak count | Yes — confirmed | ~150 RBPs, eCLIP K562+HepG2 |
| PrismNet | **101 nt** | one model per protein | Yes — ships a `seq` mode | 100 of our 122 |
| RBPNet | ~101 nt | per protein | **No binary mode exists** | own list |
| In-house | **500 nt** | one joint 122-output model | n/a | 122 of 122 |

**DeepRiPe grouping — two configurations.** Their binning absorbs 10–100× peak-abundance differences; our capped dataset spans under 4× and occupies only two of their five bins, with 22 proteins below their lowest. So:

- **E1 — single 122-output network**, masked-only loss, 150 nt. An **adaptation**, matched to B's output structure so that B vs E1 isolates architecture.
- **E2 — grouped networks**, following the published binning rule as it applies to our data (two populated bins; the 22 sub-1,000-positive proteins assigned to the lowest). The **faithful-as-possible recipe**, used for the pipeline comparison against A.

Both are labelled adaptations in every table, with the binning table from §0 reproduced so readers can see why.

**Supervision must be specified, not inherited.** "Native loss" is ambiguous, because DeepRiPe's original label construction did not use our three-state scheme. **Both E1 and E2 mask unknowns** — they do not treat them as negatives. This is stated explicitly rather than left implicit, and it is what makes B vs E1 a comparison of architecture rather than of supervision.

RBPNet remains **exploratory only**: it has no published binary-classification configuration. Restorable if count tracks and coordinates become available.

### 4.4 Three window experiments

Native windows are 101 / 150 / 500, so "only published configurations" and "a common length" cannot both hold.

**W1 — controlled-input method comparison @ 150 nt.** All models trained and tested at 150 nt. Named "method comparison", not "architecture comparison": W1 controls input length and (via §4.3) supervision, but models still differ in other respects. Non-native runs labelled adaptations.

**W2 — native-configuration comparison.** PrismNet@101, DeepRiPe(E2)@150, in-house A@500. Each at its intended operating point; inputs differ by design. Never presented as controlled.

**W3 — window curve.** In-house A/B/C at 101 / 251 / 500 — nested crops of the same peak centre. Isolates the long window's contribution to the in-house method. No competitor is run at 500 nt and called faithful.

**PrismNet@150 is an adaptation** and carries a fidelity check: a layer-by-layer diff and parameter count against PrismNet@101, confirming that only the input-dependent (flatten/dense) boundary differs.

### 4.5 Sequence-only for the headline

The in-house model uses only letters. With coordinates recovered, W2 may optionally give PrismNet its structure channel and DeepRiPe its region channel — reported as a separate "native inputs" row quantifying what the extra data is worth, never mixed into the sequence-only comparison.

---

## 5. Experimental design

### 5.1 Configurations

Notation is **`Config@window`** throughout. A bare config letter is never used in a claim.

| Config | Architecture | Training | Loss/supervision |
|---|---|---|---|
| **A** | In-house ResCNN | joint, 122 outputs | **with** unknown-as-negative penalty |
| **B** | In-house ResCNN | joint, 122 outputs | masked only |
| **C** | In-house ResCNN | one model per protein | masked only |
| **E1** | DeepRiPe | joint, 122 outputs *(adaptation)* | masked only |
| **E2** | DeepRiPe | grouped networks *(published rule)* | masked only |
| **F** | PrismNet `seq` | one model per protein | masked only (native) |

**A@500 is the submitted recipe.** A@150 and A@101 are adapted in-house configurations and are labelled as such.

**Valid comparisons**

- **B@150 vs C@150** — joint training, holding architecture, window and loss fixed.
- **A@150 vs B@150** — the unknown-as-negative penalty at the controlled window.
- **B@150 vs E1@150** — architecture, holding window, output structure and supervision fixed.
- **C@150 vs F@150** — architecture, per-protein training.
- **A@500 vs E2@150 vs F@101** — whole-pipeline comparison at native operating points (W2).
- **A@101 / A@251 / A@500** — window contribution.

**A vs C is not a valid isolation of multitask learning** and is never presented as one; it changes both training mode and loss.

**Config D dropped.** Reproducing the penalty per protein requires each single-protein model to see all 361,180 rows rather than ~3,650 — roughly two orders of magnitude more compute than C, and needed only for the training-mode × penalty interaction, which no hypothesis in §8 requires.

### 5.2 Leakage-safe splitting

**Primary — locus grouping:**

1. Map rows to unique genomic coordinates; retain uniquely-mapped rows.
2. Build connected components of **overlapping aligned exon blocks** (not bounding intervals); assign each component wholly to one fold.
3. Stratify on **separate positive and known-negative counts per protein**.
4. **Quarantine** ambiguous and unmapped rows, with the §4.2 bias report.
5. **Re-run the §3.1 overlap audit** on the resulting split.

**Acceptance criterion:** no original genomic interval overlaps across folds, confirmed by the re-audit. This is window-independent, unlike a nucleotide-count threshold.

**Fallback — sequence clustering**, only if coordinate recovery fails, and retained regardless as an independent audit. Single-linkage on shared substrings is *not* primary: repeats and low-complexity regions create giant transitive components that do not correspond to one locus. Component-size distribution reported either way.

**Gene/transcript grouping** answers the stricter question of generalisation to unseen *genes*. Optional sensitivity analysis only.

### 5.3 Development set and confirmatory set

Eight proteins, frozen now, spanning baseline difficulty and data volume, **all with unambiguous documented motifs**:

| Protein | Known motif | GC baseline (leaky) | Positives |
|---|---|---|---|
| TARDBP | UG repeats | 0.537 | 2,000 |
| ELAVL1 | AU-rich | 0.538 | 1,999 |
| U2AF2 | polypyrimidine tract (U-rich) | 0.546 | 2,000 |
| PTBP1 | CU-rich | 0.569 | 2,000 |
| HNRNPC | poly-U | 0.680 | 516 |
| PUM2 | UGUANAUA | 0.710 | 2,000 |
| QKI | ACUAAY | 0.825 | 1,998 |
| RBFOX2 | UGCAUG | 0.841 | 1,999 |

*v4 change:* IGF2BP2 replaced by **U2AF2**. IGF2BP2's motif is contested in the literature, which would have undermined the motif-recovery diagnostic; the polypyrimidine tract is about as unambiguous as RNA motifs get, and U2AF2 occupies similar baseline difficulty. Membership is frozen; the baseline values will be recomputed after resplitting but will not change membership.

**These eight are a development set.** They calibrate the budget, exercise every fidelity check, and validate the diagnostics — so anything they influence makes them contaminated for inference. **The primary confirmatory test therefore runs on the remaining 114 proteins; all-122 results are secondary.**

**The pilot preserves the joint-training setting.** For A, B, E1 and E2 the **full multitask model with all 122 outputs is trained**; only evaluation and tuning decisions are restricted to the eight development proteins. An eight-output model would misrepresent the compute, optimisation dynamics and transfer behaviour of a 122-output model. C and F are per-protein and independent, so their pilot legitimately trains only the eight.

### 5.4 Folds

**Three leakage-safe folds** for W1 and W2. For W3, one locked group-aware train/validation/test split with three training seeds, stated explicitly.

The in-house model is retrained under the same regime as every competitor. The existing fold-0 checkpoint is a historical reference only, never a comparison arm.

---

## 6. Metrics

### 6.1 Primary

**Per-protein AUROC, macro-averaged, reported raw.** Rank-based, so differing output scales remain comparable and no threshold can be tuned.

AUROC-minus-baseline is **secondary and diagnostic only** — it cancels in head-to-head comparisons on shared proteins. Its one use is aggregating across different protein sets (§7).

### 6.2 Prespecified baselines

Fixed before any test result; **all reported**, none selected post hoc: random (0.5); GC-content logistic regression; k-mer logistic regression at k = 3; k-mer logistic regression at k = 6. Where a single baseline is needed for stratification it is **GC**, fixed in advance.

### 6.3 Biological-validity diagnostics

Neither is a pass/fail gate.

**Dinucleotide-preserving shuffle** — ten Altschul–Erikson shuffles per positive; report the change in score distribution and in AUROC against real negatives, median over shuffles. Shuffled RNA carries no known binding label, so failure to collapse to 0.5 does not prove reliance on composition.

**Motif recovery** — for the eight development proteins, motif discovery on top-scoring sequences against ATtRACT / CISBP-RNA. Together these form the biological-validity evidence; neither alone suffices.

### 6.4 Evaluation sets

**Original**, for comparability; and **composition-matched** as sensitivity analysis — negatives resampled per protein to match positives' GC, and with coordinates also region type and expression/coverage. Matching bounds how much apparent signal is compositional; it does not manufacture verified biological negatives.

### 6.5 Cross-validation combination and uncertainty — frozen

**AUROC is computed per fold and then averaged across folds.** Out-of-fold predictions are **not** pooled: independently trained folds can have different score scales, and pooling would distort rankings. This rule is identical across every model and frozen before confirmatory evaluation.

**Uncertainty:**

- per-protein AUROC — bootstrap by resampling **genomic components** within that protein, never individual rows;
- macro mean and paired model differences — resample **proteins as paired units**;
- **all predictions from the same locus stay together** in every resample;
- 2,000 resamples; 95% CIs throughout.

**Effect sizes alongside every p-value** — matched-pairs rank-biserial correlation. Wilcoxon signed-rank as supporting evidence. **Win counts descriptive only.** Per-protein DeLong tests only where a specific protein is discussed.

### 6.6 Calibration — penalty analysis only

The unknown-as-negative penalty may affect probability calibration more than ranking, which AUROC cannot see. For **A@150 vs B@150** only, report **Brier score and log loss** on known positive/negative test pairs.

Secondary, and used only for the penalty analysis — never as a headline metric across unrelated methods, whose output scales are not comparable.

### 6.7 Other diagnostics (budget permitting)

Performance vs. available training data per protein; **GC difficulty analysed continuously**, not only by the <0.60 split; learning curves at 25/50/100%; runtime, parameter count, number of models to maintain.

### 6.8 Excluded

| Metric | Why |
|---|---|
| AUPRC as headline | Advantage is imbalance handling; data is ~55/45. Secondary column |
| Accuracy, F1, thresholded metrics | Score scales differ; the original notebook tunes thresholds on the evaluation set |
| Hamming loss, subset accuracy | Need the full 122-label vector; we have 1.04 |
| Micro-averaging | Mixes score scales; data-rich proteins dominate |
| Model-agreement correlations, ensembles | First to cut per triage |
| Count of proteins above AUROC 0.8 | Arbitrary threshold |

---

## 7. Unequal protein coverage

Largely dissolves in the retrained design — we train for all 122. Applies mainly to the secondary pretrained-weights experiment.

Never average across different protein sets; compare pairwise on each pair's own overlap; use paired differences so per-protein difficulty cancels; report coverage as a column; test for coverage bias as in §3.5.

---

## 8. Hypotheses and decision rules — frozen

**No rule below may be changed after examining comparative pilot performance.** Any change is recorded with justification; the development set is excluded from confirmatory analysis regardless (§5.3).

**Shared definitions**

- **Clear margin** — mean per-protein AUROC improvement **≥ 0.02**, with the full 95% CI on the mean paired difference reported.
- **Hard proteins** — prespecified GC baseline AUROC **< 0.60** on the leakage-safe split; descriptive cutoff, with GC difficulty **also analysed continuously**.
- **Advantage holds on hard proteins** — mean paired improvement **≥ 0.02** within the subgroup, **with CI reported**; the subgroup CI is *not* required to exclude zero.
- **Leakage-safe** — no original genomic interval overlaps across folds, confirmed by re-audit.

All rules below are evaluated on the **114 confirmatory proteins**.

### H1 — Predictive superiority

Two sub-claims, reported separately; neither implies the other.

- **H1a (submitted recipe, W2):** A@500 beats every prespecified baseline, and beats E2@150 and F@101, by a clear margin. Supports *"the submitted pipeline outperforms published methods at their intended operating points."*
- **H1b (controlled input, W1):** A@150 beats E1@150 and F@150 by a clear margin. Supports *"the in-house method outperforms competing methods at matched input length and supervision."*

If only one holds, only that one is claimed, and the qualification is stated in the abstract.

### H2 — Multitask benefit

**B@150 beats C@150 by a clear margin.** Supports *"joint training across proteins improves prediction, holding architecture, window and loss fixed."*

**Independent of H1.** A@500 could beat the competitors because of architecture, window or the penalty while H2 fails. In that case H1 may be supported and H2 is not, and the write-up says so explicitly rather than attributing the gain to joint learning.

### H3 — Penalty effect

**A@150 vs B@150.** Directional either way; reported with AUROC *and* the §6.6 calibration metrics, since the penalty may affect calibration more than ranking. Supports *"the unknown-as-negative penalty helps / hurts / is neutral for the joint model."*

### H4 — Window contribution

**A@101 vs A@251 vs A@500** (W3). Supports *"the 500 nt window contributes / does not contribute to the in-house method's performance."* In-house configs only; no competitor is extended to 500 nt and called faithful.

### Reported alongside, not as gates

W2 native-configuration results; the shuffle and motif diagnostics; composition-matched sensitivity; coverage.

### Other outcomes

- *Comparable accuracy, one model for 122 proteins, cheaper to train* — a legitimate positive result, stated in advance.
- *Wins on low-data proteins, ties elsewhere* — supports H2 specifically; scientifically the most interesting outcome.
- *Gains vanish under the leakage-safe split* — pivot to §11.
- *Nothing beats the trivial baselines* — the finding concerns negative sampling; pivot to §11.

---

## 9. Pre-execution deliverables

Circulated **before** any full-scale training run.

- [ ] **Frozen data manifest** — SHA-256 per source file, row count, sample IDs, 122-protein index mapping, encoding spec.
- [ ] **Coordinate / mapping-retention report** — every item in §4.2, including retention by protein and class, and GC/repeat differences between retained and quarantined rows.
- [ ] **Frozen folds** — component assignments, with the post-split §3.1 re-audit against the §8 criterion.
- [ ] **Fold-balance report** — positives and known-negatives per protein per fold, from separate indicators.
- [ ] **DeepRiPe supervision and configuration spec** — E1 vs E2, the bin assignment actually used, and explicit confirmation that both mask unknowns.
- [ ] **Loss audit** — per config, which terms are active and how unknowns are treated; both components logged per epoch with their measured ratio over training.
- [ ] **PrismNet checkpoint record** — exact filename, config, and `conv.weight.shape` per checkpoint (§3.4).
- [ ] **PrismNet@150 fidelity diff** — layer inventory and parameter count against PrismNet@101, confirming only the input-dependent layer differs.
- [ ] **Pilot results** — eight development proteins, full 122-output training for joint configs, all diagnostics.
- [ ] **Fidelity checks** — parameter count, layer summary, training curve per reimplementation; every non-native configuration labelled an adaptation.
- [ ] **Measured GPU budget** from the pilot.
- [ ] **Output schema** — tidy tables, not row-ordered `.npy`:
  `sample_id, protein, fold, window, config_id, config_hash, score`
  plus a config registry mapping `config_id` to architecture, loss, supervision, window and code commit.

---

## 10. GPU budget

Assumptions: Colab T4; in-house ResCNN ≈ 2–4 min/epoch at 500 nt, batch 256, 30 epochs; per-protein configs train 122 small models on ~3,650 rows each.

| Experiment | Configs | Regime | Estimate |
|---|---|---|---|
| **W1** controlled input @150 nt | A, B, C, E1, F | 3 folds | ~36 h |
| **W2** native configurations | F@101, E2@150, A@500 | 3 folds | ~21 h |
| **W3** window curve | A, B, C @ 101/251/500 | locked split, 1 seed | ~21 h |
| Development pilot | A, B, E1, E2 full 122-output; C, F on 8 proteins | 1 fold | ~8 h |
| **Total** | | | **~86 h** |

The pilot cost is driven by the §5.3 requirement that joint configs train all 122 outputs; an eight-output shortcut would be cheaper and invalid.

Free Colab supplies ~3–4 h/day, so this is 3–4 weeks of wall-clock. Reductions in priority order: W3 on development proteins only; W2 to one fold; drop B from W3. Colab Pro or a Technion GPU node removes the constraint. **These estimates will be replaced by pilot measurements before full-grid approval is sought.**

---

## 11. The methodology pivot

If the advantage collapses after removing leakage, the report becomes a reproducibility and benchmark-design result. It would quantify:

- performance under random vs. locus-grouped splitting;
- how inflation scales with train–test sequence overlap;
- the effect of treating unknowns as negatives;
- the effect of GC-matched evaluation;
- which conclusions from the original evaluation survive.

**Action item:** confirm with the course instructor that this satisfies the expected deliverable — sought now, not after the result is known.

---

## 12. Priorities

1. Coordinate recovery with the §4.2 retention report — prerequisite
2. Leakage-safe split and post-split audit (§5.2)
3. Trivial baselines (§6.2)
4. Development-set pilot (§5.3)
5. H2: B@150 vs C@150
6. DeepRiPe (E1, E2), then PrismNet-seq (F)

First to cut: model-agreement correlations, ensembles, extensive per-protein significance testing. RBPNet stays exploratory throughout.

---

## 13. Open items

| Item | Status |
|---|---|
| Negative sampling procedure | **Unknown**, unrecoverable. Largest remaining unknown |
| Genomic coordinates | Prerequisite. Recovery unattempted |
| PrismNet checkpoints | Models directory empty; needed for the §3.4 residual check |
| Original train/test split file | On the departed teammate's Drive; reproducible from seed, unconfirmed |
| Genome build | Unknown; two candidates, both quick to test |
| Reimplementation fidelity | Risk of under-training a competitor; mitigated by §9 |
| Compute budget | ~86 h against free-Colab capacity |
| Instructor sign-off on the §11 pivot | Being sought now |

---

## Appendix — verified facts

Computed from the project files or checked against primary sources.

| Fact | Value |
|---|---|
| Rows | 361,180 |
| Proteins | 122 |
| Sequence | 500 nt, one-hot ACGT, peak-centred, symmetric |
| Cached PrismNet tensor | `(361180, 1, 101, 4)` |
| PrismNet `pu` mode | `n_features = 5`; first conv `(11, 5)`, `same_padding=True` |
| PrismNet output filename mode field | `pu` — recorded by PrismNet itself |
| Mean known labels per row | 1.04 of 122 |
| Mean positive labels per row | 0.56 |
| Rows with ≥2 positives | ~6,500 |
| Known negatives, total | 173,532 |
| Positives per protein | 506 – 2,000; 68 proteins at the cap |
| Labelled rows per protein | 1,012 – 3,651 |
| Exact / reverse-complement duplicates | 0 / 0 |
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
| DeepRiPe training structure | **5 networks per cell line**, binned by peak count |
| Our proteins under DeepRiPe's bins | 57 in 2,000–4,000; 43 in 1,000–2,000; 22 below their lowest bin |
| DeepRiPe sequence-only ablation | Published — confirmed |

*All AUROC figures were computed on the leaky split and will be recomputed after §5.2.*

**Sources for external facts:** DeepRiPe — Ghanbari & Ohler, *Genome Research* 30:214 (https://genome.cshlp.org/content/30/2/214.full). PrismNet — source at https://github.com/kuixu/PrismNet (`tools/main.py`, `prismnet/model/PrismNet.py`).
