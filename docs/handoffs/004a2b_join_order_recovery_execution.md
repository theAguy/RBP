# Task 004A-2B — authorized join-order recovery execution

The project owner authorized one recovery attempt after independent approval
of the bounded join-order correction at `554e9c0`.

Execute exactly once, outside the Codex sandbox, through:

```bash
bash scripts/run_004a2b_join_order_recovery.sh
```

The wrapper requires `554e9c0` as an ancestor and a clean worktree. It
hash-verifies the nine log files from all three previous attempts plus the
preserved Gate-A `STOPPED.json`. It neither modifies nor deletes those files.

This attempt uses new, absent roots:

- output: `artifacts/task004a_rescnn_pilot/004a2_local_smoke_join_recovery/`
- logs: `artifacts/task004a_rescnn_pilot/004a2b_join_recovery_logs/`

On any failure, preserve both roots and do not patch or retry. On success, do
not rerun and do not start Task 004A-3. First reconcile the accepted output
independently and commit only a small sanitized evidence manifest.
