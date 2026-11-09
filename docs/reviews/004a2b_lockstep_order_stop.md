# Task 004A-2B — Gate-A lockstep-order stop

**Attempt start:** 2026-11-09T08:24:27Z

**Attempt end:** 2026-11-09T08:24:33Z

**Starting commit:** `962c1bebcbc3841c678c26e94a35b3071cac950e`

**Outcome:** stopped at the start of Gate A; no retry was performed.

All nine immutable inputs, including the accepted membership and 500-nt
FASTA, matched their frozen sizes and SHA-256 hashes. The runner then stopped
at index 2 with:

```text
ResCNN004A2DataError: lockstep ID mismatch at 2: 'row_10', 'row_2', expected 'row_2'
```

The accepted membership is serialized in lexical sample-ID order
(`row_0`, `row_1`, `row_10`, ...). The accepted FASTA and implicit CSV IDs are
serialized in numeric row order (`row_0`, `row_1`, `row_2`, ...). The Gate-A
implementation incorrectly required these independently accepted artifacts to
have the same physical row order instead of joining their canonical IDs.

The sanitized stop record proves:

- `stage: gate_a_audit`;
- `test_accessed: false` and every test-field/tensor/prediction counter is 0;
- `selection_record_written: false` and `retry_authorized: false`;
- the candidate generation directory is empty; and
- no Gate B, model update, validation, checkpoint or prediction ran.

Preserved ignored evidence:

| File | SHA-256 |
|---|---|
| `004a2b_final_execution_logs/attempt.txt` | `f3becc0cebf47eb0eba26259a3a1dae10e2a44b0785ea60433ea3652295f2697` |
| `004a2b_final_execution_logs/stderr_time.log` | `f916e23735a01628768a7dc15938587a59fc3ae644fe236758145bc5f9bebdd3` |
| `004a2b_final_execution_logs/stdout.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `004a2_local_smoke/STOPPED.json` | `4b41db852867bd67558792c5b386be499504db894c58a1ba78c87340a6bf4909` |

This is an orchestration/join-order defect, not evidence of corrupted data,
label disagreement, sequence disagreement or model failure. Any correction
requires a separate bounded review. The stopped output and evidence must be
preserved; this attempt must not be rerun.
