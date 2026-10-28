# Sequence-similarity split and leakage audit: detailed explainer

**Audience:** project owners, collaborators, reviewers, and anyone who must
explain why the benchmark split is valid.

**Status:** Task 002C is complete. The components-v2 split is the only accepted
split for future baselines and models. The former teammate's fold and the
intermediate v1 split are diagnostic evidence only.

## 1. The question this work answered

The dataset contains 361,180 RNA sequence rows. A model should be evaluated on
sequences that are genuinely independent of its training data. A row-level
random or stratified split is unsafe if a training row is identical or highly
similar to a validation/test row: the model may recognize the sequence family
rather than generalize to a new one.

Task 002C therefore answered one narrow question before any new model was
trained:

> Can all rows be placed into train, validation, and test so that no sequence
> relationship protected by the frozen 500/251/101-nt similarity definition
> crosses a partition boundary?

The answer is yes. The final split contains 169,699 indivisible components,
assigns every component wholly to one partition, and has zero detected
cross-partition hits in all 18 fresh directed MMseqs2 audits.

This task did **not** train a model, calculate a new AUROC, or determine how
much the former result was inflated.

## 2. The sequence representations

Each original row contains a 500-nt sequence encoded as 2,000 one-hot bits:
four bits per nucleotide in A/C/G/T order. Decoding is a deterministic format
conversion, not machine learning.

Three nested representations were protected:

| Representation | Definition | Main reason |
|---|---|---|
| 500 nt | the entire decoded row | primary long-context model and shifted full-window similarity |
| 251 nt | centered slice `seq[124:375]` | intermediate context-length experiment |
| 101 nt | centered slice `seq[199:300]` | shortest planned input and PrismNet-scale comparison |

The 251- and 101-nt representations are centered crops of the same row. They
are not sliding windows and do not create additional training samples.

## 3. What the former teammate did

The submitted notebook used:

```text
MultilabelStratifiedKFold(n_splits=5, shuffle=True, random_state=42)
strat_labels = targets * masks
```

It used only fold 0, producing 288,944 training rows and 72,236 holdout rows.
The notebook called the latter validation data; it was used repeatedly during
training and threshold/model inspection, so it was not an untouched final
test set.

The stratifier operated on rows, not sequence families. It did not know that
two rows could be exact copies, reverse complements, shifted versions, or
near-identical aligned sequences. It also effectively stratified positives
only: known negatives and unknowns both appear as zero in `targets * masks`.

The notebook contains no explicit reverse-complement canonicalization,
reverse-complement augmentation, or strand-aware split logic. The CNN trained
on each sequence in the orientation stored in the dataset.

Reproducing that fold exactly and comparing it with the then-current **v1
component grouping (173,465 components)** showed:

| Former-fold diagnostic | Result |
|---|---:|
| Components represented in holdout | 51,853 |
| Components crossing train/holdout | 26,765 (51.617%) |
| Holdout rows in crossing components | 45,937 / 72,236 (63.593%) |
| Training rows in crossing components | 120,760 / 288,944 (41.794%) |

Therefore, the former fold is not leakage-safe under the frozen sequence
definition. This does not invalidate the sequences or labels, and it does not
by itself quantify AUROC inflation. These recorded values are v1-grouping
results, not final-v2-grouping results. Because v2 only merges v1 components
and never splits them, the corresponding crossing counts under v2 can only be
equal or higher; the recorded values are therefore lower bounds under the
final relation.

## 4. The frozen similarity rule

The rule was fixed before inspecting model performance and was never tuned to
make a later result look better. MMseqs2 18.8cc5c was used in nucleotide mode.

### 4.1 Sequence identity

Minimum sequence identity was 0.90 at every width. MMseqs2 first constructs a
sequence alignment. Within that alignment, at least 90% of aligned positions
must be identical nucleotides under its true-alignment identity calculation.
Mismatches and alignment gaps reduce identity.

This is **not** Hamming distance over the original strings and is **not** a
comparison of A/C/G/T totals. Order matters. For example, two sequences can
contain exactly the same counts of A, C, G, and T but arrange them differently;
they will not pass unless MMseqs2 can align a sufficiently long region with at
least 90% identity. Conversely, a shifted sequence can pass because alignment
can place corresponding bases together and introduce end clipping or gaps.

