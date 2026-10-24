# Task 002C-R2N — Darwin/Linux Slurm execution of the guarded resource probe

The `newton` names in code and package paths are retained for compatibility
with the already-reviewed adapter. The Technion public Newton cluster rejects
CPU-only jobs; the actual CPU probe is submitted from Darwin, whose shared
home directory exposes the same package and environment.

## Purpose and current scientific state

The project is building a leakage-safe train/validation/test split before any
model comparison.  The first split grouped sequences through MMseqs2 cluster
membership, but a fresh directed audit found 4,792 qualifying 500-nt
train-to-validation similarities.  Those hits connected 1,351 old components
through 737 component-to-component links.  The old split is therefore not
safe under the frozen direct-search relation.

The accepted correction is **components v2**:

1. search all sequences against all sequences at 500, 251 and 101 nt;
2. retain every direct qualifying pair at each width;
3. union those pairs with exact/reverse-complement pairs;
4. take connected components of that complete relation;
5. assign whole components to train/validation/test; and
6. rerun the fresh leakage audits before freezing the split.

The synthetic components-v2 implementation (R1) is accepted.  Before the
large all-vs-all edge discovery (R3), R2 runs a deterministic 10,000-query
subset against the complete 361,180-sequence target at each width.  R2
measures time, memory, disk and output density and projects the full R3 cost.
It creates no scientific component edges and cannot continue into R3.

The Apple-Silicon portable R2 package was valid, but the collaborator run
stopped before MMseqs2 because only 90.76 GiB of disk was free, below the
frozen 100-GiB gate. Darwin provides the suitable scheduled CPU/Linux host. This
task adapts only the execution environment and resource monitors; it does not
change the scientific relation, sample, widths, thresholds or stop rules.

The first Darwin execution reached and cleanly completed the 500-nt MMseqs2
search, then stopped because the original text guard mistook normal verbose
parameter and internal-command output for a split warning. The corrected
policy does not infer failure from words in paths or command echoes. It stops
on nonzero tool exits and concrete OOM, cannot-fit, truncation, multi-part or
split-count diagnostics. Generic `Warning:` lines are retained in the step
record, raw logs and return summary for end-of-run review, but do not alone
discard a complete probe. This reduces avoidable handoffs without weakening
objective resource and integrity gates.

The second Darwin execution passed the corrected diagnostic guard, completed
the 500-nt search and `createtsv`, then stopped in the Python result parser.
Real MMseqs2 18.8cc5c emitted 15-column alignment rows, while the synthetic
fixture had taught the parser to require exactly two columns. The corrected
contract extracts query/target from the first two fields, treats all trailing
fields as opaque evidence, counts the complete raw row for resource
projection, and reports the observed column-count histogram. The exact first
real row is now a regression fixture, and the future R3 raw-edge parser uses
the same endpoint rule while keeping normalized edge artifacts strictly
two-column. No threshold, search flag, gate or sample changed.

## Frozen scientific behavior

The Darwin run uses the accepted implementation in
`src/rbpbench/splits/resource_probe_r2.py` and the command builder in
`src/rbpbench/splits/commands.py`.

- stages, in order: `probe_500`, `probe_251`, `probe_101`;
- the same deterministic 10,000 canonical IDs at all widths;
- seed: `20260925`;
- target: all 361,180 decoded sequences at each width;
- identity: 0.90;
- coverage: 0.80 at 500 nt, 0.95 at 251 and 101 nt;
- `--cov-mode 0 --max-seqs 361180`;
- `--search-type 3 --strand 2 --alignment-mode 3`;
- `-e 1000 --mask 0 -s 7.5`;
- four MMseqs2 threads; and
- MMseqs2 version `18.8cc5c`, Linux conda build `hd6d6fdc_0`.

The accepted decoded FASTAs remain bound to
`manifests/sequence_decode_002b2.json` (SHA-256
`d9826b471ef3f12539eaf51be5c21ba8be20190f3d7c6042143e839d6bb0a7b3`).
The package verifies its complete inventory before opening a FASTA.

## Frozen gates

The core R2 gates are unchanged:

