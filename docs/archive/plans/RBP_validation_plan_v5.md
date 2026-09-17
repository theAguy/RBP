# Validating an RBP-binding predictor against published methods

**Project plan — version 5, revised after fourth review**
Course project, Technion bioinformatics, winter 2026
16 Sep 2026

**Status:** approved for coordinate recovery, leakage-safe splitting and the development pilot. **The next gate is empirical, not editorial:** mapping retention, frozen fold composition, post-split leakage audit, exact E1/E2 specifications, pilot learning curves and measured runtime.

---

## 0. What changed in v5

All seven corrections accepted. Correction 1 was a genuine arithmetic error and is fixed below.

| Review item | Response |
|---|---|
| DeepRiPe bin counts internally inconsistent | **Confirmed — my error.** Recomputed with explicit boundaries; §0.1 |
| H1b does not match supervision | **Accepted.** Split into matched-supervision and common-window forms; §8 |
| E2 is not one 122-output model | **Accepted.** Wording corrected; §4.3, §5.3 |
| Retention acceptance threshold missing | **Accepted.** §4.2 now specifies all five; §5.3 defines the minimum |
| Decision rules too loose | **Accepted.** CI lower bound >0 for H1/H2; equivalence intervals for H3/H4; §8 |
| W3 seed contradiction; B/C curves unjustified | **Accepted.** 3 seeds; confirmatory W3 restricted to A; §5.4, §10 |
| H1a wording too broad | **Accepted.** Qualified in abstract, tables and §8 |

**Budget falls to ~80 h** (from 86), because restricting confirmatory W3 to config A more than offsets moving to three seeds.

### 0.1 Corrected bin counts

v4 stated that 68 proteins have exactly 2,000 positives while placing only 57 in the 2,000–4,000 bin. Both could not be true. Recomputed:

| Count | Proteins |
|---|---|
| n = 2,000 exactly | **57** |
| n = 1,999 | **11** |
| n ≥ 1,999 | 68 |

v4's "68 proteins at the 2,000 cap" conflated the 57 at exactly 2,000 with 11 sitting one below. **No protein exceeds 2,000.** The range is 506–2,000.

**Bin boundaries, frozen before E2 runs:**

| Interval | Our proteins |
|---|---|
| n > 10,000 | 0 |
| 7,000 < n ≤ 10,000 | 0 |
| 4,000 < n ≤ 7,000 | 0 |
| 2,000 < n ≤ 4,000 | 0 |
| **n = 2,000** | **57** |
| **1,000 ≤ n < 2,000** | **43** |
| **n < 1,000** | **22** |
| Total | **122** |

DeepRiPe's grouping absorbs 10–100× differences in peak abundance; our capped dataset spans under 4×, occupies one boundary value and one interval, and puts 22 proteins below their lowest bin. The heterogeneity the grouping exists for has already been removed by the dataset's construction.

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
| Positives per protein | 506 – 2,000; **57 at exactly 2,000**, 11 at 1,999, none above |
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

This is an **unknown-as-negative penalty** (an unlabelled-negative regulariser), *not* a positive–unlabelled learning method.

**Magnitude.** Both terms are mean-normalised over their own support. At initialisation, BCE ≈ ln 2 everywhere:

- masked term ≈ 0.693 × (15 × 0.538 + 1 × 0.462) ≈ **5.9**
- unknown term ≈ 0.693 × 1 ≈ **0.69**

Roughly **8.5 : 1 in favour of the masked term**. Not negligible either — a small persistent downward push on ~121 outputs per sample, and for those outputs the only signal they receive, so it plausibly shapes calibration while contributing little to total loss. Hence §6.6. Both components logged per epoch.

### 3.3 The GC confound

| Predictor | Mean AUROC |
|---|---|
| GC content alone | **0.729** |
| PrismNet (as run) | 0.619 |

GC wins on 84 of 100 proteins. Computed on the leaky split; to be recomputed after §5.2.

### 3.4 The PrismNet run is invalid — evidence chain

1. `tools/main.py` builds filenames as `identity = p_name + '_' + arch + '_' + mode`. Our files are `AATF_PrismNet_pu_…`, so **PrismNet recorded the runtime mode as `pu`**.
2. `prismnet/model/PrismNet.py`: `mode="pu"` → `n_features = 5`; `"seq"` → 4 with `forward` slicing `input[:,:,:,:4]`.
3. First layer: `Conv2d(1, base_channel, kernel_size=(11, h_k), bn=True, same_padding=True)` — `pu` builds a width-5 kernel.
4. Our cached tensor is `(361180, 1, 101, 4)` — width 4.
5. `same_padding=True` means a width-5 kernel over width-4 input **pads rather than errors**.
6. `main.py` sets `args.nstr = 1` when `mode == 'pu'`, driving `use_structure`; the cached `.npz` bypassed the TSV parse that would have failed.

