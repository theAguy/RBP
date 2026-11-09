# Task 004A-2B — one-shot local real-data smoke handoff

## Authority and boundary

This handoff is prepared after Task 004A-2A acceptance. It does **not** itself
authorize execution. Run it only after the project owner explicitly says:

> Authorize the single Task 004A-2B local real-data invocation.

The execution is one local CPU invocation on the project Mac. It is a
data-contract/resource smoke, not training and not a performance experiment.
It must not score test rows, select a model, start Task 004A-3, use a GPU,
open the former checkpoint or retry after any failure.

## Frozen implementation

- Accepted correction: `16e77e6`
- Environment: `/opt/miniconda3/envs/rbpbench-rescnn-004a2`
- Entrypoint: that environment's `rbp-rescnn-smoke`
- Wrapper: `scripts/run_004a2b_local_smoke.sh`
- Output: `artifacts/task004a_rescnn_pilot/004a2_local_smoke/`
- Non-overwriting console/resource evidence:
  `artifacts/task004a_rescnn_pilot/004a2b_execution_logs/`

The wrapper requires a clean worktree, the accepted correction as an
ancestor, all immutable inputs as plain in-repository files, an absent output
root and an absent execution-log root. The two absent roots make the wrapper
one-shot. It creates only their ignored parent directory before launch.

## Exact execution

From the repository root, and only after explicit authorization:

```bash
bash scripts/run_004a2b_local_smoke.sh
```

Do not interrupt the process. The runner itself:

1. binds the clean source tree and frozen environment before real-input
   access;
2. hash-validates every immutable input;
3. resolves the accepted 500-nt FASTA through the decode manifest;
4. streams all 361,180 rows through Gate A while interpreting only
   train/validation fields;
5. independently streams Gate B and materializes only 513 train plus 513
   validation rows;
6. runs primary/repeat one-update smoke tests for all three loss
   configurations with the real CNN;
7. authenticates checkpoint reloads, writes validation-only smoke predictions
   and atomically selects the complete generation.

## Stop behavior

On any nonzero exit:

- do not patch, delete, rename or rerun;
- preserve both paths printed by the wrapper;
- report the exit status and provide `attempt.txt`, `stdout.log`,
  `stderr_time.log` and `STOPPED.json` if it exists;
- remember that environment/resource/input-hash failures occur before the
  runner's stop-record boundary, so the console logs are authoritative; and
- a Ctrl-C may remove the candidate without writing `STOPPED.json`, which is
  why interruption is forbidden.

## Successful return

Success requires exit status 0, an accepted selection record, no
`STOPPED.json`, and the wrapper's final completion message. Do not rerun and
do not start 004A-3. Return the complete ignored output and execution-log
directories for independent reconciliation. Only after that reconciliation
may one small sanitized manifest be written and reviewed.
