# Task 001B checkpoint B3A acceptance

## Verdict

**Checkpoint B3A is accepted.** Commit `a4f0de3` closes the three final
guarded-path findings from `docs/reviews/001b_b3a_correction_review.md`.
B3B-1 may proceed only under its bounded executor handoff. B3B-2, B4, and all
later checkpoints remain unauthorized.

## Independent acceptance evidence

- Reviewed the complete `8eaae99..a4f0de3` diff and the affected command,
  probe, runner, and regression-test code.
- `git diff --check 8eaae99..a4f0de3` is clean.
- Focused command/probe/final-correction/real-binary verification passed:
  **74 passed**.
- The complete pinned-environment suite passed independently:
  **459 passed in 148.63 seconds**.
- `tests/test_coordinates_real_binaries.py` passed all **7** tests with the
  pinned BWA 0.7.19, minimap2 2.31, and SeqKit 2.13.0 binaries available; no
  test in that file was skipped.
- The worktree was clean before this acceptance documentation was added.
- No network request, NCBI source, real CSV/B2 FASTA read, human-reference
  derivation, or human-genome indexing was performed by this review.

## Accepted final corrections

### B3A-F1 — stable restart fingerprint

`canonical_probe_commands()` is now the single path-independent command
semantics representation used by both accepted `probe.json` fingerprints and
restart recomputation. Exact attempt-specific argv and paths remain in tool
provenance. The real runner-level regression proves that an unchanged restart
skips without a subprocess or new generation, while changed Git or binary
identity forces execution.

### B3A-F2 — live shared build budget

Every retained byte from older probe generations is charged before the first
new writer. BWA, minimap2, and SeqKit stdout plus stderr are then charged
immediately and exactly once to both the probe sub-budget and the shared
per-build budget. Each following writer receives the reduced remaining cap.
The reproduced three-writer overflow and retained-generation retry cases now
fail closed and discard the rejected candidate.

### B3A-F3 — exact per-contig evidence

The current reference is streamed into an observed accession-to-length map.
Malformed, empty, and duplicate headers and sequence-before-header are
rejected; the observed map must equal accepted `contig_lengths` exactly.
`Ltotal` and largest-contig selection are derived from this verified map. The
preserved-total redistribution case is now rejected.

## Non-blocking coverage note

Not every fingerprint input has a separate full-CLI behavioral test. The
pure fingerprint sensitivity suite covers every declared input, while the
full CLI tests exercise unchanged skip plus representative Git-commit and
binary-identity invalidation. The shared helper at both production call sites
and the passing complete suite make this sufficient for B3A acceptance.

## Next gate

Only B3B-1 is opened: verified GRCh38.p14 source acquisition, deterministic
filtered-reference derivation, a sanitized evidence manifest, and a review
stop. No index or probe execution is authorized until that evidence is
accepted and a separate B3B-2 handoff is issued.
