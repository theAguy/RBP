# Task 002C-R1 components-v2 core — acceptance

**Verdict:** accepted  
**Implementation commit:** `c1d61fb`  
**Correction commit:** `d57a266`

Task 002C-R1 is accepted. The repository now has a synthetic-tested core for
building components from the same direct MMseqs2 search relation used by the
cross-partition leakage audit.

The accepted implementation provides:

- a shell-free components-v2 search command with the frozen audit flags and
  no caller-facing scientific overrides;
- strict streaming parsing and deterministic normalization of direct-search
  edge TSVs;
- fail-closed canonical-universe and normalized-edge validation;
- deterministic connected components over all three protected widths plus
  exact/reverse-complement edges;
- singleton preservation and component IDs derived from sorted members; and
- per-width edge metadata plus a deterministic digest of the normalized
  exact/RC relation.

The planning reviewer independently reran the focused suite after correction:

```text
PYTHONPATH=src python3 -m unittest \
  tests.test_splits_components_v2 \
  tests.test_splits_commands \
  tests.test_splits_components \
  tests.test_splits_membership

Ran 57 tests — OK
```

All tests were synthetic. No real CSV, decoded FASTA, ignored result, network
resource, or real MMseqs2 subprocess was used. The accepted code does not
provide a real-data runner and did not begin resource probing or full edge
discovery.

## Next boundary

Task 002C-R2 must implement and execute a bounded high-memory resource probe
before any full all-vs-all direct search. Task 002C-R3 remains unauthorized
until the probe evidence and projections are reviewed.
