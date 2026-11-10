# Task 004A-3C-1 C1-C3 correction review request

Please statically review the bounded correction after commit `def1c35`.

Check only:

1. C1: the solve prefix cannot enter either COMPLETED or STOPPED ZIP content,
   while its path remains recorded and success removes only that exact prefix;
2. C2: tuple-based live `DevelopmentCounts.matrix()` strictly equals the
   accepted JSON only after type canonicalization, and scientific drift still
   fails;
3. C3: bundle partition/account must equal accepted discovery and both values
   are passed to `sbatch` with GRES, node and optional constraint.

Return Approve, Approve with bounded corrections, or Stop. This is static only:
do not run Newton, Slurm, CUDA, Conda, real data, cache or bundle execution, and
do not authorize 3C-2, 3C-3 or 3D.
