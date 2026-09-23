# Second review — Task 001B coordinate-feasibility execution

## Verdict

**Approve with required changes.**

The reviewer found the scientific scope, matched RefSeq contig policy, source
pinning, one-build-at-a-time intent, and B0–B7 checkpoints sound. The blockers
were at the boundary between those promises and the merged Task 001A runner.
The reviewer inspected the code but ran no tests, installed nothing, made no
network request, downloaded no reference, built no index, ran no mapping, and
did not read the real dataset.

## Required changes

1. **Minimap2 index and stderr.** Freeze index creation as
   `minimap2 -x splice:sr -I ... -d ...`, guarantee a single-part index,
   record and verify resolved `k/w/H`, capture and hash stderr, and stop on an
   index-parameter override warning.
2. **BWA index isolation and cleanup.** Use `bwa index -p` under a dedicated
   build-specific index directory and pass a separate BWA index prefix to
   mapping. Cleanup must target one safe, explicit directory and never use a
   reference-adjacent glob.
3. **Report/reference binding.** Include current reference and manifest hashes
   in report restart validity and fail closed if the report reference differs
   from the reference recorded by alignment.
4. **Single-build enforcement and evidence preservation.** Require exactly one
   explicit build for real mapping. A non-executed retry must never overwrite a
   prior `executed: true` alignment or exact-match record.
5. **Operational disk ceiling.** Add a per-artifact peak-size budget, enforce a
   projected-peak check before expensive work, and measure observed new disk at
   every checkpoint; merely checking free disk does not enforce 30 GiB.
6. **SeqKit scale probe.** Before the full exact search, test the largest human
   contig with a realistic pattern count and stop if projected memory would be
   unsafe on the 16-GiB host.
7. **Soft-mask behavior.** The real-binary SeqKit fixture must test
   `--ignore-case` across a lowercase/uppercase reference boundary, and the
   source masking status must be recorded.
8. **Build-label precision.** State that `hg38`/`hg19` are internal labels for
   the pinned RefSeq GRCh38.p14/GRCh37.p13 assemblies, record accession/name
   mappings, and document the GRCh37 RefSeq versus UCSC hg19 mitochondrial
   difference.
9. **Frozen-hash comparison.** Compare expected dataset/audit/protein hashes
   before reading the real CSV; computing hashes only for fingerprints does
   not verify the frozen values.
10. **Failed reconciliation exit.** A failed reconciliation must produce a
    nonzero exit, and the checkpoint must inspect `reconciliation.status`
    directly.
11. **Checksum drift.** Treat plan-time source sizes/MD5s as authoritative;
    disagreement with the live NCBI checksum listing stops execution and
    requires a recorded decision, never silent re-pinning.
12. **Artifact boundary.** Pin output/reference/index directories and extend
    `.gitignore` to cover FASTA, BED, and compressed TSV artifacts if they are
    accidentally produced outside the already ignored directories.

## Optional improvements

The reviewer also recommended creation-time index manifests to avoid repeated
multi-gigabyte hashing; documenting expected chrY pseudoautosomal ambiguity;
measuring disk per volume; returning machine-readable disk/RAM and minimap2
parameter evidence; and checking `osx-64` package availability before other
environment work.

## Governance confirmation

No Task 001B execution occurred during this review. No executor handoff was
prepared by the second reviewer.
