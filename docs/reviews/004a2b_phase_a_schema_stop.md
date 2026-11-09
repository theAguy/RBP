# Task 004A-2B — prerequisite schema stop

**Attempt start:** 2026-11-09T07:50:42Z

**Attempt end:** 2026-11-09T07:50:47Z

**Starting commit:** `0a90052846e04de33a2e788b86392af46ad0fa28`

**Outcome:** stopped during immutable-prerequisite reconciliation, before
Gate A, FASTA resolution, row interpretation or model computation.

The sandbox-recovery wrapper reached the accepted runner outside the Codex
sandbox. The runner hash-bound its declared prerequisite files, then refused
the accepted Task 003B Phase-A manifest with:

```text
ResCNN004A2RunnerError: Task 003B Phase A development bounds drift
```

The scientific values do not drift. The accepted manifest records
`fitting_sequence_count: 303582`; the Task 004A-2 runner calls the same
quantity `train_plus_validation_rows: 303582`. The other four frozen bound
values also match exactly. The defect is a missing explicit schema-name
translation in the prerequisite verifier.

The wrapper also used the Bash-4-only `declare -A` construct. macOS ships
Bash 3.2, so the wrapper emitted shell compatibility errors before continuing
to the runner. This did not alter scientific inputs or outputs, but it must be
removed before any future wrapper is reviewed.

No Gate-A audit, Gate-B cache, FASTA lookup, paired model update, validation,
checkpoint, output generation, selection record or `STOPPED.json` was
created. The latter is expected because this failure occurred in the
pre-hash/prerequisite boundary. The output root remains absent.

The ignored recovery evidence is preserved under:

`artifacts/task004a_rescnn_pilot/004a2b_recovery_logs/`

| File | SHA-256 |
|---|---|
| `attempt.txt` | `dcbc0730d62a369771297c79fa5bf9956dcd3f13a60369f1ea4778114800cf5f` |
| `stderr_time.log` | `ce641b0c630cb7ee05b8a97b8bd82a80eb8f8f10e9a2ecf791f1b1c29d508494` |
| `stdout.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

The bounded correction may translate only the accepted manifest field name,
retain all frozen values, make the wrapper compatible with macOS Bash 3.2,
and add synthetic/tracked-manifest regressions. It does not authorize another
004A-2B invocation.
