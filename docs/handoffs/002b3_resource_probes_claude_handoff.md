# Executor handoff — Task 002B-3 deterministic resource probes

Claude, execute only checkpoint 002B-3. Run the accepted deterministic
10,000-ID MMseqs2 probe sequentially at 500, 251, and 101 nt, one explicit
runner invocation per width. Stop before any full-data `cluster` stage.

## Git and required reading

1. Work on `issue-002-sequence-partitions` from the commit containing this
   handoff. Verify the expected origin, clean tracked worktree, and accepted
   real-decode commit `ce0ae66` as an ancestor. Do not push, merge, rewrite
   history, or change code/config/tests.
2. Read:
   - `docs/reviews/002b2_real_decode_acceptance.md`;
   - `manifests/sequence_decode_002b2.json`;
   - `docs/tasks/002b_real_sequence_grouping.md`;
   - `docs/reviews/002b_real_sequence_grouping_reconciliation.md`; and
   - `docs/SPLITS.md`, `docs/DATA.md`, `docs/DECISIONS.md`, and
     `CONTRIBUTING.md`.
3. Use only `rbpbench-splits-002` and the accepted MMseqs2 binary. Keep the
   host plugged into power and close unrelated memory-heavy applications.

## Stop-before-start checks

Before launching MMseqs2:

- reverify branch/origin/ancestry and the frozen config/input/binary hashes;
- rehash the selected decode generation and require exact agreement with
  `selected/decode.json` and the accepted 002B-2 manifest;
- confirm the Task 002 artifact tree contains the accepted preflight/decode
  evidence and no existing probe, full-cluster, or component-report record;
- require at least 16 GiB installed RAM, 80 GiB free disk, and **10 GiB
  currently available memory** immediately before the first probe; and
- confirm no concurrent MMseqs2 or other heavy process is running.

The 002B-2 preflight snapshot reported only about 4.8 GiB available memory.
That old value is not a failure for completed decode, but the live value must
now reach the frozen 10-GiB launch gate. If it does not, stop without launching
a probe. Do not weaken the gate or add a split-memory flag.

## Authorized commands

Run these separately and in this order. Do not use `--force`.

```text
conda run --no-capture-output -n rbpbench-splits-002 \
  python -m rbpbench.splits.runner \
  --stage probe --width 500 --authorize-mmseqs \
  --config configs/splits/sequence_partitions_v1.toml \
  --repo-root . \
  --dataset-csv dataset_K562_multilabel_with_NEGs.csv \
  --output-dir artifacts/splits/sequence_partitions_v1 \
  --mmseqs-bin mmseqs
```

After accepting and reconciling width 500, repeat the identical command with
`--width 251`; only after that passes, repeat with `--width 101`.

Capture exact commands, exit statuses, wall time, peak RSS, available memory
before/after, disk before/after, and non-overwriting logs. A probe internally
runs MMseqs2 clustering on the 10,000-ID subset; this is expected. It does not
authorize the full-data `cluster` runner stage.

## Gate after every width

Before starting the next width, require all of the following:

1. The selected probe record is executed, current, and bound to the accepted
   decode generation and exact MMseqs2 binary.
2. The probe input contains exactly the deterministic 10,000 IDs selected by
   stable hash of canonical sample ID using seed `20260925`, independent of
   labels and row order. Record a digest of the sorted ID list, not the list
   itself, in committed evidence.
3. All three widths use the identical selected-ID set.
4. Membership reconciles exactly: every selected ID appears exactly once,
   every representative belongs to the same 10,000-ID universe, and no ID is
   missing, duplicated, or foreign.
5. The recorded command retains the frozen identity/coverage for that width,
   `--cov-mode 0`, `--max-seqs 361180`, accepted clustering flags, four
   threads, and no `--split-memory-limit`.
6. Peak RSS does not exceed 10 GiB; the process was not killed or timed out;
   total Task 002 artifacts remain below 50 GiB; free disk remains at least
   80 GiB; and currently available memory after the probe remains at least
   10 GiB before another probe may start.
7. Rehash the complete probe generation and require exact agreement with its
   selection-record inventory.

If any gate fails, stop immediately. Preserve earlier accepted probe records,
leave the failed candidate unaccepted, and do not change thresholds, flags,
sample selection, or resource limits. Do not silently retry.

## Sanitized manifest and commit

If all three probes pass, create only
`manifests/sequence_probes_002b3.json`, containing:

- execution-start Git commit and exact per-width commands/statuses;
- frozen input/config/environment/binary hashes;
- accepted decode fingerprint/generation digest;
- the deterministic selected-ID count and sorted-ID-list digest;
- per-width probe fingerprint/generation digest and artifact inventory;
- per-width runtime, peak RSS, memory before/after, disk evidence, membership
  counts, cluster counts, and effective command settings; and
- explicit statements that labels were not used and that no full-data
  cluster, component report, partition, model, coordinate, reference, or
  network action occurred.

Do not commit sample-ID lists, sequences, labels, MMseqs2 databases, or large
logs. Stage and commit only the sanitized manifest locally; do not push.

If a probe fails, do not create a passing manifest. Return the failure and
stop; a small sanitized stop manifest may be committed only if needed to
preserve the failure evidence.

## Return and stop

Return:

1. pre-start resource/current-evidence checks;
2. each exact command and exit status;
3. deterministic subset reconciliation and digest;
4. per-width command/membership/resource/inventory evidence;
5. confirmation that no full-data cluster stage ran;
6. manifest commit and staged-file audit, or bounded failure evidence; and
7. anomalies or gaps.

Stop after the third accepted probe or the first failure. End exactly with:

`Task 002B-4 full 500-nt clustering was not started.`

