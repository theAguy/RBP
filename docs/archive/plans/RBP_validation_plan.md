# Validating an RBP-binding predictor against three published methods

**Project plan — for review**
Course project, Technion bioinformatics, winter 2026
Drafted 15 Sep 2026

---

## 0. TL;DR for the reviewer

A teammate built a neural network that predicts which RNA-binding proteins (RBPs) bind a given RNA sequence. It is a single multi-label model covering 122 proteins. My role is to validate it against the three standard published methods in this field: **PrismNet**, **DeepRiPe** and **RBPNet**.

Before writing this plan I ran diagnostics on the existing data and results. Two findings shape everything:

1. **The existing PrismNet results are invalid.** PrismNet was run with a missing input channel, and scores below random on 19 of 100 proteins. Those numbers cannot be reported.
2. **The benchmark has a composition confound.** A one-feature classifier that does nothing but count G and C letters achieves a mean AUC of **0.729** across the 122 proteins, and beats PrismNet on **84 of 100**. This means an AUC on this dataset is not yet evidence that a model learned anything about protein binding.

The plan therefore has two halves: first establish a trustworthy yardstick, then run the comparison against it.

**Main methodological decisions I am proposing, and would like challenged:**

- Rebuild the three published architectures and **retrain them on our data**, rather than installing their legacy code and using their downloadable weights.
- Run the headline comparison **sequence-only**, because the in-house model is sequence-only.
- Treat the genomic-coordinate-dependent version as a **secondary, bonus experiment**, not a prerequisite.

---

## 1. The problem

RNA-binding proteins attach to RNA molecules at specific locations, and this is a major mechanism of post-transcriptional regulation. Predicting where a given protein binds, from sequence alone, is a well-established machine-learning task with several published deep-learning solutions.

Our teammate's contribution is architectural: instead of training one model per protein (what everyone else does), they train **one model that predicts all 122 proteins at once**. The hypothesis is that proteins share binding preferences, so a joint model should transfer knowledge between them — particularly helping proteins with little training data.

**The question this project answers:** does that actually work better than the established per-protein methods, and if so, why?

My role is validation, not model development. The output is a defensible comparison, including the possibility that the answer is "no."

---

## 2. The data

### 2.1 What we have

| File | Contents |
|---|---|
| `dataset_K562_multilabel_with_NEGs.csv` | 361,180 sequences, 122 protein labels. 724 MB. |
| `intRBP ResCNN - for students.ipynb` | The teammate's model, training and evaluation code. |
| `CNNMultiLabelResidual_20250812_123241.pth` | Their trained weights. |
| `output_sequences.tsv` | Centre 101 nt of each sequence, decoded to letters. Prepared for PrismNet. |
| `out_tests/out/infer/*.probs` | PrismNet output for 100 of the 122 proteins, already computed. |
| `papers/` | The three reference papers. |

All from **ENCODE eCLIP in the K562 cell line**.

### 2.2 Format

Each row is 500 RNA letters, stored one-hot encoded (2,000 bits, groups of 4, order ACGT), plus a `labels` field: semicolon-separated signed integers indexing into a fixed list of 122 proteins. `+7` means "protein 7 binds here"; `-18` means "protein 18 does not bind here".

Four real rows (showing 30 letters from the centre):

```
Row 0    ...TCCTTGCTGGACAGATCCATCTGTGTGTGC...
         binds:     AQR
         does not:  —
         unknown:   the other 121 proteins

Row 1    ...ACACAGCAGGGGGCGGGACCCTCCCCTCTG...
         binds:     —
         does not:  DDX43
         unknown:   the other 121 proteins

Row 2    ...CTGGATGAAGATCGTTCTGGGGCTCGCCGC...
         binds:     SRSF1, TRA2A, ZNF622
         does not:  —
         unknown:   the other 119 proteins

Row 136  ...TCGTGACCCCAGCCCCGCCGGGCCGACCCG...
         binds:     PHF6
         does not:  DGCR8
         unknown:   the other 120 proteins
```

### 2.3 The critical structural fact: three states, not two

Every (sequence, protein) pair is one of **binds / does not bind / unknown**, and *unknown* dominates. On average a row carries information about **1.04 of the 122 proteins**.

Consequences:

- Evaluation must be masked: when scoring protein X, only rows carrying `+X` or `-X` are used. Everything else is excluded.
- Standard multi-label metrics (Hamming loss, subset accuracy, etc.) are **not computable** here — they assume the full label vector is known.
- Effectively this is **122 independent binary classification problems**, evaluated separately and then combined.

### 2.4 Per-protein statistics (verified)