### 4.2 Bidirectional coverage

Coverage asks how much of the sequences participates in the accepted
alignment. With `--cov-mode 0`, MMseqs2 uses aligned residues divided by the
longer sequence. This is called bidirectional coverage because a match cannot
be accepted solely by explaining a tiny fragment of one long sequence.

All sequences compared at a given width have the same length, so the practical
minimums are approximately:

| Width | Coverage threshold | Approximate aligned length required |
|---:|---:|---:|
| 500 | 0.80 | at least 400 nt |
| 251 | 0.95 | at least 239 nt |
| 101 | 0.95 | at least 96 nt |

The 500-nt rule allows more displacement because two windows from the same
region may be shifted relative to one another. The shorter center windows use
95% coverage because they represent specific model inputs and should match
almost end to end.

Identity and coverage are both required. A perfect 100-nt local match inside
two 500-nt sequences has 100% local identity but only 20% coverage and fails.
An alignment covering all 500 positions with only 80% identity also fails.

### 4.3 Both strands

RNA/DNA strings can describe the same underlying sequence in opposite
orientations. The reverse complement is obtained by reversing the order and
swapping A with T and C with G. For example:

```text
forward:            A C G T T A
reverse complement: T A A C G T
```

`--strand 2` in the direct-search and audit workflows tells MMseqs2 to test
both the stored orientation and the reverse-complement orientation. The older
clustering command did not expose a strand flag, so its behavior was verified
with a real non-palindromic reverse-complement fixture. The final v2 workflow
used the explicit search command with `--strand 2`.

There are two different meanings of “direction,” and they must not be mixed:

1. **Strand/orientation:** forward versus reverse complement of a nucleotide
   sequence.
2. **Search direction:** train as query against validation as target versus
   validation as query against train as target.

The final construction protected both strands. The final audit also ran both
search directions because MMseqs2's heuristic prefilter is not guaranteed to
return identical results after query and target databases are swapped.

### 4.4 Remaining frozen parameters

| Parameter | Value | Meaning |
|---|---:|---|
| `--search-type` | `3` | explicit nucleotide-versus-nucleotide search |
| `--alignment-mode` | `3` | compute the full alignment statistics needed to enforce identity and coverage rather than relying only on a fast prefilter |
| `-e` | `1000` | permissive E-value ceiling; it avoids losing a high-identity/coverage relation merely because the short sequence has a weak statistical E-value |
| `--mask` | `0` | disable low-complexity masking; repeat-rich similarities remain visible and are conservatively protected |
| `-s` | `7.5` | MMseqs2 sensitivity setting; higher sensitivity costs more time/memory but reduces missed candidates |
| `--max-seqs` | `361180` | allow up to the entire dataset universe as candidates for one query, preventing a smaller default cap from silently deleting edges |
| `--threads` | `4` | execution resource limit only; it does not change the scientific threshold |

The historical v1 clustering additionally used connected-component clustering
flags. Components v2 did not trust the clustering result as the edge relation;
it used the direct search itself.

## 5. What a direct similarity edge means

Treat every dataset row as a graph vertex. If two rows directly satisfy the
frozen identity, coverage, and strand rule at one protected width, create an
undirected edge between them.

For example:

```text
row_A ---- row_B
```

The raw search may report A→B, B→A, or both. The parser removes self-hits,
orders the two IDs canonically, and collapses duplicates. The stored graph edge
is therefore undirected: `{A,B}`.

Direct edges were created specifically to build a safe split. Their endpoints
must end up in the same connected component, and the entire component must be
assigned to one partition.

## 6. Why v1 was rejected

### 6.1 v1 construction

The first pipeline ran MMseqs2's clustering workflow independently at 500,
251, and 101 nt. Each workflow returned representative/member cluster
membership. The pipeline joined rows that shared a cluster and then took the
union across widths and exact/reverse-complement relations. This produced
173,465 v1 components and a valid whole-v1-component assignment.

### 6.2 The mismatch

A clustering output is not necessarily a complete list of every direct pair
that satisfies the search predicate. Two sequences can satisfy the direct
identity/coverage rule yet be assigned to different tool-generated clusters.

