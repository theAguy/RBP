# Task 003B-2 real validation-pilot acceptance

**Verdict:** accepted. Task 003B-3 remains unstarted and test access remains
unauthorized.

The real pilot used the accepted components-v2 membership, the frozen CSV and
the accepted 500/251/101-nt FASTAs. It fitted on known-label train rows and
scored only known-label validation rows for proteins 33, 53, 82, 84, 85, 86,
107 and 112. Unknown labels were excluded. No test label was parsed, no test
feature was built, and no test prediction was emitted.

All 36 candidate groups (three fitted baselines × three widths × four C
values) converged for all eight proteins. The nine selected C values are frozen
in `manifests/task003b_pilot_003b2.json`. Two final-code executions agree on
every selected C, row identity, label, component, partition, configuration and
AUROC/AP metric. Liblinear probability noise was bounded at
`1.9543448407599584e-05`, below the reviewed `1e-4` repeat tolerance; outputs
were not rounded or rewritten.

## Development-only results

Macro validation AUROC across the eight development proteins:

| Width | Prevalence | GC | 3-mer | 6-mer |
|---:|---:|---:|---:|---:|
| 500 | 0.500 | 0.636 | 0.824 | 0.802 |
| 251 | 0.500 | 0.640 | 0.827 | 0.799 |
| 101 | 0.500 | 0.645 | 0.815 | 0.804 |

These results are encouraging but not final performance estimates. They use
validation data from eight predeclared proteins to select hyperparameters.
They do not compare against the former teammate model and must not be described
as test performance.

The GC-matched sensitivity result is informative: GC-only AUROC falls to about
0.50, whereas the 3-mer and 6-mer baselines remain around 0.75–0.78. On these
development proteins, most of the k-mer discrimination is therefore not
explained by GC alone. This is descriptive evidence, not a significance test.

## Resource decision

Each run completed locally in about 99–100 seconds with peak RSS about 1.08
GiB. The pilot materialized 22,342 development sequences; the largest
one-width feature set occupied 129,662,412 bytes. The final implementation may
remain local if it builds one width at a time, fits one protein at a time and
releases intermediate matrices. GPU or Darwin execution is not justified by
the pilot evidence.

## Next boundary

Task 003B-3 requires an explicit owner authorization to access the test
partition once. Before scoring test, the runner must freeze these selected C
values, revalidate all accepted inputs, refit all 122 proteins on train plus
validation, and verify every fit converged. If any fit fails, test scoring must
remain unstarted.