| Quantity | Value |
|---|---|
| Positives per protein | 2,000 (max); 506 (min) |
| Negatives per protein | 1,651 (max) |
| Labelled rows per protein | 1,012 – 3,651 |
| Class balance | ~55 / 45 |
| Rows with ≥ 2 positive labels | ~6,500 of 361,180 |

The near-balance matters: it means AUPRC offers little over AUROC here, and it means the setup is much easier than real transcriptome-wide search, where binding sites are rare.

### 2.5 What "negative" means, and why it matters

A negative is **not** a tested non-binder. No one ran 361,180 binding assays.

The eCLIP experiment pulls down RNA fragments bound to one protein and sequences them. Regions with strong pile-up are called **peaks** — these are the positives. Negatives are regions that *were not* called as peaks, selected by whoever built the dataset.

So a negative means **"no evidence of binding in this experiment"** — which is weaker than "does not bind", since a region can look unbound because the RNA was lowly expressed or poorly covered.

More importantly, **how those regions are chosen is a free design decision**, and it determines what the benchmark measures.

What I verified about these negatives:
- They are **not** other proteins' binding sites — only ~1% of a protein's negatives are positive for any other protein. So they are generic background, not competitive counter-examples.
- They are **compositionally different** from the positives: mean GC 0.462 vs 0.528, with positives GC-richer in 92 of 122 proteins.

We do not have documentation of the sampling procedure, and the teammate has left the project. This is the single biggest unknown in the dataset.

---

## 3. What I found in the existing results

### Finding 1 — the PrismNet run is broken

PrismNet's data loader reads a **4-column** TSV and constructs a **5-channel** input: four one-hot sequence channels plus one icSHAPE RNA-structure channel taken from column 4. Our `output_sequences.tsv` has **3 columns**, and the cached tensor is `(361180, 1, 101, 4)`.

The pretrained `_pu_` weights were trained *with* structure and are being fed input *without* it.

Scored against the dataset labels:

| | |
|---|---|
| Mean AUC over 100 proteins | **0.619** |
| Median | 0.611 |
| Proteins scoring **below** random | **19 of 100** |
| Worst cases | FUS 0.273, EWSR1 0.311, FXR1 0.343 |

Scores that far below 0.5 are systematically inverted predictions, not weak ones. No published evaluation of PrismNet looks like this. **These numbers must not be reported.**

### Finding 2 — the benchmark has a composition confound

Build the dumbest possible predictor: for each sequence, compute the fraction of letters that are G or C. Use that as the prediction. No training, no model, no biology.

| Predictor | Mean AUC |
|---|---|
| GC content alone | **0.729** |
| PrismNet (as run) | 0.619 |

GC content wins on **84 of the 100** proteins where both are available.

This means the positives and negatives in this dataset differ in an uninteresting way, and a model can score well by detecting sequence composition rather than protein-specific binding.

**This is the central methodological issue of the project.** It implies:

- Every reported AUC needs the trivial baseline printed next to it.
- The meaningful quantity is not AUC but **AUC minus the baseline**.
- If the in-house model scores 0.70, that is a *bad* result, not a good one — it loses to letter-counting.

### Finding 3 — the existing comparison is not apples-to-apples

Two further issues in the current setup:

- **Window size.** The in-house model reads all 500 nt. PrismNet was given the centre 101 nt — 20% of the sequence. This advantages the in-house model for reasons unrelated to architecture.
- **Threshold tuning.** The evaluation code selects the optimal decision threshold per protein *on the evaluation set itself*. This inflates the reported F1 scores. Rank-based metrics such as AUC avoid this entirely, which is one reason to lead with them.

### Finding 4 — coverage is not random

PrismNet ships models for 100 of our 122 proteins. The 22 it skips are not a random sample:

| | Proteins PrismNet covers | Proteins it skips |
|---|---|---|
| Count | 100 | 22 |
| Median positives available | 1,999 | 1,289 |
| Baseline difficulty (GC AUC) | 0.729 | 0.704 |

It covers the well-studied, data-rich proteins. Its average is therefore mildly flattered by its own coverage choices. Worth reporting.

---

## 4. Proposed approach

### Decision 1 — rebuild and retrain, rather than install legacy code

**The problem.** The three published tools have incompatible, obsolete stacks:

| Tool | Requires |
|---|---|
| PrismNet | Python 3.6, PyTorch 1.1 (2019) |
| DeepRiPe | Keras / TensorFlow 1.x |
| RBPNet | TensorFlow 2, modern Python |

We will run on Google Colab, which provides Python 3.12 and PyTorch 2.x, and **does not allow changing the Python version**. Forcing 2019-era dependencies into that environment is days of work with a real chance of failure.

