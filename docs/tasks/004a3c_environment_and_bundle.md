# Task 004A-3C — freeze the Newton environment and build the GPU-smoke bundle

**Status:** planning review corrections G1-G5 implemented and synthetically
verified; awaiting independent implementation review. No environment job, real-data
cache build, bundle build, CUDA use, or GPU submission is authorized by this
document.

## 1. Purpose

Task 004A-3B established that Newton can provide an NVIDIA L40S with 49,140 MiB
through the scheduler request `gpu:L40`, that the required package channels are
reachable, and that environment installation belongs in a CPU job. Task
004A-3C turns those facts into two immutable inputs for the later one-epoch GPU
smoke:

1. a complete, hash-verified CUDA-enabled Python environment; and
2. a development-only cache containing exactly 8,193 train and 8,193
   validation rows.

It then builds one self-contained, inventoried bundle. It does not train a
model and does not open any test-row fields.

## 2. Accepted inputs

- accepted discovery: `manifests/task004a3b_newton_discovery.json`;
- accepted local data-contract smoke: `manifests/task004a2b_local_smoke.json`;
- accepted model/loss config: `configs/models/task004a_v1.toml`;
- real CSV, final v2 membership and accepted 500-nt FASTA at the exact hashes
  recorded by Task 004A-2;
- accepted Task 004A-2 summary SHA-256
  `27e78cd924eddce6799ad388d46235687cb2ce916648bc15c2b6a28569f6d805`.

No path is trusted without its recorded size and SHA-256.

## 3. Frozen environment request

The environment is Linux x86-64 and uses:

- Python 3.11;
- `pytorch::pytorch=2.5.1`;
- `pytorch::pytorch-cuda=12.4`;
- NumPy 1.26.4;
- pytest 8.x;
- `mkl<2024.1`;
- only dependencies resolved from the `pytorch`, `nvidia` and `conda-forge`
channels, in that order, with channel override and strict channel priority.

PyTorch documents PyTorch 2.5.1 with `pytorch-cuda=12.4` as an official Linux
Conda combination. CUDA 12.4 is below the 13.2 capability exposed by the
accepted Newton driver. TorchVision and TorchAudio are not installed because
the accepted source and focused suites do not import them.

The CPU job may resolve build strings and transitive packages once. It must
then export an `@EXPLICIT` lock with MD5 package checksums, hash it, install a
second final prefix only from that lock using `--copy`, and verify the two
resolved package lists are identical. The final prefix is
final prefix is
`$HOME/.conda/envs/rbpbench-004a3-<lock_sha256_prefix>`.

The job must locate an existing site/user Conda installation. It may not
bootstrap a new package manager or silently switch to pip. Failure to find
Conda produces a return package and stops.

The job checks channel reachability before solving and requires an explicitly
named CPU partition and optional account. Its host must be Ubuntu and use glibc
2.35 or older, matching the accepted GPU host family. The final installation
must report PyTorch 2.5.1 from the `pytorch` channel, CUDA runtime 12.4, NumPy
1.26.4 and no `pypi` packages. The return also records Conda, cuDNN,
`torch.__config__`, channel, kernel, OS and glibc evidence.

After the runtime inventory is written, all Python work uses
`PYTHONDONTWRITEBYTECODE=1` and `PYTHONNOUSERSITE=1`. The five focused suites
run, the inventory is verified again, and the final prefix is made read-only.
The final installation uses copied rather than package-cache-hardlinked files,
so making it read-only cannot alter the shared Conda package cache.

## 4. Checkpoint 3C-1 — synthetic implementation and review

Before any remote or real-data action, implement and test:

1. a runtime-manifest builder that records every file and symlink below a
   prefix, rejects escaping symlinks, and reproduces the verifier's exact
   inventory;
2. a CPU-job submit wrapper and job that:
   - request no GPU;
   - locate Conda fail-closed;
   - resolve the frozen request once in a job-specific staging prefix;
   - export the explicit lock and install the final hash-named prefix;
   - build and immediately verify the complete runtime manifest;
   - run the five accepted focused suites with four numerical threads;
   - reverify the manifest after the suites and make the prefix read-only;
   - write a sanitized environment summary and ZIP plus checksum;
   - remove only its own staging prefix after final verification;
