# Newton operator card — Task 002C-R2

This directory runs one CPU-only, fixed resource probe through Slurm.  It does
not need a GPU and it cannot run the later full edge-discovery task.

From the extracted bundle on the Newton login node:

```bash
bash hpc/newton/002c_r2/01_INSTALL_ENVIRONMENT.sh
bash hpc/newton/002c_r2/02_SUBMIT_R2_PROBE.sh
bash hpc/newton/002c_r2/03_CHECK_STATUS.sh
# after completion:
bash hpc/newton/002c_r2/04_VERIFY_RETURN.sh
```

If your lab requires an account and partition, set `NEWTON_ACCOUNT` and
`NEWTON_PARTITION` before submission.  The default job asks for 4 CPUs,
96 GiB RAM, 8 hours and no GPU.

Never run the Python module or MMseqs2 directly, never submit the extracted
bundle twice, and never continue into R3.  Whether the outcome is SUCCESS or
STOPPED, return only the generated ZIP plus its `.sha256` file.

The full explanation and file map are in
`docs/tasks/002c_r2_newton_hpc_execution.md` in the source repository.