**The proposal.** Reimplement all three architectures in modern PyTorch and train them on our data, our split, our negatives.

Advantages:
- No legacy installation at all. One modern environment.
- Genuine apples-to-apples: every model sees identical data.
- Removes two confounds present in the pretrained-weights approach:
  - the published models were trained with **differently defined negatives** (unfair to them);
  - they were trained on ENCODE K562 eCLIP, the same source as our data, so **our test sequences are likely in their training sets** (unfair to us).
- Coverage stops being a limitation — we can train a model for all 122 proteins, since "only 100 released models" is a limitation of their download page, not their method.

Costs and risks:
- More implementation work; more opportunity for bugs.
- We cannot claim to have evaluated the *authors'* trained models, only their architectures. Must be stated plainly.
- Risk of under-training a competitor and unfairly making it look weak. Mitigation: match published hyperparameters where stated, train to convergence, and report training curves.

**Secondary experiment, retained:** fix the PrismNet pretrained run (add the structure channel or switch to sequence-only weights) and report it separately as "how do off-the-shelf published tools transfer to our benchmark?" This is a legitimate and interesting question — just a different one.

### Decision 2 — the headline comparison is sequence-only

The in-house model uses only the letters. PrismNet additionally wants RNA-structure data; DeepRiPe additionally wants gene-region annotation. Both extras are looked up by **genomic coordinate** — the chromosome and position each sequence was cut from — which our dataset does not include.

Rather than treating that as a blocker, note that the fair comparison is sequence-only anyway: giving competitors extra information the in-house model never had would make a win uninterpretable.

So:
- **Main experiment:** all four models, sequence-only, identical inputs.
- **Bonus experiment:** recover the coordinates, give the competitors their full intended inputs, and re-run. If the in-house model still wins, that is a much stronger result. If it loses, we have quantified exactly what the extra data is worth — also a result.

Coordinates can likely be recovered ourselves by aligning the 500 nt sequences back to the human genome (standard alignment tools; a 500-mer is essentially unique). Estimated half a day, no GPU. Risks: the dataset may use an older genome build (two candidates, both quick to test), or sequences may be spliced rather than contiguous (detectable immediately).

### Decision 3 — build the yardstick before the comparison

Given Finding 2, the trivial baselines are not an afterthought. They are built first, and every subsequent number is reported relative to them.

---

## 5. Steps

Each step is one Colab notebook. Notebooks share nothing except score files on Google Drive — this isolation is what prevents dependency conflicts.

**Output contract for every model notebook:** one file per protein, `scores/{model}/{PROTEIN}.npy`, containing one score per test sequence. Nothing else crosses between notebooks.

### Step 1 — Data preparation *(no GPU)*
Read the 724 MB CSV once; convert to `.npy` arrays; build the target and mask matrices; fix and save the train/test split. Every later notebook then loads in seconds.

Also: verify the saved split. The `.pth` was evaluated on fold 0 of a 5-fold `MultilabelStratifiedKFold(shuffle=True, random_state=42)` over `targets * masks`. The split JSON is on the departed teammate's Drive; the split should be reproducible from the seed, and we must confirm it matches before comparing against their reported numbers.

### Step 2 — Trivial baselines *(no GPU)*
Per protein, fit on train and score on test:
- random (0.5 by definition)
- GC-content logistic regression
- k-mer logistic regression (counts of short letter patterns, k = 1..6)

This establishes, per protein, the score to beat. **This is the deliverable that makes everything else interpretable.**

### Step 3 — The in-house model
Load the existing `.pth`, score the test set. Also score it on the centre 101 nt only, so we have a matched-window number.

### Step 4 — Competitor reimplementations
One notebook each for PrismNet, DeepRiPe and RBPNet. Build the architecture, train on the same train split, score the same test set. RBPNet outputs a per-nucleotide profile rather than a single score; the aggregation (max / sum / signal-to-control ratio) is chosen on the training fold and reported.

### Step 5 — Fixed pretrained PrismNet *(secondary)*
Repair the input format and re-run the published weights, for the transfer experiment.

### Step 6 — Analysis *(no GPU)*
Read all score files; compute metrics; produce tables and figures.

### Step 7 (optional) — Coordinate recovery and the bonus experiment
Align sequences to the genome, attach structure and region annotations, re-run Steps 4 and 6.

**Practical notes.** Free Colab disconnects after a few hours — checkpoint to Drive constantly. Run the 5 cross-validation folds rather than only fold 0 as the original notebook did, so results carry error bars.

---