The first fresh audit of the v1 assignment found 4,792 qualifying 500-nt
train→validation pairs. Those pairs involved 3,576 distinct rows and connected
v1 components that had been placed in different partitions. This was only the
first of 18 planned directed searches; the audit stopped on that failure by
design, so the other 17 searches were not run and 4,792 is a lower bound on
the rejected v1 split's direct-search leakage rather than a complete total.

Therefore, v1 was not accepted for modeling. We did not argue that the audit
was too strict, weaken a threshold, or merely patch those 4,792 pairs.

## 7. The changed construction: components v2

Components v2 use the direct audit relation as the construction relation.

1. Run full all-versus-all direct MMseqs2 search at 500 nt.
2. Normalize every qualifying non-self pair into an undirected direct edge.
3. Repeat at 251 and 101 nt.
4. Add independently calculated exact/reverse-complement relationships.
5. Preserve every historical v1 co-membership relation, labelled explicitly
   as a protected relation rather than pretending it is a direct alignment.
6. Take the connected components of the union.

The protected-v1 step is conservative: v2 may merge old components but may
never split one. It ensures that changing construction algorithms cannot
discard a relationship already protected by the earlier accepted evidence.

Final direct-edge counts were:

| Width | Normalized direct edges |
|---:|---:|
| 500 nt | 943,435 |
| 251 nt | 217,571 |
| 101 nt | 102,759 |

The v2 result contains 169,699 components. It merged 6,406 historical v1
components into 2,640 larger v2 components, affecting 54,610 rows, and split
zero v1 components.

## 8. Connected components

A connected component is every vertex reachable through a chain of edges.
Direct similarity need not be transitive, but leakage protection must be.

Example:

```text
A ---- B ---- C       D
```

- A is directly similar to B.
- B is directly similar to C.
- A and C may not directly satisfy the threshold.
- A, B, and C still form one component because information can flow through
  the sequence family.
- D is a singleton component.

If A were in training and C in test, B would connect the two sides. We
therefore move `{A,B,C}` as one indivisible unit.

The final graph has 169,699 components, including 118,943 singletons. The
largest component has 708 rows (0.196% of the dataset), and the largest 20
together contain 1.809%. These are far below the prespecified 5% and 20%
giant-component stop gates.

## 9. Assigning whole components

Yes: the split is a split of components, not rows. Every row in a component
goes to train, validation, or test together. A component is never divided to
improve balance, because dividing it would recreate leakage by construction.

Only after components were frozen were labels used for balance. For each
component, the software aggregated:

- component row count;
- 122 known-positive counts; and
- 122 known-negative counts.

Unknown labels contributed to neither class. Thus each component had one row
dimension and 244 label dimensions.

### 9.1 Deterministic assignment procedure

The target was 70% train, 15% validation, and 15% test with seed `20260925`.
The algorithm was deterministic:

1. Calculate how difficult each component is to place. A component is more
   difficult if it contains a large share of all rows or a large share of any
   protein's positive/negative examples.
2. Sort difficult/larger components first. Use a seeded hash only as the final
   tie-break, so input file order cannot change the result.
3. For the next component, tentatively place it in each partition.
4. Calculate the increase in normalized squared deficit from all targets.
   Normalization prevents total row count from overwhelming rare labels.
5. Give the one row-count dimension the same total weight as all 244 label
   dimensions combined.
6. Choose the partition with the smallest increase. Exact ties resolve in the
   fixed order train, validation, test.
7. If any validation/test protein class is below 30, allow only deterministic
   whole-component moves or swaps that strictly improve the frozen repair
   objective without breaking another floor or row-fraction limit.

Toy example: suppose train is short of rows but validation is short of known
positives for protein X. Component K contains 100 rows and 20 X positives.
Putting K in train helps row balance but hurts the X-positive balance;
putting K in validation helps X but may overshoot validation rows. The
normalized objective scores both consequences and selects the lower total
deficit. K is never split 70/15/15 internally.

The real assignment needed zero repair steps. Repeating it with reordered
component input produced byte-identical membership and scientific summaries.

### 9.2 Final row counts

| Partition | Rows | Fraction | Target | Deviation |
|---|---:|---:|---:|---:|
| Train | 246,017 | 68.1148% | 70% | -1.8852 pp |
| Validation | 57,565 | 15.9380% | 15% | +0.9380 pp |
| Test | 57,598 | 15.9472% | 15% | +0.9472 pp |