**Conclusion:** a structure-expecting model consumed structure-free input, silently. Mean AUROC 0.619; **19 of 100 proteins below chance**.

**Residual check, required before discarding:** read `conv.weight.shape` from the checkpoints — `(base_channel, 1, 11, 5)` for `pu`, `(…, 11, 4)` for `seq`. Models directory is empty; tracked as open.

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

**Cost:** we evaluate published *architectures* as **our retrained implementations**, not the authors' released models. This qualification appears in every results table and in the abstract (§8).

### 4.2 Coordinate recovery — prerequisite, with acceptance criteria

Align the 500 nt sequences to the human genome; retain uniquely-mapped rows with strand. Estimated half a day, no GPU.

**Report contents (all mandatory):**

- unique-mapping rate overall;
- **retention by protein and by positive/negative class**;
- **GC and repeat-content differences between retained and quarantined rows**;
- usable positives and negatives remaining per protein per fold, against the §5.3 minimum;
- genome build and alignment-quality criteria (MAPQ threshold, mismatch allowance);
- explicit handling of **splice-junction sequences and multimappers**.

**Acceptance thresholds, frozen before mapping:**

| Criterion | Threshold | If not met |
|---|---|---|
| Overall unique-mapping rate | ≥ 80% | 60–80%: proceed with documented caveat. <60%: stop; fall back to §5.2 sequence clustering |
| Positive-vs-negative retention gap | ≤ 5 percentage points | Flag as a potential new confound; report retention-stratified sensitivity analysis |
| Per-protein retention | ≥ 70% | Protein flagged in the report; eligibility decided by the §5.3 minimum, not by retention alone |

**Spliced alignments:** where a sequence maps across exons, overlap groups are built from **aligned exon blocks**, not a genomic bounding interval — a bounding interval would merge unrelated loci across a long intron.

After grouping, the §3.1 sequence-overlap audit is re-run as the final leakage check.

Proteins are **never silently excluded after seeing retention.** Exclusions are reported with their characteristics (positives, GC baseline, retention rate) plus the sensitivity analysis in §5.3.

### 4.3 Competitors and their true native configurations

Principle: **reimplement only configurations the original authors published**, and label every departure an adaptation.

| Method | Native sequence window | Native training structure | Sequence-only published? | Coverage |
|---|---|---|---|---|
| DeepRiPe | **150 nt** (+250 nt region) | **5 networks per cell line**, binned by peak count | Yes — confirmed | ~150 RBPs, eCLIP K562+HepG2 |
| PrismNet | **101 nt** | one model per protein | Yes — ships a `seq` mode | 100 of our 122 |
| RBPNet | ~101 nt | per protein | **No binary mode exists** | own list |
| In-house | **500 nt** | one joint 122-output model | n/a | 122 of 122 |

**Two DeepRiPe configurations:**

