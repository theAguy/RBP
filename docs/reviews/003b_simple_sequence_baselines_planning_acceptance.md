# Task 003B simple sequence baselines — planning acceptance

**Verdict:** approved with bounded corrections

**Accepted corrections:**

1. A candidate C is eligible only when all eight development-protein fits
   converge. The final run fits and verifies every model before any test label,
   feature or score is accessed.
2. Baseline and window differences in Task 003B are descriptive only;
   component-aware inference is deferred to the later paired comparison.
3. Fitting rows are exactly a protein's known-positive and known-negative rows
   in the fitting partition. GC quantiles use NumPy's linear method, collapsed
   duplicate edges and a frozen right-closed bin rule.

The review also requested two non-scientific consistency updates, now applied:
the implementation plan names the deterministic prevalence baseline rather
than random prediction, and the data contract includes component, partition,
label and configuration fields in row-aligned prediction artifacts.

No baseline, split, width, development protein, metric or test boundary was
changed. Task 003B-1 synthetic implementation may begin. No real CSV, accepted
FASTA, membership or test artifact was opened during planning review.
