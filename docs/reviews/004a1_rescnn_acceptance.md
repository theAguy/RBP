# Task 004A-1 ResCNN synthetic/source acceptance

**Verdict:** Approve.

**Accepted implementation:** commit `b442eb4` on branch
`issue-003b-simple-baselines`, including the original implementation in
`721d63b` and the bounded correction reviewed in
`docs/reviews/004a1_rescnn_implementation_review_reconciliation.md`.

The independent reviewer accepted:

- the hash-bound notebook architecture/loss oracles and exact 9,029,562-
  parameter, 500-nt, 122-output ResCNN;
- the three frozen loss configurations and their paired deterministic start;
- checkpoint authentication before deserialization, explicit refusal of the
  former checkpoint and complete current-run identity validation;
- config parsing, data-contract, metrics and transactional-output hardening;
  and
- the reported two repeated focused runs of 36 tests with no real input,
  ignored artifact, former checkpoint, GPU or training access.

The review was static because its host had no PyTorch installation. The test
results are therefore implementation evidence reported by the executor, not
an independently repeated environment-bound run. The suite must be repeated
in the later frozen Newton environment.

The reviewer explicitly authorized Task 004A-1 closure and Task 004A-2
planning. The following remained deferred to 004A-2:

- config-only loss, Adam and scheduler construction;
- independently recomputed per-config paired order evidence;
- unshuffled validation and float32 sigmoid metric semantics;
- real partition-first test-blindness counters and `test_accessed: false`;
- separate proof that every pair of loss configurations changes pre-update
  loss/gradient evidence;
- final-loader epoch binding to the frozen 30 epochs; and
- measured compact-cache runtime and peak memory before GPU packaging.

No Task 004A-2 execution is accepted by this record.
