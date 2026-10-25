# Darwin operator card — Task 002C-R3–R5 real-binary smoke

This package runs exactly two tests on generated tiny sequences. It contains
no real dataset, does not start the R3–R5 workflow, and does not use a GPU.

On the Darwin login node, after extracting the archive:

```bash
cd RBP_Task002C_R3R5_Darwin_Smoke_*
export RBP_SLURM_MAIL_USER='YOUR_EMAIL_ADDRESS'
bash hpc/darwin/002c_r3r5_smoke/01_VERIFY_PACKAGE_AND_ENV.sh
bash hpc/darwin/002c_r3r5_smoke/02_SUBMIT_SMOKE.sh
```

The submission requests 4 CPUs, 24 GiB RAM, two hours, and no GPU. It sends
email at job start, end, or failure. Disconnecting SSH does not stop it.

Later, check and verify the return:

```bash
bash hpc/darwin/002c_r3r5_smoke/03_CHECK_STATUS_AND_RETURN.sh
```

When the script says `PASSED`, download the printed `.zip` and `.zip.sha256`
files. A failure is a stop: do not rerun or alter memory, commands, tests, or
the environment without review.
