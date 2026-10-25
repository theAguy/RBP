# Darwin operator card — Task 002C-R3–R5 (components-v2 split)

One CPU-only package runs the whole reviewed workflow: full direct-edge
discovery (500/251/101 nt), components v2, whole-component assignment, an
independent exact/RC audit, all 18 fresh directed MMseqs2 audits (with one
pre-authorized remediation cycle), and final verification.  It trains no
model and needs no GPU.

From the freshly extracted, checksum-verified bundle on the Darwin login node:

```bash
bash hpc/darwin/002c_r3r5/01_VERIFY_ENVIRONMENT.sh   # accepted R2 environment; never reinstalls
quota -s                                             # confirm >= 80 GiB quota headroom
export RBP_SLURM_MAIL_USER=you@example.org           # required e-mail notifications
bash hpc/darwin/002c_r3r5/02_SUBMIT_R3R5.sh           # submits once (or one restart chain)
bash hpc/darwin/002c_r3r5/03_CHECK_STATUS.sh
bash hpc/darwin/002c_r3r5/04_VERIFY_RETURNS.sh        # after the e-mail says the job ended
```

* The bundle directory needs >= 140 GiB free before the 500-nt stage (80-GiB
  floor + 60-GiB job-owned ceiling) and >= 80 GiB quota headroom.  If quota
  is not machine-readable, the submit script asks you to confirm with
  `RBP_CONFIRM_NO_QUOTA_BELOW_80GIB=yes`.
* Defaults: partition `public` (override `DARWIN_PARTITION`), 96 GiB
  (`DARWIN_MEMORY` may only increase), optional `DARWIN_ACCOUNT`.  If the
  partition allows 20–48 h, the script automatically submits a dependency
  chain totalling >= 48 h; below 20 h it refuses.
* Every attempt writes one numbered return ZIP plus `.sha256` under
  `returns/`.  Upload **all** of them; `04_VERIFY_RETURNS.sh` checks the
  series and prints the current state.
* If a return says the stop is resumable (time, signal, or a corrected
  free-space/memory/quota condition), fix the condition and run
  `05_RESUME_R3R5.sh` once.  It refuses after scientific, integrity, tool or
  frozen-limit stops and after success — those need review, not a retry.

Never run MMseqs2 or the Python module by hand, never edit files inside the
bundle, and never start baselines or models from this package.
