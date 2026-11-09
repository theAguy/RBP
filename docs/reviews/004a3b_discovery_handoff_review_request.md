# Task 004A-3B discovery handoff — static review request

**Requested verdict:** Approve, Approve with bounded corrections, or Stop.

This is a static review of the prepared, data-free, single-shot discovery
handoff. Do not run scripts, query Newton, install anything, access real data,
submit Slurm or authorize execution.

## Required reading

1. `docs/reviews/004a3a_acceptance.md`
2. `docs/tasks/004a3_newton_gpu_resource_smoke.md`
3. `docs/handoffs/004a3b_newton_discovery_execution.md`
4. `hpc/newton/004a3/00_SUBMIT_DISCOVERY.sh`
5. `hpc/newton/004a3/01_DISCOVERY.sbatch`
6. `src/rbpbench/discovery_004a3.py`
7. the bounded hardening and handoff diff after `89b34e5`, including B1 after
   `0aedf2e`

## Review questions

1. Does the submit wrapper reject a non-positive/non-numeric byte quota, an
   unset `USER` or `HOME`, and an unset/malformed reviewed partition before it
   can invoke `sbatch`? Does it pass the partition and optional account as
   separate quoted scheduler arguments?
2. Can discovery evidence still be written if `USER` or `HOME` is absent from
   the compute-job environment, using only safe standard-library fallbacks?
3. Does discovery record requested and allocated partition/account evidence,
   and does validation refuse any requested/allocated mismatch?
4. Does the runbook bind exact execution commit `e90a26a9...`, require a clean
   tree and absent `discovery/`, and separate preparation from authorization?
5. Are the human decisions—reviewed GPU partition, optional required account,
   site-approved install location and current numeric user quota—explicit,
   evidence-backed and required before submit?
6. Are the submission, monitoring, expected-output, checksum and return steps
   complete enough for a one-shot operator without an LLM?
7. Do the stop rules prevent retry, script editing, installation, bundle/cache
   creation, GPU smoke execution and any automatic later stage?
8. Is the return-review checklist sufficient to freeze the later environment,
   GPU-model request, Slurm limit and storage gates without biological data?
9. Does the handoff remain entirely data-free, single-shot and outside the
   authorization boundary of 004A-3B execution?

Assess the reported regressions on exact parent `89b34e5`: the old submit
wrapper called a stub `sbatch` for both `10G` quota and missing `USER`, and the
old discovery heredoc directly indexed `os.environ["USER"]` and
`os.environ["HOME"]`. Do not authorize execution in the verdict.

Also assess the B1 regressions on exact parent `0aedf2e`: the old wrapper
called a stub `sbatch` with no partition when `RBP_SLURM_PARTITION` was unset,
and the old validator accepted requested/allocated partition and account
drift. The corrected regressions pass on execution commit `e90a26a9...`.