## 6. Metrics

### 6.1 Primary

**Per-protein AUC**, macro-averaged. AUC has a clean interpretation: *pick a random binding site and a random non-site; AUC is the probability the model scores the binding site higher.* 0.5 is chance, 1.0 is perfect, below 0.5 is backwards.

It is rank-based, so models with wildly different output scales remain comparable, and there is no threshold to tune.

**Reported as Δ over the best trivial baseline, not as a raw number.** Given Finding 2, the raw value is not interpretable on its own.

### 6.2 Comparison between models

- **Win/loss counts and a paired test.** 122 paired observations, one per protein. Wilcoxon signed-rank on the per-protein differences. "Beats PrismNet on 94 of 122 proteins, p = …" is a far stronger claim than comparing two averages.
- **Per-protein significance** where needed: DeLong's test, Benjamini–Hochberg corrected.
- **Distribution, not just the mean:** median, quartiles, and the count of proteins clearing 0.8. A model averaging 0.75 uniformly differs from one that is excellent on 40 proteins and poor on the rest.

### 6.3 Diagnostic analyses

- **Stratify by difficulty.** Group proteins by how well the trivial baseline does; report each model separately on the easy and hard groups. This separates *learned binding* from *rode the confound*. Likely the most informative table in the report.
- **Performance vs. available training data.** Positives per protein range 506–2,000. Plot AUC against that. This directly tests the multi-label hypothesis: a joint model should help most where data is scarce. If the in-house model wins specifically on low-data proteins, we have explained *why* it wins.
- **Model agreement.** Correlate per-sequence scores between models within each protein. High correlation means "same thing, done better"; low correlation with similar accuracy means the models find different signal.
- **Ensemble test.** Average the in-house scores with a competitor's. If the blend beats both, the in-house model carries information the published tools lack — a strong claim that survives even a lost head-to-head.
- **Composition-shuffle control.** Shuffle a high-scoring sequence while preserving its letter composition and rescore. A model using a real local motif drops sharply; a model riding GC content does not. This is a direct, model-level test of the confound, applicable to any model.
- **Motif recovery.** For ~10 proteins with well-characterised motifs, check whether each model's top-scoring sequences contain the known motif (ATtRACT / CISBP-RNA). This is the only check on the list immune to the negative-sampling problem.
- **Learning curve.** Train on 25 / 50 / 100% of the data. Tests the data-efficiency claim of the multi-label design.
- **Practical cost.** Runtime to score all 361,180 sequences, model size, number of models to maintain. One model for 122 proteins vs 122 separate models is a real operational difference.

### 6.4 Deliberately excluded

