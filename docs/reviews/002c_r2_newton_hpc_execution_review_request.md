# Task 002C-R2N — Newton HPC execution review request

## Requested verdict

Review the Newton-specific implementation and return one of:

- **Approve**;
- **Approve with bounded corrections**; or
- **Do not approve**, with concrete blockers.

This review authorizes neither a real Newton run nor R3.  It reviews only the
Linux/Slurm adaptation and the offline operator workflow.

## Scientific context

Read, in order:

1. `docs/PROJECT_ROADMAP.md`
2. `docs/reviews/002c3_cross_partition_failure_and_component_rebuild_plan.md`
3. `docs/tasks/002c_r1_component_rebuild_implementation.md`
4. `docs/reviews/002c_r1_component_rebuild_acceptance.md`
5. `docs/tasks/002c_r2_direct_search_resource_probe.md`
6. `docs/reviews/002c_r2_resource_probe_implementation_acceptance.md`
7. `docs/tasks/002c_r2_newton_hpc_execution.md`

## Code and scripts to inspect

- Linux monitor additions: `src/rbpbench/splits/resource_probe_r2.py`
- Newton launcher: `src/rbpbench/splits/newton_002c_r2.py`
- environment installer:
  `hpc/newton/002c_r2/01_INSTALL_ENVIRONMENT.sh`
- runtime receipt: `hpc/newton/002c_r2/write_runtime_receipt.py`
- submit wrapper: `hpc/newton/002c_r2/02_SUBMIT_R2_PROBE.sh`
- Slurm job: `hpc/newton/002c_r2/RUN_R2_PROBE.sbatch`
- monitor/return scripts: `hpc/newton/002c_r2/03_CHECK_STATUS.sh` and
  `hpc/newton/002c_r2/04_VERIFY_RETURN.sh`
- bundle builder: `scripts/build_002c_r2_newton_bundle.py`
- tests: `tests/test_splits_resource_probe_r2_linux.py` and
  `tests/test_splits_newton_002c_r2.py`

## Questions for the second reviewer

1. Are the scientific command, seed, three widths, query count, target
   universe and gates unchanged from accepted R2?
2. Is the Linux translation of RSS/swap/available-memory evidence fail-closed
   and proportionate?  Identify any case where a missing measurement passes.
3. Does the launcher guarantee execution inside Slurm rather than the login
   node and bind exactly four CPUs plus at least 64 GiB allocated memory?
4. Is 96 GiB and eight hours a safe default allocation for R2 without
   changing scientific behavior?  Should only upward operational overrides
   be allowed?
5. Does the conda setup record enough Linux-specific provenance (explicit
   lock, package list, Python path/version, MMseqs2 path/version/hash) and
   does the job revalidate it?
6. Does any path permit R3, direct-edge writing, component construction,
   assignment, leakage audit, a stage selector or automatic retry?
7. Can any preexisting output or unlisted bundle file be silently adopted?
8. Does every failure still attempt a small sanitized STOPPED return, and are
   FASTAs/raw MMseqs2 results excluded?
9. Are account/partition selection and upload/storage instructions suitable
   for Newton without hardcoding a lab-specific value?
10. Are there shell portability, Slurm-variable, conda-channel or quota issues
    that would prevent a one-shot unattended run?

## Review boundary

Do not access the real FASTAs, run MMseqs2, install an environment, build the
real archive, submit to Newton or start R3 during this review.  Static review
and synthetic tests only.