3. a production cache-builder CLI that authenticates every real input against
   Task 004A-2 before opening it, invokes the accepted Gate A/Gate B streaming
   boundary, requires Gate A's full matrix to equal the accepted 004A-2 matrix,
   and writes an immutable cache plus sanitized summary;
4. a one-command bundle builder/runbook that consumes only an accepted lock,
   accepted runtime manifest, accepted cache and accepted discovery record;
5. regressions for refusal of a missing/extra runtime file, escaping symlink,
   package-list drift, wrong input hash, test-field access, wrong cache size,
   GPU-policy drift and any pre-existing output.

No network, Newton query, Conda solve, real input, CUDA or Slurm action occurs
in 3C-1.

## 5. Checkpoint 3C-2 — one CPU environment job

After 3C-1 acceptance, submit exactly one CPU-only job from Darwin using the
shared home filesystem and an explicitly reviewed partition/account. Requested
resources are four CPUs, 32 GiB RAM and two hours. The job performs only the
environment work in section 3. It returns STOPPED evidence on channel or host
incompatibility; it does not try another route.

The return contains:

- explicit environment lock and SHA-256;
- complete runtime manifest and SHA-256;
- exact package list;
- Python, PyTorch, CUDA-runtime, cuDNN and NumPy versions, Torch build config,
  Conda version/channels and install-host OS/kernel/glibc;
- focused-suite output;
- prefix size, file/symlink counts, wall time and peak RSS;
- sanitized `COMPLETED` or `STOPPED` summary;
- ZIP checksum.

The job does not contain biological data and does not request a GPU. It is
single-shot: on failure, return the evidence without editing or retrying.

## 6. Checkpoint 3C-3 — local development cache and bundle

Only after the environment return is accepted:

1. run in the accepted Task 004A-2 local environment (digest
   `c4398ac454240b367eb7b8736915b67a038984724427eacffd9d98b19f3ae847`),
   require a clean worktree and reverify its accepted source binding;
2. hash all Task 004A-2 inputs before opening them;
3. run Gate A across the complete membership/CSV/FASTA universe and require its
   complete train/validation matrix to equal the accepted 004A-2 summary;
4. select exactly 8,193 train and 8,193 validation rows using seed `20261029`,
   label coverage followed by deterministic label-blind filler;
5. run independent Gate B and require equal count matrices, equal selected
   content digests, 122/122 class eligibility and zero test-field accesses;
6. enforce the accepted two-hour, four-GiB peak-RSS and free-disk gates;
7. write the mmap cache transactionally and rehash its complete inventory;
8. build the portable archive and verify every archive member against the
   bundle inventory.

The bundle freezes:

- scheduler request `gpu:L40:1`;
- required runtime name `NVIDIA L40S`;
- node binding `nlp-l40-2`, the discovery allocation that directly proved the
  scheduler's `L40` resource was an `NVIDIA L40S` (the discovery evidence did
  not prove that every public `L40` node has the same model);
- the accepted runtime-manifest and lock hashes;
- the 12-hour Task 004A-4 project ceiling and the four-hour 004A-3D smoke
  request;
- the accepted source/config/input hashes;
- no test rows and no original full-universe CSV, FASTA or membership file.

If Slurm assigns a device whose runtime name is not exactly `NVIDIA L40S`, the
later smoke stops before opening the cache. This is fail-closed; it does not
select another model automatically.

## 7. Acceptance gates

Task 004A-3C passes only if:

- the explicit lock recreates the final environment exactly;
- every runtime file and symlink matches the accepted manifest;
- all five focused suites pass in the final environment;
- the final environment is byte-for-byte identical to its runtime manifest
  after the suites and is read-only;
- cache partitions contain exactly 8,193 rows each;
- all 122 outputs have both known classes in train and validation;
- Gate A and Gate B reconcile exactly and all test access counters are zero;
- the bundle and archive inventories rehash exactly;
- no test row, sequence, label, checkpoint or prediction enters the sanitized
  tracked manifest;
- the output root was absent before each stage and no retry occurred.

## 8. Boundary after 3C

Passing 3C authorizes only preparation of a separate Task 004A-3D execution
handoff. It does not authorize the GPU smoke itself, full 30-epoch training,
Task 004A-4, a second seed, or model comparison.