| Metric | Why not |
|---|---|
| AUPRC as headline | Its advantage is handling imbalance; this data is ~55/45. Will shadow AUC. Kept as a secondary column only. |
| Accuracy, F1, anything thresholded | Model score scales differ enormously (PrismNet's mean output ranges 0.014–0.396 across proteins). Comparing thresholded metrics compares threshold choices. Also the source of the tuning-on-test problem in Finding 3. |
| Hamming loss, subset accuracy, multi-label set metrics | Require the full 122-label vector per sequence. We have 1.04. Not computable. |
| Micro-averaging over all (sequence, protein) pairs | Mixes incomparable score scales and lets data-rich proteins dominate. Macro-average instead. |
| Per-sequence ranking of all 122 proteins | Only ~6,500 sequences have ≥2 known positives; for the rest, ranking 122 proteins is meaningless. Retained only as a small focused analysis on that subset. |

---

## 7. Handling unequal protein coverage

Different methods cover different protein sets — PrismNet 100 of 122, DeepRiPe ~59, RBPNet its own list.

**In the retrained main experiment this largely dissolves**: we train models for all 122. It bites only in the secondary pretrained-weights experiment.

Where it does apply:

1. **Never average across different protein sets.** A mean over 100 proteins and a mean over 59 are different quantities and cannot be ranked against each other.
2. **Compare pairwise, on each pair's own overlap.** "In-house vs PrismNet on their shared 100." "In-house vs DeepRiPe on their shared 59." Each row internally valid; never compare across rows.
3. **Use paired differences, not raw values.** Per-protein difficulty cancels out, making the comparison far more stable against which proteins happen to be in the set.
4. **Subtract the baseline.** Converting each score to "how much better than letter-counting on this protein" removes the dominant source of between-protein variation, and makes different protein sets substantially more comparable. The trivial baseline does double duty: detecting the confound *and* normalising across coverage.
5. **Report coverage as a result.** A column in the main table. "Ships models for 59 of 122" is a real limitation. The in-house model covers 122 of 122 with one model — a genuine advantage that would otherwise be invisible.
6. **Test for coverage bias**, as in Finding 4.

---

## 8. How we will conclude

Stating the decision rules *before* running, so the conclusion is not chosen to fit the result.

**The claim "the in-house model outperforms existing methods" is supported only if all of:**

1. It beats the best trivial baseline by a clear margin, macro-averaged. *If it does not, nothing else matters.*
2. It beats each competitor on a majority of shared proteins, with a significant paired test.
3. The advantage holds on the hard proteins (where the trivial baseline is near chance), not only on the easy ones.
4. The advantage survives matched window size.
5. It passes the composition-shuffle control — i.e. the model responds to sequence content, not just composition.

**Outcomes other than a clean win, and what each would mean:**

- *Comparable to competitors but covers all 122 proteins with one model, trains faster, and is complementary in the ensemble test* — a legitimate and reportable positive result. Worth stating in advance that this is a success, not a failure.
- *Wins on low-data proteins, ties elsewhere* — supports the multi-label hypothesis specifically. Arguably the most scientifically interesting outcome.
- *All models, including the in-house one, fail to beat the trivial baseline* — then the finding is about the dataset, not the models, and the deliverable becomes a benchmark critique plus a recommendation for how the negatives should be re-sampled. This should be treated as a valid outcome, not a failed project.

**Deliverables.**
Main table (methods × metrics, with coverage and *n*). Figure 1: per-protein AUC across methods, sorted by baseline difficulty. Figure 2: pairwise scatter against the diagonal. Figure 3: AUC vs available training data. Figure 4: original vs composition-matched negatives. All code, fixed seeds, split file, and score arrays archived.

---

## 9. Open questions and risks

| Item | Status |
|---|---|
| How were the negatives sampled? | **Unknown.** Teammate has left; no documentation. Determines whether the confound is a fixable sampling artefact. Biggest single unknown. |
| Genomic coordinates | Not in the dataset. Recoverable by alignment — unverified. Needed only for the bonus experiment. |
| Original train/test split file | On the departed teammate's Drive. Should be reproducible from the seed; must be confirmed. |
| Where the PrismNet run was executed | Unknown — the models directory in the shared folder is empty. Needed to confirm which weights were used. |
| Reimplementation fidelity | Risk of under-training a competitor and unfairly weakening it. Mitigate by matching published hyperparameters and reporting training curves. |
| Compute budget | Free Colab. Four architectures × 122 proteins × 5 folds may exceed it. Fallback: reduce folds, or restrict the retrained comparison to a protein subset chosen *before* seeing results. |

---

## 10. Specific questions for the reviewer

1. Is **rebuild-and-retrain** the right call over fighting the legacy environments? It trades sysadmin pain for implementation risk, and means we evaluate the published *architectures* rather than the published *models*.
2. Is the **sequence-only** framing convincing as the primary comparison, with the coordinate-enabled version as a bonus?
3. Given the GC confound — is the right response to (a) report against the baseline, (b) rebuild the negative set to be composition-matched, or (c) both? (b) makes the benchmark better but means we are no longer evaluating on the dataset the in-house model was trained for.
4. Are the pre-stated conclusion rules in §8 too strict, too lenient, or missing a condition?
5. Anything obvious missing from the metrics in §6, or anything there that should be cut?

---

## Appendix — verified facts

Everything below was computed directly from the project files, not taken from documentation.

| Fact | Value |
|---|---|
| Rows | 361,180 |
| Proteins | 122 |
| Sequence length | 500 nt, one-hot ACGT (2,000 bits) |
| `output_sequences.tsv` | centre 101 nt, row-aligned with the CSV (verified) |
| Cached PrismNet tensor | `(361180, 1, 101, 4)` — 4 channels; PrismNet requires 5 |
| Mean known labels per row | 1.04 of 122 |
| Mean positive labels per row | 0.56 |
| Rows with ≥2 positives | ~6,500 |
| Positives per protein | 506 – 2,000 |
| Labelled rows per protein | 1,012 – 3,651 |
| Negatives that are another protein's positive | ~1% |
| Mean GC, positives / negatives | 0.528 / 0.462 |
| Proteins where positives are GC-richer | 92 of 122 |
| GC-only baseline, mean AUC | 0.729 (122 proteins) |
| PrismNet as run, mean AUC | 0.619 (100 proteins) |
| PrismNet below chance | 19 of 100 proteins |
| GC baseline beats PrismNet | 84 of 100 proteins |
| PrismNet coverage bias | covers proteins with median 1,999 positives; skips those with 1,289 |
