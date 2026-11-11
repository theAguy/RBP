# Task 004A-3C-2 environment acceptance

## Verdict

**Approve.** The bounded recovery completed successfully and the frozen Linux
CUDA environment is accepted for later Task 004A-3C-3 planning. This record
does not authorize cache construction, bundle construction, a GPU smoke, or
full training.

## What happened

The original CPU job `543090` successfully solved and installed its staging
environment, then stopped because final-prefix recreation consulted Conda's
configured `defaults` channels and triggered a non-interactive Terms-of-Service
check. Its evidence and staging prefix were preserved. The reviewed recovery
used that exact staging state and explicit lock; it did not solve or fetch a
package and did not accept channel terms.

Recovery job `544376` completed on Darwin node `protagoras` in 9 minutes 42
seconds with four CPUs, 32 GiB requested memory, about 2.15 GiB peak RSS and no
GPU allocation.

## Accepted environment

- final prefix:
  `/home/guy.assa/.conda/envs/rbpbench-004a3-4acbb5a8ebf2`;
- lock SHA-256:
  `4acbb5a8ebf263a7cfc59975d29620ae03a59416046768b0627ad386cd5a67c8`;
- runtime-manifest SHA-256:
  `ea1938760087ea6e89ca19a68e7147d39a7fe7ad14d35833cd175e895d45cf33`;
- 91 packages; staging and final package JSON are identical;
- Python 3.11.18, PyTorch 2.5.1, CUDA runtime 12.4, cuDNN 9.1 and NumPy 1.26.4;
- exactly 30,772 runtime entries and 6,717,946,054 file bytes;
- complete runtime verification passed before and after the prefix was made
  read-only;
- all five focused suites passed: 112 tests in 63.92 seconds;
- package-cache growth was zero for both recorded cache directories.

The explicit lock contains only MD5-bound HTTPS entries from `pytorch`,
`nvidia` and `conda-forge`; it contains no configured `defaults` entry and no
PyPI package. The effective channel order is frozen accordingly.

## Independent reconciliation

The downloaded ZIP checksum and ZIP integrity pass. Independent local checks
reproduced the lock and runtime-manifest hashes; required byte identity between
the returned and staging locks; required exact staging/final package equality;
recomputed runtime entry/file/symlink/byte totals; verified zero package-cache
growth; and required the exact 22-file sanitized return inventory.

The scheduler accounting reports `COMPLETED`, exit `0:0`, partition `public`,
account `cs`, four allocated CPUs and no GPU TRES. The only stderr content is
an informational Conda tip about conda-pypi; the accepted package list contains
no PyPI package.

## Boundary and retained evidence

The tracked aggregate record is
`manifests/task004a3c2_environment.json`. Row-level data and biological inputs
were never accessed. The prior STOPPED evidence and staging prefix remain
untouched. Removing those multi-gigabyte artifacts requires a separate cleanup
decision after this acceptance is secure.

Task 004A-3C-3 may now be planned separately. It remains unauthorized by this
acceptance record, as do 004A-3D and 004A-4.
