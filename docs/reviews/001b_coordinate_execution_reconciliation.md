# Reconciliation — Task 001B second review

## Outcome

The second reviewer returned **approve with required changes**. The planning
reviewer independently checked the cited Task 001A paths and accepts all twelve
required findings. All are incorporated into
`docs/tasks/001b_coordinate_feasibility_execution.md`; none is delegated as an
optional scientific judgment to the executor.

Task 001B remains checkpointed. The resulting authorization is for B1 only:
isolated environment resolution and tiny-fixture readiness implementation. It
does not authorize reading the real CSV, downloading human references,
building human-genome indices, or real mapping.

## Required changes

| Item | Decision | Reconciliation |
|---|---|---|
| R1 minimap2/stderr | Accept, make concrete | Frozen one-part index command is `minimap2 -x splice:sr -I 8G -d`; minimap2 2.31 resolves `k=15`, `w=5`, non-HPC. All external stderr is preserved and hashed; parameter-override or multipart warnings stop the run. |
| R2 BWA cleanup | Accept | BWA receives a build-specific `indices/<build>/<build>` prefix created with `bwa index -p`. Cleanup is exact-directory-only with path, symlink, contents, provenance, mapping, and reconciliation guards. |
| R3 report binding | Accept, strengthen | Current reference/manifest/index evidence enters restart validity. Both exact-match and report compare their active reference with upstream recorded hashes and fail closed on mismatch. |
| R4 build/evidence safety | Accept | Real mapping requires exactly one explicit build. A failed, unauthorized, or dry-run attempt cannot overwrite a prior executed record. |
| R5 disk mechanism | Accept | Added a conservative 30-GiB B6 peak ledger, per-volume baseline, pre-step projection, post-step measurement, and fail-closed output allowance. |
| R6 SeqKit feasibility | Accept | B3 now includes the largest contig and all 10,100 patterns, with wall-time/RSS/output evidence before the full-reference search. |
| R7 masking | Accept | Tiny real-binary tests include a case-boundary match, and each derived manifest records masking base counts/status. |
| R8 labels/MT | Accept | The task explicitly defines labels as RefSeq assemblies, requires accession/name tables, and documents the `NC_012920.1` versus UCSC hg19 `NC_001807.4` distinction. |
| R9 input equality | Accept, enforce in code | A checked-in execution-source specification supplies all four expected hashes, which must be compared before the real CSV is opened. |
| R10 reconciliation | Accept | Failed reconciliation exits nonzero; reviewers still inspect `reconciliation.status == "passed"`. |
| R11 MD5 drift | Accept | Plan size/MD5 values are authoritative. Live-list disagreement stops and requires `docs/DECISIONS.md`; silent re-pinning is forbidden. |
| R12 artifact boundary | Accept | Runtime locations are pinned and B1 adds the missing FASTA/BED/compressed-TSV ignore patterns. |

## Optional improvements

All five were adopted. Index manifests retain creation-time cryptographic
hashes and safe fast-validation metadata; the task documents chrY PAR
ambiguity; disk evidence is volume-aware; executor returns are
machine-readable; and package availability is checked first.

For fast restart validation, size/mtime may identify whether a full index hash
must be recomputed, but it may never substitute for the creation-time SHA-256
stored in the index manifest or allow changed files to pass.

## Parameter evidence

The minimap2 2.31 source defines `splice:sr` index settings as `k=15`, `w=5`,
and non-HPC, and documents `-I 8G` as the batch limit. Its manual warns that a
larger reference creates a multipart index with incorrect mapping quality and
that index parameters are fixed in a prebuilt index:

- <https://github.com/lh3/minimap2/blob/v2.31/options.c>
- <https://github.com/lh3/minimap2/blob/v2.31/minimap2.1>

The installed binary remains the binding B1 verification target.
