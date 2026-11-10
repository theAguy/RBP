# Task 004A-3C-1 implementation report

## Scope

This checkpoint implements the reviewed environment, cache and bundle
boundaries only. It did not install an environment, open real biological data,
query Newton, submit Slurm, use CUDA or build a production cache/bundle.

## G1-G5 implementation

- G1: `02_PREPARE_ENVIRONMENT.sbatch` uses channel-qualified PyTorch 2.5.1 and
  CUDA 12.4 specifications, strict channel order, NumPy 1.26.4, pytest 8 and
  `mkl<2024.1`. It exports an MD5-bearing explicit lock, recreates the final
  prefix with `--copy`, compares package lists, rejects pip packages and
  records Torch/CUDA/cuDNN/NumPy/Conda/channel evidence.
- G2: `environment_004a3.build_runtime_manifest` inventories all files and
  symlinks and rejects escaping links. The job disables bytecode/user-site
  writes, verifies the manifest after the focused suites, makes the final
  prefix read-only and verifies it again. A regression adds a late
  `__pycache__` file and proves verification fails.
- G3: `02_SUBMIT_ENVIRONMENT.sh` requires an explicit validated CPU partition
  and optional account. The job checks all three channels before solving and
  accepts only Ubuntu with glibc no newer than the accepted 2.35 GPU host. It
  records host and Conda-package-cache evidence and packages STOPPED evidence
  on failure.
- G4: `build_004a3_development_cache.py` requires a clean checkout, the exact
  accepted Task 004A-2 environment digest and live manifest, all accepted
  input hashes, the accepted source-file binding and the accepted summary.
  It uses the reviewed two-pass cache builder, requires exact equality with
  the accepted full development matrix, and retains the two-hour/four-GiB/
  free-disk gates.
- G5: the bundle schema and submit wrapper now require a node binding. The
  production policy is `gpu:L40:1`, exact runtime `NVIDIA L40S`, node
  `nlp-l40-2`. This uses the node actually observed in discovery because the
  returned scheduler evidence did not prove all public `L40` nodes equivalent.

## Verification

The accepted five-file local CPU suite was run twice with all four numerical
thread variables set to four:

- run 1: 108 passed, 73 subtests passed, 2 warnings, 99.71 seconds;
- run 2: 108 passed, 73 subtests passed, 2 warnings, 84.04 seconds.

The warnings are the pre-existing PyTorch TypedStorage deprecation and the
thread-reset warning in the notebook-fidelity test. Every new shell script
passes `/bin/bash -n`; all changed Python modules compile; `git diff --check`
is clean.

Copying the corrected test module onto a disposable archive of parent
`5d54407` fails during collection because the parent has neither
`require_accepted_count_matrix` nor the complete runtime-manifest builder. The
same regressions pass at the corrected head.

## Boundary

The CPU environment job (004A-3C-2), real local cache/bundle build (004A-3C-3)
and GPU smoke (004A-3D) remain unauthorized.
