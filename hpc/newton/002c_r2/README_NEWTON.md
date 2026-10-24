# Darwin operator card — Task 002C-R2

This directory runs one CPU-only, fixed resource probe through Slurm.  It does
not need a GPU and it cannot run the later full edge-discovery task.

The `hpc/newton` path is a historical compatibility name. CPU-only jobs must
be submitted from the **Darwin** login node; Newton's public GPU infrastructure
rejects them. From the extracted bundle on Darwin:

```bash
bash hpc/newton/002c_r2/01_INSTALL_ENVIRONMENT.sh
# Check your storage quota before submitting. Confirm at least 100 GiB of
# quota headroom for the directory containing this extracted bundle.
quota -s
# On Lustre, when available:
lfs quota -u "$USER" "$(pwd)"
bash hpc/newton/002c_r2/02_SUBMIT_R2_PROBE.sh
bash hpc/newton/002c_r2/03_CHECK_STATUS.sh
# after completion:
bash hpc/newton/002c_r2/04_VERIFY_RETURN.sh
```

If your lab requires an account and partition, set `NEWTON_ACCOUNT` and
`NEWTON_PARTITION` before submission.  The default job asks for 4 CPUs,
96 GiB RAM, 8 hours and no GPU.  If neither quota command reports usable
information, confirm the 100-GiB quota headroom with the cluster administrator
before submitting.  Do not confuse filesystem free space with your personal
or group quota.  Memory and time overrides may only increase the reviewed
96-GiB and eight-hour defaults.

To receive scheduler email at start, completion, or failure, set one address
before submission:

```bash
export RBP_SLURM_MAIL_USER=your-address@example.org
```

The wrapper validates the address and supplies fixed
`--mail-type=BEGIN,END,FAIL` options. Leaving it unset disables email.

Never run the Python module or MMseqs2 directly, never submit the extracted
bundle twice, and never continue into R3.  The wrapper refuses a second
submission.  Slurm sends the launcher an advance signal ten minutes before
the time limit so it can stop its child and package evidence.  Whether the
outcome is SUCCESS or STOPPED, return only the generated ZIP plus its
`.sha256` file.

If `sbatch` rejects the request (for example, because the account or partition
is invalid), the wrapper writes `SUBMIT_FAILED.txt` beside the bundle and
prints the recovery procedure.  First run
`squeue --me --name=rbp-r2-probe` and confirm that no job exists.  Only then
remove the named `SUBMIT_FAILED.txt`, remove its now-empty receipt directory,
correct the account/partition, and submit once.  Never remove a successful
`submission.txt` receipt and never resubmit while any matching job exists.

The full explanation and file map are in
`docs/tasks/002c_r2_newton_hpc_execution.md` in the source repository.
