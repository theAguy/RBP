Thanks — all corrections accepted. v3 attached, changelog at the top. Three things worth your attention before the rest.

**Your PrismNet challenge was fair, and I can now evidence the invalidation properly.** You were right that a four-channel tensor alone proves nothing, since PrismNet has an official sequence-only mode. From the source:

- `tools/main.py` builds output filenames as `identity = p_name + '_' + arch + '_' + mode`. Our files are named `AATF_PrismNet_pu_…`, so **PrismNet itself recorded the runtime mode as `pu`**.
- In `prismnet/model/PrismNet.py`, `mode="pu"` sets `n_features = 5`, while `"seq"` sets 4 and slices `input[:,:,:,:4]`.
- The first layer is `Conv2d(1, base_channel, kernel_size=(11, h_k), bn=True, same_padding=True)` — so `pu` builds a width-5 kernel.
- Our cached tensor is width 4, and `same_padding=True` means a width-5 kernel over width-4 input **pads rather than errors**. That is why the run completed and produced plausible numbers.

So a structure-expecting model consumed structure-free input, silently. I've kept your residual check as a required deliverable and made it specific: read `conv.weight.shape` from the checkpoint, which is `(base_channel, 1, 11, 5)` for `pu` and `(…, 11, 4)` for `seq`, and record the filename and config alongside. The models directory in the shared folder is empty, so this is tracked as an open item rather than closed.

**You were right about DeepRiPe's window, and checking it exposed a second error of mine that you didn't flag.** The paper confirms 150 nt sequence and 250 nt region. But I also had the coverage backwards in both v1 and v2: **59 is the PAR-CLIP model; the eCLIP model covers ~150 RBPs across K562 and HepG2.** DeepRiPe is a considerably better comparator than I represented, and probably covers most of our 122. The sequence-only ablation is confirmed published, so that flag comes off too.

Your point about the design tension follows directly — native windows are 101 / 150 / 500, three different numbers, so the two principles genuinely cannot coexist. §4.4 now splits this into three experiments: **W1** controlled input at 150 nt with every non-native run labelled an adaptation, **W2** native configurations, and **W3** the 101/251/500 curve for the in-house configs only. I chose 150 nt for W1 because it is DeepRiPe-native and PrismNet's adaptation is a mechanical dense-layer resize; say if you'd rather it were 101.

**On the loss magnitude — I had the direction wrong, not just the precision.** You said the lambdas don't describe effective contribution. Working it out: both terms are mean-normalised over their own support, so "unknowns are 99% of entries" does not make the penalty large. At initialisation, with BCE ≈ ln 2 everywhere, the masked term is ≈ 0.693 × (15 × 0.538 + 0.462) ≈ 5.9 against ≈ 0.69 for the unknown term — about **8.5 : 1 in favour of the masked term**, driven by `lambda_pos = 15`. My "large signal" claim in v2 was unsupported.

I'd still not call it negligible: it's a small persistent downward push on ~121 outputs per sample, and for those outputs it's the only signal they ever get, so it plausibly shapes calibration while contributing little to total loss. Both components are now logged per epoch, and A vs B settles it empirically. Terminology corrected throughout to "unknown-as-negative penalty".

The remaining changes are as you specified. **B vs C** is now the clean causal test of joint learning and A vs C is explicitly disclaimed; D is dropped with the two-orders-of-magnitude cost noted. Locus grouping is primary with the leakage criterion redefined as non-overlap of original genomic intervals, sequence clustering demoted to fallback and independent audit, quarantine for unmapped rows, and a post-split re-audit. The eight motif proteins are a development set, with the confirmatory test on the remaining 114 and all-122 secondary. The shuffle control is a diagnostic rather than a gate. Bootstrap is at component level within protein and proteins as paired units. Hard proteins keep the <0.60 descriptive cutoff plus continuous analysis, and the subgroup CI is reported without being required to exclude zero.

One thing that got worse rather than better: the budget is now **~84 GPU-hours**, up from 75. Dropping D saved less than splitting W1/W2/W3 cost. §10 lists reductions in priority order. I'll bring measurements from the pilot rather than argue the estimate.

Proceeding only to coordinate recovery, split construction and the pilot, as approved. I'll also seek the instructor's view on the §11 pivot before it becomes a live option rather than after.
