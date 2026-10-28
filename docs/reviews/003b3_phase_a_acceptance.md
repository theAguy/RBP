# Task 003B-3 final Phase A acceptance

**Verdict:** Phase A passed. Phase B test scoring was not started.

Phase A revalidated the accepted pilot, immutable dataset, components-v2
membership and three FASTAs. It parsed known labels only from train and
validation, then fitted the nine frozen logistic configurations independently
for all 122 proteins. It also saved per-protein prevalence, fitted scalers,
coefficients, intercepts and training-derived GC-bin edges for later Phase-B
scoring.

## Convergence and label evidence

- fitting sequences represented by at least one known fitting label: 303,582;
- proteins: 122;
- fitted logistic models: 1,098;
- converged models: 1,098;
- maximum iterations observed: 13 of the 2,000 limit;
- smallest per-protein known fitting set: 806;
- smallest positive fitting count: 388;
- smallest negative fitting count: 408.

Every protein therefore had both fitting classes, and every selected model
converged with a large iteration margin. All saved arrays have their expected
shape, contain finite values, and use positive scaler values. The selected
record rehashes all 33 retained artifacts.

## Resources

The local execution completed in 585.84 seconds (9 minutes 46 seconds) with
peak RSS 6,652,665,856 bytes (about 6.20 GiB). The maximum simultaneous raw
feature storage was 1,768,236,236 bytes for the 500-nt width. The retained
model generation is only 24,560,234 bytes. This is comfortably within the
local host's capacity, so Phase B does not require Darwin or a GPU.

## Test boundary

The Phase-A command did not include `--authorize-test`. Test membership rows
were permitted only as structural partition metadata; test labels were skipped
before parsing and test sequences were not converted into features. The
accepted summary records zero test labels parsed, zero test features built and
zero test predictions. No Phase-B selection record or output exists.

Phase B must revalidate this exact selection record and all model artifacts,
then make the single authorized test-scoring pass. No Phase-B work was
implemented or executed in this checkpoint, as requested by the owner.
