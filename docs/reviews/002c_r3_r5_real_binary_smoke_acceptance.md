# Task 002C-R3–R5 Darwin real-binary smoke acceptance

## Verdict

**Passed and accepted.** The final implementation-review gate is closed.

The immutable smoke return and its sidecar were independently verified after
download. Exactly two synthetic real-MMseqs2 tests ran, both passed, and none
were skipped:

1. E0 reverse-complement, identity, and width-specific coverage behavior;
2. the complete tiny E0–E8 workflow using the pinned real binary.

The tests used only generated tiny sequences. They did not open the real
dataset, did not start production R3–R5, and did not use a GPU.

## Bound execution evidence

- source commit: `8eef8dca310adcabae750cd78cd548d128f175dd`;
- host/job: `newton8`, Slurm job `452915`;
- allocation: 4 CPUs and 24,576 MiB RAM;
- pinned MMseqs2: `18.8cc5c`, conda build `hd6d6fdc_0`, binary SHA-256
  `d6d1bf1b50c095eb0cb66f685a7fb1d9b8b69497e1e88416fd48f28e313cc773`;
- accepted runtime-receipt SHA-256:
  `ec64969ca0d3936fc5b2d5cdbc301e9613ae644e1a7b59be41118fe73d008dd9`;
- unittest result: 2 passed in 324.949 seconds;
- process wall time: 325.97 seconds;
- peak RSS: 8,397,352 KiB (about 8.01 GiB);
- swaps: 0; exit status: 0.

The return ZIP is 4,258 bytes with SHA-256
`874f5f7cfb14429b59afd88adda045192c56ef464fdc81aabd253ef1632e55d3`.
Its outer sidecar, ZIP structure, internal inventory, per-member checksums,
status, environment evidence, and test output all reconcile.

The machine-readable evidence is recorded in
`manifests/sequence_r3r5_darwin_smoke_002c.json`.

## Boundary and next step

This acceptance permits construction of the separately reviewed immutable
production R3–R5 bundle. It does not by itself authorize the production run.
The production bundle must bind all accepted real inputs, be verified after
extraction on Darwin, and be launched only through its reviewed Slurm wrapper.