- at least 64 GiB installed/node RAM;
- at least 24 GiB available RAM before and throughout every child;
- at least 100 GiB free disk before a width and 80 GiB throughout;
- at least 100 GiB of confirmed user/group quota headroom before submission;
- at most 10 GiB temporary/output growth per width;
- at most two hours per probe width;
- swap growth at most 2 GiB;
- no concrete MMseqs2 OOM, cannot-fit, truncation, multi-part or greater-than-one
  database-split diagnostic (generic warnings are retained for review);
- conservative projected RSS at most 48 GiB;
- conservative projected retained output at most 25 GiB total;
- conservative projected transient disk at most 20 GiB; and
- conservative projected time at most 12 hours per width and 24 hours total.

Darwin additionally must provide exactly four Slurm CPUs and at least 64 GiB
of allocated memory.  The submission default is 96 GiB, providing headroom
without changing a scientific parameter.  The job is CPU-only: MMseqs2 in
this workflow does not use the GPU.  The wrapper rejects any memory override
below 96 GiB or time override below eight hours.

## Linux operational adaptation

The original R2 monitor used macOS `sysctl`. The Linux/Slurm adapter adds:

- process-tree RSS from portable `ps` columns;
- swap use from `/proc/meminfo`;
- Linux `MemAvailable` before, during and after every child; and
- raw `/proc/pressure/memory` PSI text when available.

An unavailable RSS, available-memory or swap measurement stops the run.  The
24-GiB available-memory floor is enforced live on Linux.  Slurm allocation
memory is verified independently from physical node memory.

Transient disk is measured conservatively as the larger of the observed
filesystem free-space drop and the peak size of the probe's own candidate
generation.  This prevents unrelated deletions on shared storage from hiding
the probe's growth.  Host preflight also retains `quota -s` and `lfs quota`
diagnostics when those commands exist; because cluster storage policies vary,
the operator still confirms quota headroom before submitting.

## Deliverable layout

The Linux/Slurm bundle is built locally by
`scripts/build_002c_r2_newton_bundle.py`.  It contains only the R2 source
closure, the accepted decode manifest, the three accepted FASTAs and:

- `hpc/newton/002c_r2/01_INSTALL_ENVIRONMENT.sh`
- `hpc/newton/002c_r2/02_SUBMIT_R2_PROBE.sh`
- `hpc/newton/002c_r2/RUN_R2_PROBE.sbatch`
- `hpc/newton/002c_r2/03_CHECK_STATUS.sh`
- `hpc/newton/002c_r2/04_VERIFY_RETURN.sh`
- `hpc/newton/002c_r2/write_runtime_receipt.py`
- `src/rbpbench/splits/newton_002c_r2.py`
- `README_NEWTON.md`

The environment installer uses an existing conda when available. Otherwise it
downloads the specifically pinned official Linux x86-64 Miniconda
`py311_26.9.3-0` installer, verifies its published SHA-256, and installs it in
a private user prefix without modifying shell startup files. It then creates
a new conda environment with Python 3.11 plus the unique linux-64 MMseqs2
18.8cc5c build `hd6d6fdc_0` from only
conda-forge/bioconda. It records the exact Linux
package lock and the exact MMseqs2 binary SHA-256.  The batch job revalidates
that receipt and binary before reading a FASTA.

## Operator procedure on Darwin

### 1. Connect and choose storage

Connect to `darwin.cs.technion.ac.il` over SSH (Technion VPN is required when
off campus), or use `132.68.38.100`. Do not run the probe on the login node.
Copy the verified bundle archive and its `.sha256` file to a location
with at least 100 GiB free and sufficient user quota. The operator may use
the shared home directory or an authorized lab volume.

Before extraction or submission, inspect quota as supported by the selected
filesystem:

```bash
quota -s
lfs quota -u "$USER" /the/selected/storage/path
```

Proceed only after confirming at least 100 GiB of quota headroom.  If neither
command reports meaningful information, confirm the limit with the cluster
administrator; `df` free space alone is not sufficient on shared storage.

### 2. Verify and extract

```bash
sha256sum --check RBP_Task002C_R2_Newton.tar.gz.sha256
tar -xzf RBP_Task002C_R2_Newton.tar.gz
cd RBP_Task002C_R2_Newton
```

Never reuse an extracted copy after any attempt.  Extract a fresh verified
copy if a new reviewed attempt is authorized.

### 3. Install the exact environment once

```bash
bash hpc/newton/002c_r2/01_INSTALL_ENVIRONMENT.sh
```

The script refuses to mutate an existing prefix.  To use a different new
prefix:

