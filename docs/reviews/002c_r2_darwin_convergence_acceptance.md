# Task 002C-R2 Darwin convergence run — acceptance

## Verdict

**Accept R2 as complete, with two explicit planning exceptions for R3. Do not
rerun the resource probe.**

The verified Darwin return completed all three protected widths under the
frozen direct-search settings. Its scheduler-level `FAILED` state reflects an
intentional nonzero exit after recording `REVIEW_REQUIRED`; it is not an
MMseqs2, parser, integrity, memory, timeout, or disk-floor failure.

The bound evidence is recorded in
`manifests/sequence_r2_darwin_convergence_return.json`.

## Results

| Width | Probe search | Linear full search | Conservative full search | Conservative transient disk | Decision |
| ---: | ---: | ---: | ---: | ---: | --- |
| 500 | 13.98 min | 8.42 h | 12.62 h | 44.84 GiB | reviewed exception |
| 251 | 2.21 min | 1.33 h | 2.00 h | 16.28 GiB | pass |
| 101 | 0.46 min | 0.28 h | 0.42 h | 7.34 GiB | pass |

All widths had 100% self-hit recovery, no result-cap saturation, valid
15-column result rows, stable block density, no fatal tool diagnostic, and
about 9.31 GiB observed peak RSS. The combined conservative search projection
is 15.04 hours, below the original 24-hour total gate.

## Reviewed exceptions

The 500-nt conservative time exceeds the former 12-hour per-width threshold
by 0.62 hours (about 5.2%). This is acceptable only with a new R3 batch request
of at least 48 hours, stage checkpoints, and timeout-safe return packaging.

The 500-nt job-owned transient projection is 44.84 GiB, above the original
20-GiB planning threshold. That threshold protected a host with only a 20-GiB
margin between its 100-GiB preflight and 80-GiB live floor. The Darwin run had
about 45 TiB free and the operator confirmed at least 100 GiB headroom. R3 may
therefore proceed only when it rechecks at least 100 GiB headroom before every
width, enforces the 80-GiB live floor, caps job-owned output, runs widths
sequentially, and deletes no accepted evidence without a verified receipt.

No identity, coverage, sensitivity, strand, masking, E-value, result-cap,
width, sample-universe, or thread setting is changed.

## Boundary

R2 produced resource evidence only. The next reviewed deliverable is one
restart-safe R3-R5 workflow: full direct edges, components v2, deterministic
assignment, independent exact/RC audit, all 18 directed similarity audits,
and final split freezing. No baseline or model may run before that workflow
passes.
