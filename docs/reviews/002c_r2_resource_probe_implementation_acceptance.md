# Task 002C-R2 guarded resource-probe core — acceptance

**Verdict:** accepted for portable-package preparation  
**Implementation commit:** `8de909b`  
**Correction commits:** `e71402c`, `b554a4b`

The synthetic R2 core is accepted. It provides a fixed three-width,
query-subset/full-target resource-probe workflow without any path to R3 full
edge discovery.

The planning reviewer independently reran the focused suite:

```text
PYTHONPATH=src python3 -m unittest \
  tests.test_splits_resource_probe_r2 \
  tests.test_splits_components_v2 \
  tests.test_splits_commands \
  tests.test_splits_002c_guarded_exec

Ran 94 tests — OK
```

Accepted safeguards include:

- fixed `probe_500`, `probe_251`, and `probe_101` stages only;
- deterministic label-blind 10,000-ID selection and full-target validation;
- frozen direct-search arguments and four-thread cap;
- bounded, query-grouped result parsing with self-hit, cap, row-density, and
  byte-density checks;
- immediate warning stops and no automatic retry/progression;
- live and post-reap RSS, disk, temporary-output, swap, memory-pressure, and
  timeout gates;
- whole-width transient-disk and conservative retained-output projections;
- transactional selected records and a sanitized return-summary schema; and
- explicit exclusion of direct-edge writing, component construction,
  assignment, audit, and R3 execution.

All tests used generated tiny FASTAs and a fake executable only. No real CSV,
decoded FASTA, ignored artifact, real MMseqs2 binary, network resource, or
portable package was used.

## Remaining package boundary

Before the real 64-GiB execution, a portable launcher must bind and verify the
accepted native arm64 MMseqs2 binary/hash, the locked environment, the decode
manifest, and all three decoded FASTA hashes. It must build one immutable
offline bundle, perform a fresh package verification, run R2 only, and always
emit a small SUCCESS/STOPPED return ZIP. That work requires a dedicated
handoff and review; R3 remains unauthorized.