All row fractions are within the accepted ±3-percentage-point boundary.
Every protein has at least 30 known positives and 30 known negatives in both
validation and test. The observed minima are 97 positives (protein 93) and 80
known negatives (protein 53).

## 10. Per-protein imbalance: what it means and what can be done

Whole-component safety and perfect label stratification can conflict. If many
examples for a protein occur in a few large sequence families, those families
cannot be divided among partitions.

The final split passes every hard count floor, but it is not perfectly
stratified:

- 86 of 122 proteins have at least one positive/negative partition cell more
  than 3 percentage points from its 70/15/15 target;
- 218 of all 732 cells (122 proteins × 3 partitions × 2 classes) are flagged;
- considering validation/test only, 54 proteins and 117 cells are flagged.

Example: protein 25 has 2,000 known positives: 437 train (21.85%), 779
validation (38.95%), and 784 test (39.20%). Its known negatives are much more
balanced. This illustrates why aggregate row balance does not guarantee every
protein/class is proportioned identically.

The current assignment is deterministic and accepted, but the heuristic was
not proven to be the global optimum for label balance. Possible responses are:

1. **Recommended for the main benchmark:** keep the locked split; publish every
   protein's train/validation/test positive and negative counts; flag all
   >3-percentage-point deviations; use confidence intervals and avoid
   over-interpreting noisy proteins.
2. Perform a label-only, pre-model feasibility study to determine whether a
   stronger whole-component optimizer could materially reduce imbalance. This
   would be diagnostic unless the project deliberately reopened and refroze
   the split before seeing model results.
3. Do **not** split components. That would solve the arithmetic problem by
   reintroducing the scientific leakage problem.
4. Do **not** train on many random splits and average them as a substitute for
   one locked test set. Repeated component-level resampling may later quantify
   uncertainty, but model selection still needs a fixed untouched test split,
   and related rows must remain together in every resample.

Because no model has yet been evaluated, reopening is scientifically possible,
but it would require a new prespecified assignment rule and repetition of the
acceptance audit. The current recommended course is to retain the accepted
split and treat balance flags as explicit limitations/covariates.

## 11. How leakage was inspected

No single zero count was trusted. The audit used several independent layers.

### Layer 1 — reproduce the former split

The notebook's first fold was recreated with the pinned library, seed, and
positive-only stratification matrix. This established exactly which rows the
former experiment treated as training and holdout. The old boundary was then
compared with the rejected v1 component membership, producing the recorded
63.593% affected-holdout result above. Task 003A separately recomputes this
diagnostic against final v2 membership; it must not relabel the v1 result.

### Layer 2 — construct v2 from full direct searches

For each width, the complete decoded dataset was searched against itself with
the frozen rule. Endpoints were reconciled against the exact 361,180-ID
universe. Self-pairs were removed; duplicate/reversed pairs were collapsed;
and normalized edge counts and hashes were independently reread.

### Layer 3 — independent exact/reverse-complement audit

A separate implementation reread every accepted FASTA and independently
canonicalized a sequence with its reverse complement. It did not reuse the
construction helper. At 500 and 251 nt it found no duplicate groups; at 101 nt
it found two groups of size two. Both groups were contained inside one
partition. Cross-partition violations: zero.

### Layer 4 — prove the audit searched the intended data

Fresh partition FASTAs were regenerated from final membership. For every
width and partition, IDs and per-sequence hashes were matched to the accepted
full FASTA. Fresh MMseqs2 databases were checked through their lookup tables
and converted back to FASTA to verify a round trip.

### Layer 5 — positive controls

Before accepting a zero-hit audit, deterministic self-hits and known
same-partition construction edges were searched. Their recovery showed that
the tool, strand mode, databases, and parser were functioning. A zero result
was therefore not merely an empty or broken search.

### Layer 6 — 18 fresh directed searches

There are three widths and three unordered partition pairs:

```text
train–validation, train–test, validation–test
```

Each pair was searched in both query/target directions:

```text
3 widths × 3 pairs × 2 directions = 18 searches
```

