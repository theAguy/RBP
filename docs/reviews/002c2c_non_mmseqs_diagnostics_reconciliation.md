# Task 002C-2C planning reconciliation

**Verdict:** approved with one bounded pre-execution correction  
**Reviewed plan:**
`docs/reviews/002c2c_non_mmseqs_diagnostics_review_request.md`  
**Second-review outcome:** the scientific boundary, denominators, diagnostic
asymmetry, and local execution plan are accepted.

## Accepted decisions

1. The former split's leakage result is descriptive. A nonzero result neither
   fails nor changes the new assignment.
2. The new assignment's exact/reverse-complement audits are hard
   zero-violation gates.
3. The required denominators distinguish components, per-width connected
   clusters, train rows, holdout rows, raw pairs, and distinct affected rows.
4. One pinned, deterministic legacy-fold execution plus independent evidence
   reconciliation is proportionate; assignment alone required the separate
   repeated execution.
5. Exact audits at 500, 251, and 101 nt are necessary and sufficient for this
   non-MMseqs checkpoint. They do not replace the later fresh similarity
   searches.
6. Aggregate sanitized evidence is sufficient because any new-split exact/RC
   violation stops the checkpoint rather than being omitted from an accepted
   manifest.

## Required bounded correction

The accepted decode manifest and live generation use:

```text
duplicate_edges_500.json
duplicate_edges_251.json
duplicate_edges_101.json
```

The legacy runner and its synthetic fixture hardcode the nonexistent real-data
name `exact_rc_edges_<width>.json`. The first real legacy diagnostic would
therefore stop before producing a result.

Before real execution, the runner must derive each artifact basename from the
accepted decode-manifest entry and resolve it inside the explicitly supplied
decode-artifact directory. It must continue to enforce that entry's exact
size and SHA-256. The same manifest-derived resolution must be used in both
restart-fingerprint precomputation and real execution. Fixtures must use the
real filename contract.

No file may be copied, renamed, linked, regenerated, or hand-authored to work
around the mismatch. This correction changes file discovery only; it does not
change evidence content or scientific interpretation.

## Execution boundary

After the correction tests pass and the correction is committed, execute
sequentially on the accepted primary assignment root:

1. `legacy_diagnostic`;
2. `exact_audit --width 500`;
3. `exact_audit --width 251`; and
4. `exact_audit --width 101`.

Stop before Task 002C-3. Do not launch MMseqs2, finalize the split, or begin a
baseline/model stage.

