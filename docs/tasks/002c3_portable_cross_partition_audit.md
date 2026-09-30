# Task 002C-3/4 — Portable cross-partition audit and conditional finalization

**Status:** portable handoff preparation
**Parent:** `docs/tasks/002c_partition_assignment_and_audit.md`
**Execution host:** native Apple-Silicon macOS with 64 GiB installed RAM
**Execution style:** one guarded launcher; no interactive stage-by-stage decisions

## Purpose

Finish the last leakage-safety gate for the benchmark split. The portable
handoff runs fresh MMseqs2 searches between every pair of train, validation,
and test partitions at all three protected sequence widths. It finalizes the
split only if every directed search finds zero qualifying cross-partition
hits.

This task does not repeat decoding, similarity clustering, component
construction, assignment, the former-split diagnostic, or the exact/reverse-
complement audits. Those accepted artifacts are copied into the handoff and
revalidated by hash.

## Frozen scientific work

The launcher performs, sequentially:

1. verify the complete portable input inventory;
2. verify native Apple-Silicon execution, the accepted MMseqs2 18.8cc5c
   binary, at least 16 GiB installed RAM, at least 10 GiB currently available
   RAM, and at least 80 GiB free disk;
3. run one deterministic resource probe at each width: 500, 251, and 101 nt;
4. run all 18 directed searches: three widths multiplied by the six ordered
   partition pairs (`train→validation`, `validation→train`, `train→test`,
   `test→train`, `validation→test`, `test→validation`);
5. stop immediately if a search reports any qualifying hit; otherwise run
   finalization; and
6. independently reconcile the final 361,180-row membership, 173,465 intact
   components, accepted partition counts, three probes, and 18 zero-hit
   searches.

Every MMseqs2 subprocess keeps the already reviewed settings:

- nucleotide search type 3 and both strands;
- minimum identity 0.90;
- bidirectional coverage 0.80 at 500 nt and 0.95 at 251/101 nt;
- coverage mode 0, alignment mode 3, E-value 1000, masking disabled,
  sensitivity 7.5, and `--max-seqs 361180`;
- at most four threads;
- 12-hour timeout per subprocess;
- 50-GiB combined Task 002C output ceiling and 80-GiB free-disk floor.

No threshold or gate may be lowered by the executor.

## Apple-Silicon binary identity

The frozen Intel MMseqs2 executable previously failed with `SIGILL` on Apple
Silicon. Task 002B independently accepted the official native Bioconda
`osx-arm64` build after real-binary smoke tests and deterministic probe/full-
clustering reconciliation:

- version/build: `18.8cc5c`, `h44b2af9_0`;
- SHA-256:
  `3fa397a9af5f8142ab8df13cc3e19b3aefc91cb9908d9c147883c8ac4162db0d`.

The portable runner accepts this hash only when the live host reports
`arm64`/`aarch64`. Intel execution remains bound to the original hash. The
scientific commands are identical across architectures.

## Portability correction for finalization

The accepted legacy-diagnostic selection record retains the original Mac's
absolute path to the Task 002B evidence root. The portable finalization CLI
therefore supplies an explicit new evidence root. This override changes only
where the bytes are found: all eight evidence files are re-hashed, parsed,
and compared with the frozen config and the unchanged accepted record. The
accepted record is never rewritten or silently adopted.

## Stop policy

The launcher performs no automatic retry and no repair. It stops on the first:

- missing, altered, or unlisted immutable input;
- wrong host architecture, Python runtime, MMseqs2 version/hash, or resource
  gate failure;
- nonzero subprocess exit, timeout, or disk ceiling/floor violation;
- stale/missing accepted stage evidence;
- malformed or foreign audit endpoint;
- one or more qualifying cross-partition hits; or
- failed independent final reconciliation.

An operational or scientific stop must not trigger a flag change, a weaker
threshold, a manual record edit, or a rerun. The working directory is kept
intact for review.

## Return contract

Whether the run succeeds or stops, the launcher attempts to create:

```text
return/RBP_002C3_RETURN_<UTC timestamp>_<host>/
├── STATUS.json
├── RETURN_SUMMARY.md
├── RETURN_MANIFEST.json
├── RETURN_INVENTORY.json
├── CHECKSUMS.sha256
├── audit_reports/
├── selected_records/
├── execution_logs/
├── tool_logs/
├── environment/
└── final/                         # success only
    ├── sequence_partitions_v1.tsv.gz
    ├── sequence_partitions_v1.json
    └── finalize_selection_record.json
```

A ZIP with the same basename is created beside the directory. That ZIP is the
only object the collaborator needs to return. It intentionally excludes the
724-MB CSV, decoded FASTAs, MMseqs2 databases, and temporary files. Those stay
inside the working bundle unless a later review explicitly requests them.

## Success gate

Success requires all of the following:

- three accepted resource probes;
- 18 accepted directed searches, each with `passed=true` and `hit_count=0`;
- a current accepted finalization record;
- exactly 361,180 canonical sample IDs and 173,465 unsplit components;
- row counts `train=246465`, `validation=57391`, `test=57324`;
- all existing label-count floors still passing; and
- the final membership matching the accepted assignment after decompression.

Only after independent review of the returned ZIP may the split be declared
frozen and Phase 3 baselines begin.