- **E1 — a single 122-output network**, masked-only supervision, 150 nt. An **adaptation**, matched to B's output structure so B@150 vs E1@150 isolates architecture. **One model.**
- **E2 — grouped networks**, applying the published binning rule to our data. Given §0.1, this yields **two networks**: `high` (n = 2,000) covering **57** proteins, and `low` (n < 2,000) covering **65** proteins (43 in 1,000–2,000 plus the 22 below DeepRiPe's lowest bin, assigned down). The **faithful-as-possible recipe**, used against A@500 in W2. **Two models, jointly covering all 122 proteins** — not one 122-output model.

Both are adaptations, with the §0.1 table reproduced so readers see why.

**Supervision is specified, not inherited.** "Native loss" is undefined against our three-state labels. **E1 and E2 both mask unknowns**; they do not treat them as negatives. This is what makes B@150 vs E1@150 a comparison of architecture rather than of supervision.

RBPNet remains **exploratory only**: no published binary-classification configuration exists.

### 4.4 Three window experiments

Native windows are 101 / 150 / 500, so "only published configurations" and "a common length" cannot both hold.

**W1 — controlled-input method comparison @ 150 nt.** All models trained and tested at 150 nt. Named "method comparison": W1 controls input length, and supervision only among the configs that share it (§8). Non-native runs labelled adaptations.

**W2 — native-configuration comparison.** PrismNet F@101, DeepRiPe E2@150, in-house A@500. Each at its intended operating point; inputs differ by design. Never presented as controlled.

**W3 — window curve.** In-house **A only** at 101 / 251 / 500, nested crops of the same peak centre. Confirmatory scope restricted to A because H4 requires only A; B and C window curves answer interaction questions no hypothesis asks, and are development-only or budget-permitting.

**PrismNet@150 is an adaptation** and carries a fidelity check: layer-by-layer diff and parameter count against PrismNet@101, confirming only the input-dependent (flatten/dense) boundary differs.

### 4.5 Sequence-only for the headline

The in-house model uses only letters. With coordinates recovered, W2 may optionally give PrismNet its structure channel and DeepRiPe its region channel — reported as a separate "native inputs" row, never mixed into the sequence-only comparison.

---

## 5. Experimental design

### 5.1 Configurations

Notation is **`Config@window`** throughout. A bare config letter never appears in a claim.

| Config | Architecture | Training | Supervision | Model count |
|---|---|---|---|---|
| **A** | In-house ResCNN | joint, 122 outputs | **with** unknown-as-negative penalty | 1 |
| **B** | In-house ResCNN | joint, 122 outputs | masked only | 1 |
| **C** | In-house ResCNN | one model per protein | masked only | 122 |
| **E1** | DeepRiPe | joint, 122 outputs *(adaptation)* | masked only | 1 |
| **E2** | DeepRiPe | grouped *(published rule)* | masked only | **2** |
| **F** | PrismNet `seq` | one model per protein | masked only (native) | 122 |

**A@500 is the submitted recipe.** A@150 and A@101 are adapted in-house configurations.

**Valid comparisons and what each controls**

| Comparison | Window | Supervision | Isolates |
|---|---|---|---|
| B@150 vs C@150 | matched | matched | joint vs per-protein training |
| B@150 vs E1@150 | matched | matched | architecture (multitask) |
| C@150 vs F@150 | matched | matched | architecture (per-protein) |
| A@150 vs B@150 | matched | differs by design | the unknown-as-negative penalty |
| A@150 vs E1@150, F@150 | matched | **not matched** | whole pipeline at common window |
| A@500 vs E2@150, F@101 | native | not matched | whole pipeline at native operating points |
| A@101 / A@251 / A@500 | varies | matched | window contribution |

**A vs C is never presented as isolating multitask learning** — it changes both training mode and supervision.

**Config D dropped.** Reproducing the penalty per protein requires each single-protein model to see all 361,180 rows rather than ~3,650 — two orders of magnitude more compute, and needed only for an interaction no hypothesis requires.

### 5.2 Leakage-safe splitting

**Primary — locus grouping:**

1. Map rows to unique genomic coordinates; retain uniquely-mapped rows.
2. Build connected components of **overlapping aligned exon blocks**; assign each component wholly to one fold.
3. Stratify on **separate positive and known-negative counts per protein**.
4. **Quarantine** ambiguous and unmapped rows, with the §4.2 bias report.
5. **Re-run the §3.1 overlap audit** on the resulting split.

**Acceptance criterion:** no original genomic interval overlaps across folds, confirmed by re-audit. Window-independent, unlike a nucleotide threshold.

**Fallback — sequence clustering**, only if coordinate recovery fails the §4.2 thresholds, and retained regardless as an independent audit. Single-linkage on shared substrings is *not* primary: repeats and low-complexity regions create giant transitive components. Component-size distribution reported either way.

**Gene/transcript grouping** — optional sensitivity analysis only; it answers the stricter question of generalisation to unseen genes.

### 5.3 Development set, confirmatory set, and eligibility

Eight development proteins, frozen, all with unambiguous documented motifs:

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

Membership frozen; baseline values will be recomputed after resplitting but membership will not change.

**These eight are a development set** — anything they influence makes them contaminated for inference. **The confirmatory test runs on the other 114 proteins**, subject to the eligibility rule below. All-122 results are secondary.

**Eligibility minimum, frozen before mapping:**

- **≥ 100 positives and ≥ 100 known negatives per protein in every fold's test partition.**
- **Every fold must contain both classes** for that protein.
- A confirmatory protein failing either condition is **ineligible**, not silently dropped.

**The primary sample is therefore reported as "eligible confirmatory proteins, n = X", never asserted as 114.** Ineligible proteins are listed with their positives, GC baseline and retention rate. A **sensitivity analysis** re-runs the primary comparison at a relaxed minimum (≥ 50 per class per fold) to show the conclusion does not hinge on the threshold.

**The pilot preserves the joint-training setting.** For **A, B and E1**, the full 122-output model is trained; for **E2**, all grouped networks are trained and the collection covers all 122 proteins. Only evaluation and tuning decisions are restricted to the eight development proteins. An eight-output shortcut would misrepresent compute, optimisation dynamics and transfer behaviour. **C and F** are per-protein and independent, so their pilot legitimately trains only the eight.

### 5.4 Folds and seeds

- **W1 and W2: three leakage-safe folds.**
- **W3: one locked group-aware train/validation/test split with three training seeds.** Each protein's result is **averaged across seeds before the protein-level comparison**, with seed variability reported separately.

*(v5 fixes a v4 contradiction: §5.4 said three seeds, the budget table said one. Three is correct.)*

The in-house model is retrained under the same regime as every competitor. The existing fold-0 checkpoint is a historical reference only.

---

## 6. Metrics

### 6.1 Primary

**Per-protein AUROC, macro-averaged, reported raw.** Rank-based, so differing output scales remain comparable and no threshold can be tuned.

AUROC-minus-baseline is **secondary and diagnostic only** — it cancels in head-to-head comparisons on shared proteins. Its one use is aggregating across different protein sets (§7).

### 6.2 Prespecified baselines — window-matched

Fixed before any test result; **all reported**, none selected post hoc: random (0.5); GC-content logistic regression; k-mer logistic regression at k = 3; k-mer logistic regression at k = 6.

**Baseline features are computed on the same window as the models they are compared against.** Comparisons involving A@500 use 500 nt features; the controlled 150 nt comparison uses 150 nt features; W3 contrasts use the matching window at each point. A single baseline family evaluated at one window would otherwise silently favour whichever models share that window.

Where a single baseline is needed for stratification it is **GC at the relevant window**, fixed in advance.

### 6.3 Biological-validity diagnostics

Neither is a pass/fail gate.

**Dinucleotide-preserving shuffle** — ten Altschul–Erikson shuffles per positive; report the change in score distribution and in AUROC against real negatives, median over shuffles. Shuffled RNA carries no known binding label, so failure to collapse to 0.5 does not prove reliance on composition.

**Motif recovery** — for the eight development proteins, motif discovery on top-scoring sequences against ATtRACT / CISBP-RNA.

### 6.4 Evaluation sets

**Original**, for comparability; and **composition-matched** as sensitivity analysis — negatives resampled per protein to match positives' GC.

With coordinates, region type can additionally be matched. **Expression and eCLIP coverage require additional K562 tracks that we do not currently have**; those will be matched only if appropriate tracks are obtained, and the report states plainly which matching was actually applied.

### 6.5 Cross-validation combination and uncertainty — frozen

**AUROC is computed per fold and then averaged across folds.** Out-of-fold predictions are **not** pooled: independently trained folds can have different score scales, and pooling would distort rankings. Identical across every model, frozen before confirmatory evaluation.

**Uncertainty:**

- per-protein AUROC — bootstrap by resampling **genomic components** within that protein, never individual rows;
- macro mean and paired model differences — resample **proteins as paired units**;
- **all predictions from the same locus stay together** in every resample;
- 2,000 resamples; 95% CIs throughout.

**Effect sizes alongside every p-value** — matched-pairs rank-biserial correlation. Wilcoxon signed-rank as supporting evidence. **Win counts descriptive only.**

### 6.6 Calibration — penalty analysis only

For **A@150 vs B@150** only, report **Brier score and log loss** on known positive/negative test pairs, since the penalty may affect calibration more than ranking. Never a headline metric across unrelated methods.

### 6.7 Other diagnostics (budget permitting)

Performance vs. available training data per protein; **GC difficulty analysed continuously**; learning curves at 25/50/100%; runtime, parameter count, model count.

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

Largely dissolves in the retrained design — we train for all 122. Applies mainly to the secondary pretrained-weights experiment. Never average across different protein sets; compare pairwise on each pair's own overlap; use paired differences; report coverage as a column; test for coverage bias as in §3.5.

---

## 8. Hypotheses and decision rules — frozen

**No rule below may be changed after examining comparative pilot performance.** Any change is recorded with justification; the development set is excluded from confirmatory analysis regardless.

**Shared definitions**

- **Clear margin (confirmatory)** — mean per-protein AUROC improvement **≥ 0.02** *and* **95% CI lower bound > 0**. Both required. A point estimate of 0.02 with a CI crossing zero is **inconclusive**, not supportive.
- **Equivalence** — the 95% CI for the AUROC difference lies **entirely within [−0.02, +0.02]**.
- **Inconclusive** — neither a clear margin nor equivalence.
- **Hard proteins** — prespecified GC baseline AUROC **< 0.60** on the leakage-safe split; descriptive, with GC difficulty **also analysed continuously**.
- **Advantage holds on hard proteins** — mean paired improvement **≥ 0.02** within the subgroup, **with CI reported**; the subgroup CI is *not* required to exclude zero.
- **Leakage-safe** — no original genomic interval overlaps across folds, confirmed by re-audit.

All rules are evaluated on the **eligible confirmatory proteins (n reported, §5.3)**.

### H1 — Predictive superiority

Three sub-claims, reported separately; none implies another.

- **H1a (submitted recipe, native operating points, W2):** A@500 beats every window-matched prespecified baseline, and beats E2@150 and F@101, by a clear margin.
  Supported conclusion, verbatim: *"the submitted pipeline outperforms **our retrained implementations of** the published methods at their respective operating points."*
  **This qualification appears in the abstract, in §8, and in every results table.** The unqualified form — "outperforms published methods" — is not supported, because E2 is modified for the 22 sub-1,000-positive proteins, both E2 and F use our masked supervision, and neither is the authors' released model.

- **H1b-i (matched supervision, W1):** B@150 beats E1@150, and C@150 beats F@150, by a clear margin.
  Supports *"the in-house architecture outperforms competing architectures at matched input length and matched supervision."*

- **H1b-ii (common window, W1):** A@150 beats E1@150 and F@150 by a clear margin.
  Supports *"the in-house pipeline outperforms competing methods at matched input length."* **Supervision is not matched here** — A carries the unknown-as-negative penalty while E1 and F mask unknowns — and the claim is never stated as controlling for supervision.

If only some hold, only those are claimed, each with its qualification.

### H2 — Multitask benefit

**B@150 beats C@150 by a clear margin** (≥ 0.02 and CI lower bound > 0). Supports *"joint training across proteins improves prediction, holding architecture, window and supervision fixed."*

If the CI lies within [−0.02, +0.02]: *"joint training is equivalent to per-protein training at this window."* Otherwise inconclusive.

**Independent of H1.** A@500 could beat the competitors through architecture, window or the penalty while H2 fails; the write-up then supports H1 and explicitly declines the joint-learning attribution.

### H3 — Penalty effect

**A@150 vs B@150**, reported with AUROC *and* the §6.6 calibration metrics.

- **Helps / hurts** — clear margin in that direction.
- **Neutral for ranking** — only if the AUROC-difference CI lies entirely within [−0.02, +0.02]. A non-significant difference alone does **not** license "neutral".
- **Inconclusive** — otherwise.

Calibration is reported separately and may differ in direction from ranking; that divergence would itself be the finding.

### H4 — Window contribution

**Primary contrast: A@500 vs A@101.**

- **Contributes** — paired improvement ≥ 0.02 and CI excludes zero.
- **Does not materially contribute** — CI lies entirely within [−0.02, +0.02].
- **Inconclusive** — otherwise.

**A@251 is the intermediate dose-response point**, reported to show whether any effect is monotone. Confirmatory scope is config A only.

### Reported alongside, not as gates

W2 native-configuration detail; shuffle and motif diagnostics; composition-matched sensitivity; coverage; the relaxed-eligibility sensitivity analysis.

### Other outcomes

- *Comparable accuracy, one model for 122 proteins, cheaper to train* — a legitimate positive result, stated in advance.
- *Wins on low-data proteins, ties elsewhere* — supports H2 specifically.
- *Gains vanish under the leakage-safe split* — pivot to §11.
- *Nothing beats the trivial baselines* — pivot to §11.

---

## 9. Pre-execution deliverables

The next reviewer gate. Circulated **before** any full-scale training run.

- [ ] **Frozen data manifest** — SHA-256 per source file, row count, sample IDs, 122-protein index mapping, encoding spec.
- [ ] **Mapping-retention report** — every item and threshold in §4.2, including retention by protein and class and GC/repeat comparison between retained and quarantined rows.
- [ ] **Frozen fold composition** — component assignments, with the post-split §3.1 re-audit against the §5.2 criterion.
- [ ] **Fold-balance report** — positives and known-negatives per protein per fold, from separate indicators, against the §5.3 eligibility minimum; eligible-protein count and the ineligible list.
- [ ] **Exact E1 / E2 specification** — architecture, output structure, model count, bin assignment actually used, and explicit confirmation that both mask unknowns.
- [ ] **Loss audit** — per config, which terms are active and how unknowns are treated; both components logged per epoch with measured ratio over training.
- [ ] **PrismNet checkpoint record** — filename, config, `conv.weight.shape` per checkpoint (§3.4).
- [ ] **PrismNet@150 fidelity diff** — layer inventory and parameter count against PrismNet@101.
- [ ] **Pilot learning curves** — eight development proteins, full-scale training for joint configs, all diagnostics.
- [ ] **Measured runtime** replacing the §10 estimates.
- [ ] **Output schema** — tidy tables, not row-ordered `.npy`:
  `sample_id, protein, fold, seed, window, config_id, config_hash, score`
  plus a config registry mapping `config_id` to architecture, supervision, window, model count and code commit.

---

## 10. GPU budget

Assumptions: Colab T4; in-house ResCNN ≈ 2–4 min/epoch at 500 nt, batch 256, 30 epochs; per-protein configs train 122 small models on ~3,650 rows each.

| Experiment | Configs | Regime | Estimate |
|---|---|---|---|
| **W1** controlled input @150 nt | A, B, C, E1, F | 3 folds | ~36 h |
| **W2** native configurations | F@101, E2@150, A@500 | 3 folds | ~21 h |
| **W3** window curve | **A only** @ 101/251/500 | locked split, **3 seeds** | ~15 h |
| Development pilot | A, B, E1 full 122-output; E2 all grouped networks; C, F on 8 proteins | 1 fold | ~8 h |
| **Total** | | | **~80 h** |

Down from v4's 86 h: restricting confirmatory W3 to config A more than offsets moving from one seed to three. B and C window curves, if run at all, are development-only.

Free Colab supplies ~3–4 h/day. Reductions in priority order: W2 to one fold; W3 to two seeds. Colab Pro or a Technion GPU node removes the constraint. **These estimates are replaced by pilot measurements before full-grid approval is sought.**

---

## 11. The methodology pivot

If the advantage collapses after removing leakage, the report becomes a reproducibility and benchmark-design result, quantifying:

- performance under random vs. locus-grouped splitting;
- how inflation scales with train–test sequence overlap;
- the effect of treating unknowns as negatives;
- the effect of GC-matched evaluation;
- which conclusions from the original evaluation survive.

**Action item:** instructor sign-off sought now, not after the result is known.

---

## 12. Priorities

1. Coordinate recovery with the §4.2 retention report — prerequisite
2. Leakage-safe split and post-split audit (§5.2)
3. Trivial baselines, window-matched (§6.2)
4. Development-set pilot (§5.3)
5. H2: B@150 vs C@150
6. DeepRiPe (E1, E2), then PrismNet-seq (F)

First to cut: model-agreement correlations, ensembles, extensive per-protein significance testing, B/C window curves. RBPNet stays exploratory.

---

## 13. Open items

| Item | Status |
|---|---|
| Negative sampling procedure | **Unknown**, unrecoverable. Largest remaining unknown |
| Genomic coordinates | Prerequisite. Recovery unattempted |
| PrismNet checkpoints | Models directory empty; needed for §3.4 |
| Original train/test split file | On the departed teammate's Drive; reproducible from seed, unconfirmed |
| Genome build | Unknown; two candidates, both quick to test |
| K562 expression / coverage tracks | Not obtained; §6.4 matching conditional on them |
| Reimplementation fidelity | Risk of under-training a competitor; mitigated by §9 |
| Compute budget | ~80 h against free-Colab capacity |
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
| Positives per protein | 506 – 2,000 |
| — exactly 2,000 | **57 proteins** |
| — exactly 1,999 | **11 proteins** |
| — 1,000 ≤ n < 2,000 | **43 proteins** |
| — n < 1,000 | **22 proteins** |
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
| E2 as it runs on our data | **2 networks**: 57 proteins (n = 2,000) and 65 proteins (n < 2,000) |
| DeepRiPe sequence-only ablation | Published — confirmed |

*All AUROC figures were computed on the leaky split and will be recomputed after §5.2.*

**Sources for external facts:** DeepRiPe — Ghanbari & Ohler, *Genome Research* 30:214 (https://genome.cshlp.org/content/30/2/214.full). PrismNet — source at https://github.com/kuixu/PrismNet (`tools/main.py`, `prismnet/model/PrismNet.py`).