```bash
export RBP_NEWTON_ENV_PREFIX=/an/authorized/path/rbpbench-r2-newton
bash hpc/newton/002c_r2/01_INSTALL_ENVIRONMENT.sh
```

### 4. Select account/partition only if needed

Darwin can display account associations with:

```bash
sacctmgr show user "$USER" withassoc format=user,account
```

If a private lab account/partition is required:

```bash
export NEWTON_ACCOUNT=the_approved_account
export NEWTON_PARTITION=the_approved_partition
```

If unset, the submit wrapper uses Darwin's defaults. The wrapper requests
four CPUs, 96 GiB RAM, eight hours and no GPU.  Operational overrides may
increase memory/time only; they must not change the R2 program or scientific
flags:

```bash
export NEWTON_MEMORY=128G
export NEWTON_TIME_LIMIT=10:00:00
```

The environment-variable names retain `NEWTON_` for compatibility. To enable
Slurm email without changing the script, set exactly one address:

```bash
export RBP_SLURM_MAIL_USER=your-address@example.org
```

The wrapper then requests `BEGIN,END,FAIL` notifications. It never requests a
GPU.

### 5. Submit exactly once

```bash
bash hpc/newton/002c_r2/02_SUBMIT_R2_PROBE.sh
```

The wrapper invokes `sbatch`; it never performs the search on the login node.
It atomically creates a submission receipt and refuses if that receipt already
exists, so two queued jobs cannot race on one extraction.  The package is
single-use and the job stops without retry at the first failed gate.  Slurm is
asked to send `USR1` ten minutes before the time limit; `USR1` and `SIGTERM`
both terminate any active MMseqs2 process group and route through the normal
small STOPPED-return path.  Later termination signals are ignored while that
return is being packaged, so cancellation cannot interrupt the evidence ZIP.

If `sbatch` itself rejects the request, no job was accepted and no successful
submission receipt is written.  The wrapper preserves the scheduler error in
`SUBMIT_FAILED.txt` and prints a bounded recovery: confirm with
`squeue --me --name=rbp-r2-probe` that no job exists, remove only that failure
receipt and its empty directory, correct the account/partition, and submit
once.  A failed receipt is never silently overwritten or adopted.

### 6. Monitor without modifying the run

```bash
bash hpc/newton/002c_r2/03_CHECK_STATUS.sh
```

The command shows `squeue`/`sacct` state and prints the return location when
available.  Do not manually run MMseqs2 and do not resubmit after a failure.

### 7. Verify and return

```bash
bash hpc/newton/002c_r2/04_VERIFY_RETURN.sh
```

Return only the generated ZIP and its SHA-256 sidecar.  Raw FASTAs, databases
and result TSVs remain on Darwin and are excluded from the return.

## Success and failure interpretation

`SUCCESS` means all three probe widths passed and their full-run projections
can be reviewed.  It does **not** mean the split is fixed and it does not
authorize R3.

`STOPPED` is a valid, informative outcome.  Preserve and return its ZIP; do
not alter thresholds, reduce `--max-seqs`, omit a width, retry automatically
or start R3.

## Relevant project record

- Overall roadmap: `docs/PROJECT_ROADMAP.md`
- Split mechanics: `docs/SPLITS.md`
- v1 audit failure and correction:
  `docs/reviews/002c3_cross_partition_failure_and_component_rebuild_plan.md`
- Components-v2 core: `docs/tasks/002c_r1_component_rebuild_implementation.md`
- R1 acceptance: `docs/reviews/002c_r1_component_rebuild_acceptance.md`
- R2 scientific plan: `docs/tasks/002c_r2_direct_search_resource_probe.md`
- R2 core acceptance:
  `docs/reviews/002c_r2_resource_probe_implementation_acceptance.md`
- Prior Mac packaging plan: `docs/tasks/002c_r2_portable_probe_package.md`
- Prior Mac package build receipt:
  `manifests/sequence_r2_portable_package_build.json`
- Prior stopped return: `artifacts/teammate_run_results/return.zip`

## Boundary after Darwin R2

After the ZIP returns, the planning reviewer must independently verify hashes,
commands, resource measurements, projections and gates.  Only then may a new
R3 plan authorize the full all-vs-all direct-edge searches.  R3, component-v2
construction, reassignment, leakage audit and model training remain outside
this task.
