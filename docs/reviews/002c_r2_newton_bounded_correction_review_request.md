# Task 002C-R2N-C1 — bounded Newton correction review request

## Requested verdict

Review only the correction diff from base commit `91af9e0` and return one of:

- **Approve**;
- **Approve with bounded corrections**; or
- **Do not approve**, naming a concrete blocker.

This review authorizes neither a real bundle build nor a Newton submission.
Task 002C-R3 remains unauthorized.

## Why this correction exists

The first Newton planning review approved the scientific design but found
four operational gaps.  This commit addresses only those gaps:

1. **Slurm termination:** `USR1` and `SIGTERM` enter the normal STOPPED-return
   path.  The submit wrapper requests `USR1` ten minutes before timeout, and
   an interrupted supervised child process group is terminated before return
   packaging.  The wrapper rejects memory below 96 GiB and time below eight
   hours.
2. **Exactly-once submission:** the submission receipt directory is created
   atomically without `-p`; its prior existence is a hard stop.  `sbatch`
   uses `--parsable`, and the status script reads the exact returned job ID.
3. **Shared storage:** transient disk is the maximum of filesystem free-space
   drop and the candidate generation's peak size.  Host evidence records
   available `quota -s`/`lfs quota` output, and the operator instructions
   require at least 100 GiB of quota headroom.
4. **Linux-stable live-monitor tests:** fake tools used by live-monitor tests
   remain alive for at least one polling interval.  A regression covers the
   case where unrelated shared-filesystem deletions hide free-space loss.

The same correction also freezes the already accepted seed, decode-manifest
hash and row count in the Newton config validator.  It does not change any
MMseqs2 flag, threshold, sample ID rule, width, target universe or projection
threshold.

## Files to inspect

- `src/rbpbench/splits/newton_002c_r2.py`
- `src/rbpbench/splits/resource_probe_r2.py`
- `hpc/newton/002c_r2/02_SUBMIT_R2_PROBE.sh`
- `hpc/newton/002c_r2/03_CHECK_STATUS.sh`
- `hpc/newton/002c_r2/RUN_R2_PROBE.sbatch`
- `hpc/newton/002c_r2/README_NEWTON.md`
- `tests/test_splits_newton_002c_r2.py`
- `tests/test_splits_resource_probe_r2.py`
- the related documentation diff

## Required Linux verification

Run from a clean Linux checkout of the correction commit:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_splits_resource_probe_r2 \
  tests.test_splits_resource_probe_r2_linux \
  tests.test_splits_newton_002c_r2 \
  tests.test_splits_portable_002c_r2 \
  tests.test_splits_components_v2 \
  tests.test_splits_commands

bash -n hpc/newton/002c_r2/*.sh hpc/newton/002c_r2/*.sbatch
git diff --check 91af9e0..HEAD
```

Confirm specifically that:

- the live-monitor module no longer has the four Linux timing failures;
- the fake-sbatch regressions reject a second submission and downward
  memory/time overrides;
- an actual `SIGTERM` produces a sanitized STOPPED ZIP in the synthetic test;
- no path starts R3 or writes scientific direct edges; and
- the frozen MMseqs2 command remains unchanged.

Do not read the real FASTAs/CSV, build the large archive, install MMseqs2,
submit Slurm work, or run a real binary during this correction review.
