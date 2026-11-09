# Task 004A-2B — authorized pre-hash sandbox recovery

The project owner authorized one recovery attempt after the documented
pre-hash sandbox stop in
`docs/reviews/004a2b_prehash_sandbox_stop.md`.

This recovery changes only the process boundary: the same accepted CLI,
inputs, hashes, model, numerical settings, gates and output root run outside
the Codex sandbox so `/usr/sbin/sysctl -n hw.memsize` and `vm_stat` can read
the host resources. It does not weaken or alter a scientific setting.

Execute exactly once through:

```bash
bash scripts/run_004a2b_local_smoke_recovery.sh
```

The recovery wrapper verifies the hashes of all three original stop logs,
requires the scientific output root and recovery-log root to be absent, and
writes new evidence only under:

`artifacts/task004a_rescnn_pilot/004a2b_recovery_logs/`

It must itself be launched outside the sandbox. On any failure, preserve all
evidence and do not retry. On success, do not start Task 004A-3; return both
the selected 004A-2 output and recovery logs for independent reconciliation.
