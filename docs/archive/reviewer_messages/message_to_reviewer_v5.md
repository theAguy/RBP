All seven accepted. v5 attached. Agreed that the next gate should be empirical — this is the last prose revision I'll ask you to read before the §9 artifacts.

**Correction 1 was a real arithmetic error, and fixing it simplified E2.** Recomputed with explicit boundaries:

| Count | Proteins |
|---|---|
| n = 2,000 exactly | **57** |
| n = 1,999 | 11 |
| 1,000 ≤ n < 2,000 | 43 |
| n < 1,000 | 22 |
| **Total** | **122** |

**No protein exceeds 2,000.** My "68 at the 2,000 cap" silently merged the 57 sitting at exactly 2,000 with 11 sitting one below — and my bin label "2,000–4,000" was a half-open interval that in practice contained only the boundary value. Both artefacts of sloppy wording over a correct computation, which is the worse kind of error because the table looked fine.

The frozen boundaries are now those in the table, and E2 resolves to **two networks**: `high` (n = 2,000, 57 proteins) and `low` (n < 2,000, 65 proteins — the 43 plus the 22 below DeepRiPe's lowest bin, assigned down).

**On point 3, you're right and it propagates further than the pilot section.** E2 is two models, not one 122-output model. §5.1 now carries a model-count column — A, B and E1 are one model each; E2 is two; C and F are 122 each — because the operational claim that the in-house approach needs one model is only meaningful against accurate counts for everyone else. The pilot text now says all grouped networks are trained and the collection covers 122.

**On point 2, I'd stated matched supervision where there was none.** H1b is split: **H1b-i** is B@150 vs E1@150 and C@150 vs F@150, matched window and matched supervision, supporting an architecture claim; **H1b-ii** is A@150 vs E1/F, matched window only, supporting a pipeline claim and explicitly not stated as controlling for supervision. Both reported, interpretations kept apart. §5.1 now has a table listing each comparison with what it does and does not control.

**Point 4 was a dangling reference — §4.2 pointed at a §5.3 minimum that didn't exist.** Now specified before mapping: ≥100 positives and ≥100 known negatives per protein in every fold's test partition, both classes present in every fold, and §4.2 acceptance thresholds for overall retention (≥80%, with 60–80% proceeding under caveat and <60% falling back to clustering) and for the positive-vs-negative retention gap (≤5 points, since differential retention by class would itself manufacture a confound). The primary sample is reported as **"eligible confirmatory proteins, n = X"** rather than asserted as 114, ineligible proteins are listed with their characteristics, and a sensitivity analysis re-runs the comparison at a relaxed ≥50 minimum.

**Point 5 accepted in full.** Clear margin now requires ≥0.02 **and** CI lower bound >0; a point estimate with a CI crossing zero is inconclusive, not supportive. H3 can only conclude "neutral" if the CI lies entirely within [−0.02, +0.02], otherwise inconclusive. H4 has a concrete primary contrast, A@500 vs A@101, with the same three-way structure and A@251 as the dose-response intermediate.

**Point 6 — three seeds, and confirmatory W3 restricted to A.** You're right that B and C window curves answered interaction questions no hypothesis asks. **The budget falls to ~80 h**, since dropping those more than offsets three seeds. Per-protein results are averaged across seeds before the protein-level comparison, with seed variability reported separately.

**Point 7 accepted.** The supported wording is *"the submitted pipeline outperforms our retrained implementations of the published methods at their respective operating points"*, and the qualification travels with the claim into the abstract and every table. Baselines are now window-matched — 500 nt features for A@500 comparisons, 150 nt for the controlled comparison — which I'd missed entirely and which would otherwise have favoured whichever models shared the baseline's window. And §6.4 now says expression/coverage matching happens only if appropriate K562 tracks are obtained; coordinates alone don't supply them, and they're listed in §13 as not obtained.

Next from me is artifacts, not prose: mapping-retention report, frozen fold composition with the post-split leakage re-audit, exact E1/E2 specification, pilot learning curves and measured runtime.
