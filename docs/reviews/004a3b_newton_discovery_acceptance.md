# Task 004A-3B Newton discovery acceptance

**Verdict:** Accept the single data-free discovery return. Do not repeat the
discovery. This acceptance does not authorize environment installation,
bundle/cache construction, the CUDA resource smoke or training.

## Execution and evidence

- Execution commit: `e90a26a9fbfc2ac57a83a3d39753f3b2155a5cea`.
- Slurm job: `1492772`, partition `public`, account `cs`.
- The job packaged the return before validation, as designed.
- Slurm then reported `FAILED` because the old validator required a positive
  partition time while the site reported `MaxTime=UNLIMITED`.
- The ZIP checksum and archive integrity passed after download.
- All retained hashes, sizes and accepted aggregate findings are frozen in
  `manifests/task004a3b_newton_discovery.json`.

This is an expected contract mismatch, not a failed hardware discovery. The
raw JSON contains all required hardware, scheduler, storage, operating-system,
channel-reachability and installation-policy evidence.

## Accepted findings

- GPU: NVIDIA L40S, 49,140 MiB, compute capability 8.9.
- Driver/CUDA exposure: 595.91.07 / 13.2.
- Host: x86_64 Ubuntu 22.04.5, glibc 2.35, Python 3.10.12.
- Allocation: four CPUs; about 1.04 TB available RAM at discovery.
- Storage: 45.77 TB filesystem free and 880,554,195,025 bytes of operator-
  evidenced user quota available.
- Required package channels were reachable.
- The approved environment-install location is a CPU job.
- Slurm advertises `gpu:L40`; the assigned runtime device was `NVIDIA L40S`.
  The later smoke must request `gpu:L40:1` and then verify the exact runtime
  model and UUID before opening its cache.
- The public partition reports `MaxTime=UNLIMITED` and
  `PreemptMode=REQUEUE`.

## Bounded scheduler correction

The discovery record must preserve `UNLIMITED`; it must not fabricate a site
limit. A later experiment nevertheless requires a finite stop gate. The
project therefore freezes 43,200 seconds (12 hours) as its own maximum for the
single-seed Task 004A-4 projection and job. This is a ceiling, not an expected
runtime. The 004A-3D smoke remains a four-hour job.

For preemption, 004A-3D remains `--no-requeue` and fails closed with sanitized
STOPPED evidence. Before Task 004A-4 can run on this partition, epoch-level
checkpoint/restart behavior must be implemented, tested and independently
reviewed. No automatic retry is authorized by this acceptance.

## Boundary

Task 004A-3B is closed. The bounded validator/bundle correction receives a
separate static review. Task 004A-3C begins only after that review and a new
owner authorization.
