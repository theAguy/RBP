Thanks — this was very useful. I've accepted all eight points and attached v2, which opens with a changelog table mapping each one to what changed.

Two things came out of checking your points that I think you'll want to see before reading the rest.

**Your point 2 was right, and the scale is worse than either of us assumed.** I indexed every offset of a random sample of rows and queried the full dataset, so overlaps are detected regardless of alignment. There are no exact duplicates and no reverse-complement duplicates — but **80.3% of rows share ≥150 nt of exact sequence with at least one other row, and 76.6% share ≥300 nt of their 500 nt window.** Median 6 overlapping partners, maximum 306. 73% overlap a row labelled for a different protein.

So the random split leaks for roughly three-quarters of the data, and the inflation is probably asymmetric, since only the in-house model was trained on that split. Every number produced so far, mine included, needs recomputing. This is now the top priority, ahead of everything else.

**On your stratification and loss questions — both confirmed, and the loss finding is new.** `targets * masks` is *identical* to `targets`; the 173,532 known negatives were invisible to the fold splitter, exactly as you suspected. And the loss is mask-aware in its first term but then adds a second term that pushes every unknown label toward zero, with `lambda_unknown = 1` against `lambda_pos = 15`. Since unknowns are ~99% of entries, that's a substantial training signal treating unlabelled as unbound.

It's a defensible PU-learning choice, but it was undocumented, and it means the in-house model confounds *three* things rather than two: architecture, joint training, and the PU term. I've expanded your point 1 into a 2×2 grid — {joint, per-protein} × {with, without the unknown penalty} — in §5.1.

A few smaller notes. On point 3, I've demoted RBPNet on the principle that we only reimplement configurations the original authors published: PrismNet ships a `seq` mode and DeepRiPe reports a sequence-only ablation, whereas RBPNet has no binary-classification mode at all. On point 4, the teammate confirmed the 500 nt windows are peak-centred and symmetric, so 101 ⊂ 251 ⊂ 500 share a centre and window size becomes a clean nested ablation — every model trained and tested at each size, no inference-time cropping. On point 5, I've made raw AUROC primary and kept the baseline-subtracted version only for aggregating across different protein sets in the coverage section, flagged as a diagnostic.

§8 now has numeric thresholds, §9 is the pre-execution checklist you asked for, and §10 estimates ~75 GPU-hours for the full grid, which is more than free Colab realistically supplies.

Five questions are in §12. The two I'd most value your view on:

1. **Is sequence clustering an acceptable grouping criterion, or should coordinate recovery become a hard prerequisite?** Single-linkage clustering on shared subsequence may produce large components — one row had 306 partners — which could make folds badly unbalanced. Recovering genomic coordinates by alignment would let us group by locus instead, which is both simpler and more correct. It's roughly half a day of work and no GPU. Given the overlap numbers, I'm inclined to do it first rather than treat it as a bonus.

2. **How should the unknown-label penalty be handled?** The 2×2 grid measures its effect, but there's an argument for simply removing it so the in-house model is compared on the same loss as the competitors. That changes what we're evaluating — the teammate's actual model versus their architecture — and I don't have a strong view on which is the right object of study here.

Nothing will be launched until the pilot in §5.3 and the checklist in §9 are done.