These searches used fresh partition databases and did not reuse the
construction search results. Every returned endpoint had to belong to the
declared query and target universes. All 18 searches reported zero qualifying
cross-partition hits.

### Layer 7 — independent final reconstruction

The production components were built with union-find. Final verification
independently rebuilt the graph closure with breadth-first search. It obtained
the same 169,699 component count. All 361,180 rows appeared exactly once, no
component crossed a partition, assignment and repeat hashes matched, and no
remediation cycle was needed.

The correct conclusion is:

> No cross-partition relationship was detected under the frozen
> 500/251/101-nt MMseqs2 and exact/reverse-complement definitions.

This is stronger and more honest than claiming that no imaginable biological
relationship exists. Genomic-coordinate leakage remains untested because the
coordinate indexing path was resource-infeasible and was explicitly deferred.

## 12. Why 500, 251, and 101 nt—and what about 150 nt?

The former teammate's scientific idea includes a context-length claim: about
500 nt may carry useful information that shorter sequence windows omit. The
cleanest test is therefore an in-house window ablation at the already protected
500, 251, and 101 nt widths. It asks whether performance improves as more
context is supplied while the architecture and split are controlled.

There is no need to add a 150-nt in-house condition to test that hypothesis.
It would add cost while giving a less interpretable spacing of context sizes.

However, a published competitor's native 150-nt input is a separate issue.
The current split was not explicitly audited at 150 nt. Protection at 101,
251, and 500 nt will catch many 150-nt relationships, but it does not logically
guarantee all of them. Therefore:

- do not make 150 nt part of the main context-length ablation;
- run controlled competitors at one of the protected common widths when their
  implementation permits it; and
- if a native DeepRiPe-at-150 result is later considered scientifically
  essential, prespecify and run a 150-nt leakage audit before reporting that
  result. Otherwise omit the native 150-nt operating point and disclose why.

The primary scientific claim should remain 500-versus-251-versus-101, with
500 nt as the former teammate's intended long-context operating point.

## 13. Final accepted evidence

| Item | Accepted result |
|---|---|
| Rows | 361,180, each exactly once |
| Components v2 | 169,699 |
| Singletons | 118,943 |
| Largest component | 708 rows (0.196%) |
| Largest 20 components | 1.809% of rows |
| v1 components split | 0 |
| Assignment repeat | byte-identical |
| Exact/RC cross-partition violations | 0 at all three widths |
| Fresh directed searches | 18 / 18 accepted |
| Fresh near-similarity violations | 0 |
| Remediation cycle | not used |
| Final membership SHA-256 | `ca527da4f0c0615bcb9d31c6fc705523238e8fb8f4751473ccc2af3ee0aecddb` |

The accepted return is stored under
`artifacts/teammate_run_results/002c_r3r5_darwin_production_20261026/`.
The tracked closure record is
`manifests/sequence_partitions_002c_v2.json`, and the formal review is
`docs/reviews/002c_final_sequence_partition_acceptance.md`.

## 14. Claims now allowed and not allowed

Allowed:

- the former row-level fold is not leakage-safe under the frozen relation;
- the final components-v2 split is deterministic and passes the prespecified
  500/251/101-nt sequence-leakage gates;
- all methods can now be compared on the same locked membership; and
- label imbalance remains for some proteins and is explicitly disclosed.

Not yet allowed:

- the former model is better or worse than a competitor;
- the old AUROC was inflated by a specific amount;
- 500 nt improves prediction over shorter windows;
- joint training helps;
- the positive weight or unknown penalty helps; or
- the split is protected at an untested native width such as 150 nt.

Those are questions for the baseline and model-comparison phases.

## 15. Source documents

- Frozen split design: `docs/tasks/002_sequence_clustered_partitions.md`
- Assignment and audit contract:
  `docs/tasks/002c_partition_assignment_and_audit.md`
- v1 failure and corrective design:
  `docs/reviews/002c3_cross_partition_failure_and_component_rebuild_plan.md`
- Final combined execution contract:
  `docs/tasks/002c_r3_r5_end_to_end_v2_execution.md`
- Former-split diagnostic acceptance:
  `docs/reviews/002c2c_non_mmseqs_diagnostics_acceptance.md`
- Final closure review:
  `docs/reviews/002c_final_sequence_partition_acceptance.md`
