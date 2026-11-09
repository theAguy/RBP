# Task 004A-2B — final authorized local execution

The project owner authorized one final local Task 004A-2B attempt after the
bounded prerequisite correction at `15ef4f0` received independent approval.

Execute exactly once, outside the Codex sandbox, through:

```bash
bash scripts/run_004a2b_local_smoke_final.sh
```

The wrapper requires `15ef4f0` as an ancestor, a clean worktree, an absent
scientific output root and an absent third log root. Before real execution it
re-hashes all six files from the two previous stopped attempts. It uses only
macOS-Bash-3.2-compatible syntax and retains the previously reviewed
scientific command unchanged.

New evidence is written only under:

`artifacts/task004a_rescnn_pilot/004a2b_final_execution_logs/`

Scientific output may be written only under:

`artifacts/task004a_rescnn_pilot/004a2_local_smoke/`

On any failure, preserve both locations and do not patch or retry. On success,
do not rerun and do not start Task 004A-3. First perform independent
reconciliation and commit only a small sanitized acceptance manifest.
