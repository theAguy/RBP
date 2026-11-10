# Task 004A-3C — freeze the Newton environment and build the GPU-smoke bundle

**Status:** planned; awaiting independent review. No environment job, real-data
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
- PyTorch 2.5.1;
- `pytorch-cuda=12.4`;
- NumPy 1.26.4;
- pytest 8.x;
- only dependencies resolved from the `pytorch`, `nvidia` and `conda-forge`
  channels with channel override enabled.

PyTorch documents PyTorch 2.5.1 with `pytorch-cuda=12.4` as an official Linux
Conda combination. CUDA 12.4 is below the 13.2 capability exposed by the
accepted Newton driver. TorchVision and TorchAudio are not installed because
the accepted source and focused suites do not import them.

The CPU job may resolve build strings and transitive packages once. It must
then export an `@EXPLICIT` lock, hash it, install a second final prefix only
from that lock, and verify the two resolved package lists are identical. The
final prefix is
`$HOME/.conda/envs/rbpbench-004a3-<lock_sha256_prefix>`.

The job must locate an existing site/user Conda installation. It may not
bootstrap a new package manager or silently switch to pip. Failure to find
Conda produces a return package and stops.

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
   - write a sanitized environment summary and ZIP plus checksum;
   - remove only its own staging prefix after final verification;
3. a production cache-builder CLI that authenticates every real input against
   Task 004A-2 before opening it, invokes the accepted Gate A/Gate B streaming
   boundary, and writes an immutable cache plus sanitized summary;
4. a one-command bundle builder/runbook that consumes only an accepted lock,
   accepted runtime manifest, accepted cache and accepted discovery record;
5. regressions for refusal of a missing/extra runtime file, escaping symlink,
   package-list drift, wrong input hash, test-field access, wrong cache size,
   GPU-policy drift and any pre-existing output.

No network, Newton query, Conda solve, real input, CUDA or Slurm action occurs
in 3C-1.

## 5. Checkpoint 3C-2 — one CPU environment job

After 3C-1 acceptance, submit exactly one CPU-only job from Darwin using the
shared home filesystem. Requested resources are four CPUs, 32 GiB RAM and two
hours. The job performs only the environment work in section 3.

The return contains:

- explicit environment lock and SHA-256;
- complete runtime manifest and SHA-256;
- exact package list;
- Python, PyTorch, CUDA-runtime and NumPy versions;
- focused-suite output;
- prefix size, file/symlink counts, wall time and peak RSS;
- sanitized `COMPLETED` or `STOPPED` summary;
- ZIP checksum.

The job does not contain biological data and does not request a GPU. It is
single-shot: on failure, return the evidence without editing or retrying.

## 6. Checkpoint 3C-3 — local development cache and bundle

Only after the environment return is accepted:

1. hash all Task 004A-2 inputs before opening them;
2. run Gate A across the complete membership/CSV/FASTA universe;
3. select exactly 8,193 train and 8,193 validation rows using seed `20261029`,
   label coverage followed by deterministic label-blind filler;
4. run independent Gate B and require equal count matrices, equal selected
   content digests, 122/122 class eligibility and zero test-field accesses;
5. write the mmap cache transactionally and rehash its complete inventory;
6. build the portable archive and verify every archive member against the
   bundle inventory.

The bundle freezes:

- scheduler request `gpu:L40:1`;
- required runtime name `NVIDIA L40S`;
- no additional node constraint;
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
