# Task 003B-2 pilot numerical-reproducibility correction

Exploratory repeated real pilot runs selected the same nine C values, produced
the same 96 reported AUROC/AP rows, and emitted the same prediction identities,
labels, components and partitions. Their raw probability scores differed by at
most `8.786459947202063e-06`; one converged fit used 9 versus 10 iterations.
One non-selected candidate's macro validation AUROC differed by
`1.8622528790146475e-06`. Final accepted-code repeats again had exact selected
C values, identities and AUROC/AP rows, but 27 of 50,388 probabilities exceeded
the provisional `1e-5` score bound; the maximum was
`1.9543448407599584e-05`. Test labels and test features remained untouched.

This is bounded `liblinear` floating-point behavior, not scientific drift. The
repeat gate now requires all scientific decisions and identity fields exactly,
while allowing at most `1e-4` absolute per-row score difference and `5e-6`
metric difference. The probability tolerance is deliberately an order of
magnitude above the observed solver noise, while remaining irrelevant to the
rank-based AUROC/AP results, which were exact. Iteration differences are
disclosed. The comparison never
rounds or rewrites model output, and any selected-C, row, label, partition,
component, configuration, convergence, or test-boundary difference still
fails closed.
