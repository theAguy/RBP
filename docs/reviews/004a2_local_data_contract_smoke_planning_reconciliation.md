# Task 004A-2 planning-review reconciliation

**Verdict:** Approve with bounded corrections.

**Status:** both blocking corrections and the same-boundary hardening are
incorporated in `docs/tasks/004a2_local_data_contract_smoke.md`. Task 004A-2A
synthetic-only implementation may begin; real-data execution remains gated on
implementation review.

## Review boundary

The reviewer read every requested tracked source and only metadata from the
three permitted manifests. No real CSV, FASTA, membership, ignored artifact,
environment, PyTorch execution or checkpoint was opened. The reviewer
independently matched the Task 004A config hash and confirmed that the accepted
membership digest refers to the gzip file itself.

## B1 — development-only count reconciliation

The draft did not say what its train/validation label counts were checked
against. Using whole-dataset totals from `manifests/dataset_audit.json` would
make it possible to derive held-out test counts by subtraction, violating the
hard blindness boundary.

The corrected plan now requires two independent counters over only train and
validation. Their complete per-protein matrices must match exactly, and their
combined aggregate bounds must match the already accepted Task 003B Phase A
manifest. Whole-dataset totals cannot be subtracted, and no test class count
may be computed, inferred, recorded or reported.

## B2 — safe checkpoint-load path before GPU work

Task 004A-1 ran under PyTorch 1.12, which did not exercise the new
`weights_only=True` branch. Deferring that path until Newton could expose a
payload incompatibility only after expensive GPU execution.

The corrected plan requires the local environment to expose the
`torch.load(..., weights_only=...)` interface, reruns the accepted focused
suite there, and records `weights_only_used: true` for every smoke reload.
The environment's actual versions are discovered and frozen rather than
invented. Matching Newton's eventual major/minor is preferred and any later
version difference requires review.

## Additional same-boundary hardening

The plan also now:

- permits reading test component IDs solely for membership integrity;
- requires exactly one set bit in every four-bit CSV base group;
- bounds sampler memory to quota minima plus 513-entry heaps;
- cross-checks Gate A selected-row content digests against Gate B's cache;
- checks exact loss-component identities and a known positive in the updated
  batch;
- gives checkpoint and prediction artifacts explicit smoke roles distinct
  from final/pilot roles;
- compares effective factories with frozen constants, not only caller-created
  config objects;
- fixes numerical threads at exactly four;
- tests macOS/Linux `ru_maxrss` units and names the macOS available-RAM
  source; and
- defers GPU-specific Adam implementation flags explicitly to Task 004A-3.

These changes do not authorize real data, full training, test scoring, GPU
work, a new metric or any scientific choice. They close the local contract
before implementation.
