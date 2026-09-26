# Executor handoff — Task 002B-2 real decode and exact/RC evidence

Claude, execute only checkpoint 002B-2. This is the first real-dataset
checkpoint. Run `preflight`, then `decode`, as two separate invocations and
stop. Do not run a probe, cluster, component report, or partition assignment.

## Git and required reading

1. Work on `issue-002-sequence-partitions` from the commit containing this
   handoff. Verify the expected origin, a clean tracked worktree, and accepted
   implementation commit `173b2a6` as an ancestor. Do not push, merge, or
   rewrite history.
2. Read:
   - `docs/reviews/002b1_orchestration_acceptance.md`;
   - `docs/tasks/002b_real_sequence_grouping.md`;
   - `docs/reviews/002b_real_sequence_grouping_reconciliation.md`;
   - `docs/reviews/002a_sequence_partition_acceptance.md`;
   - `docs/SPLITS.md`, `docs/DATA.md`, `docs/DECISIONS.md`, and
     `CONTRIBUTING.md`.
3. Use only the isolated `rbpbench-splits-002` environment and its accepted
   MMseqs2 binary. Keep the host plugged into power and close unrelated
   memory-heavy applications.

## Stop-before-start checks

Before opening the real CSV:

- resolve the repository root independently and verify the expected branch,
  origin, ancestry, and clean tracked worktree;
- confirm at least 16 GiB installed RAM and at least 80 GiB free disk;
- confirm `artifacts/splits/sequence_partitions_v1/` does not already contain
  any selection record, generation, or unknown file; if it does, stop and
  list it without deleting, adopting, or overwriting anything;
- confirm the production config still names the frozen 361,180-row dataset,
  three protected widths, resource limits, and accepted MMseqs2 SHA-256; and
- confirm the environment/binary manifest and all frozen small-input files
  are present. Do not silently repin any value.

## Authorized execution

Use the production defaults explicitly. First run only:

```text
conda run --no-capture-output -n rbpbench-splits-002 \
  python -m rbpbench.splits.runner \
  --stage preflight \
  --config configs/splits/sequence_partitions_v1.toml \
  --repo-root . \
  --dataset-csv dataset_K562_multilabel_with_NEGs.csv \
  --output-dir artifacts/splits/sequence_partitions_v1 \
  --mmseqs-bin mmseqs
```

Stop immediately if preflight fails or reports any frozen hash, byte-size,
binary, RAM, or disk mismatch. If it passes, inspect and preserve the accepted
`selected/preflight.json`, then run only:

```text
conda run --no-capture-output -n rbpbench-splits-002 \
  python -m rbpbench.splits.runner \
  --stage decode \
  --config configs/splits/sequence_partitions_v1.toml \
  --repo-root . \
  --dataset-csv dataset_K562_multilabel_with_NEGs.csv \
  --output-dir artifacts/splits/sequence_partitions_v1 \
  --mmseqs-bin mmseqs
```

Do not pass `--force`, `--authorize-mmseqs`, or any other stage. Capture exact
commands, exit status, wall time, peak RSS, and free disk before/after in
non-overwriting checkpoint logs under the ignored Task 002 artifact tree.

## Required reconciliation

After decode returns zero, independently verify without writing a second
decoded generation:

1. `selected/preflight.json` and `selected/decode.json` are accepted and
   current under the runner's own currency checks.
2. The decode record has exactly 361,180 unique canonical IDs, ordered
   `row_0` through `row_361179`, and no foreign/missing/duplicate ID.
3. Each accepted FASTA has exactly 361,180 records; IDs match the exact
   universe; widths are exactly 500, 251, and 101 nt; and every base is one
   of A/C/G/T.
4. The strict decoder completed its built-in source one-hot round-trip for
   every row; do not re-decode into a second retained copy.
5. For each width, recompute sanitized exact/reverse-complement canonical-hash
   counts in a streaming or bounded-memory audit and reconcile the retained
   edge artifact and recorded duplicate-group count/maximum size. Verify edge
   endpoints are valid IDs and no raw sequence or label enters committed
   evidence.
6. Re-hash every retained decode-generation artifact and require an exact
   match to the selection record's path/size/SHA-256 inventory.
7. Confirm no probe, cluster, component-report, partition, model, coordinate,
   reference, or network action occurred and no MMseqs2 clustering command
   ran.

Any mismatch is a hard stop. Preserve the candidate and records for review;
do not repair data, weaken validation, rerun with `--force`, or continue to
002B-3.

## Sanitized manifest and commit

Create only `manifests/sequence_decode_002b2.json`, containing:

- checkpoint/status and execution-start Git commit;
- exact commands and exit statuses;
- config, input, environment-manifest, and binary hashes/sizes;
- preflight/decode stage fingerprints and decode generation digest;
- retained artifact paths relative to the repository, byte sizes, and
  SHA-256 values;
- row/ID/width/alphabet and exact/RC reconciliation summaries;
- wall time, peak RSS, disk before/after, and artifact-byte totals; and
- explicit statements that labels were not used for grouping and that no
  probe/cluster/component/partition/model/coordinate/reference/network action
  occurred.

Do not include sequence strings, one-hot data, label values, absolute personal
paths, or large logs. Confirm the large generation remains Git-ignored. Stage
and commit only this sanitized manifest locally; do not push.

## Return and stop

Return:

1. pre-start checks and exact command/exit status for each stage;
2. frozen input/tool revalidation;
3. runtime, memory, disk, and artifact sizes;
4. full FASTA/ID/width/alphabet reconciliation;
5. per-width exact/RC group and edge summaries;
6. selection-record/inventory revalidation;
7. staged-file audit, commit hash, and clean tracked worktree; and
8. anomalies or gaps.

Stop after the local manifest commit. End exactly with:

`Task 002B-3 resource probes were not started.`

