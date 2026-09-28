# Task 002B real sequence-grouping acceptance

## Verdict

**Accepted with a documented execution exception.** Returned attempt
`20260928T091014Z_87391_arm64` completed the deterministic probes, all three
full-data clusterings, and the component union/report. No full rerun is
required. Task 002C may be planned separately; this acceptance does not itself
assign a train, validation, or test partition.

## Independent reconciliation

The reviewer independently verified the returned checksums, selected-stage
chain, membership files, component assignment, and report:

- all 361,180 canonical IDs occur exactly once in each of the 500-, 251-, and
  101-nt full membership files, with no missing, duplicate, or foreign IDs;
- the three widths contain 174,190, 259,288, and 296,182 clusters,
  respectively, with largest sizes 231, 65, and 35;
- independently unioning all three membership files produces exactly the
  returned 173,465 components over all 361,180 IDs;
- all 173,465 component IDs equal the specified hashes of their sorted member
  IDs, and the report's complete component-size mapping matches the returned
  membership;
- the largest component contains 611 rows (0.169%) and the largest 20 contain
  1.156%, safely below the prespecified 5% and 20% gates; and
- the final artifact contains only `sample_id` and `component_id`; labels,
  model outputs, coordinates, and partition assignment were not used.

The regenerated decode artifacts match the accepted 002B-2 artifact hashes
and sizes exactly. The 10,000-ID probe subset digest is
`f077d08637956a78f39b08e81f68a257f7bf01a167625f151d68cf2e1b17ac4a`;
its 500/251/101 cluster counts (9,415/9,847/9,934) match the earlier frozen-
Intel probe results. All observed runs stayed within the original 10-GiB
peak-memory gate and used the frozen scientific flags, four threads, and no
split-memory override.

## Execution exception

The portable bundle pinned the `osx-64` MMseqs2 18.8cc5c build with binary
SHA-256
`44afaca1d6d8a4c7709177782aa37203cd52651563c778d75f9ae2ee98bed635`.
That executable failed with `SIGILL`/AVX2 on the collaborator's Apple-Silicon
host. The completed run instead used the official Bioconda native
`osx-arm64` build `h44b2af9_0`, version 18.8cc5c, binary SHA-256
`3fa397a9af5f8142ab8df13cc3e19b3aefc91cb9908d9c147883c8ac4162db0d`.

This means the run did not reproduce the frozen executable hash. The exception
is accepted because the version and scientific commands were unchanged, the
12 real-binary smoke tests passed, the deterministic probe agreed with the
prior Intel probe at all three widths, and the complete returned result passed
independent reconciliation. The native build identity remains part of the
permanent provenance; it must not be described as the frozen Intel binary.

## Boundary for Task 002C

Task 002C must assign whole accepted components toward the locked 70/15/15
targets, check the 30-positive/30-negative validation and test floors, compare
the former row-level split as a diagnostic, and run fresh cross-partition
MMseqs2 plus independent exact/reverse-complement audits. Model results remain
out of scope until that membership is accepted and frozen.
