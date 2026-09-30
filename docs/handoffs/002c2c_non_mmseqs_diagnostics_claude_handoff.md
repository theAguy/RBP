# Task 002C-2C Claude executor handoff — legacy and exact/RC diagnostics

## Authorization and Git boundary

Execute this bounded checkpoint on branch `issue-002c-partition-assignment`,
starting from the commit containing this handoff or a descendant. Work on the
current project Mac. Do not push or merge.

Before changing or reading any real artifact, verify:

- repository root and origin `https://github.com/theAguy/RBP.git`;
- branch `issue-002c-partition-assignment`;
- commits `a15fcfa`, `2d5d114`, `436ec1c`, `8387712`, and this handoff are
  ancestors of `HEAD`;
- tracked worktree is clean;
- `artifacts/splits/sequence_partitions_002c_v1/selected/assign.json` is the
  only selection record in the primary assignment root; and
- no `legacy_diagnostic` or `exact_audit` generation/selection record already
  exists.

If any target output or unknown prior evidence exists, stop and list it. Do not
delete, overwrite, adopt, or use `--force`.

## Required reading, in order

1. `CONTRIBUTING.md`
2. `docs/PROJECT_ROADMAP.md`
3. `docs/tasks/002c_partition_assignment_and_audit.md`
4. `docs/reviews/002c2b_real_assignment_acceptance.md`
5. `docs/reviews/002c2c_non_mmseqs_diagnostics_review_request.md`
6. `docs/reviews/002c2c_non_mmseqs_diagnostics_reconciliation.md`
7. `configs/splits/sequence_partitions_002c_v1.toml`
8. the `legacy_diagnostic` and `exact_audit` paths in
   `src/rbpbench/splits/runner_002c.py`, `legacy_diagnostic.py`,
   `legacy_edges.py`, `cluster_membership_evidence.py`, and `exact_audit.py`.

## Scope and checkpoint order

This handoff authorizes, sequentially:

1. one bounded accepted-filename correction using synthetic fixtures only;
2. one real legacy-fold leakage diagnostic;
3. one independent exact/reverse-complement audit at each of 500, 251, and
   101 nt;
4. one sanitized execution manifest; and
5. two local commits: correction, then execution evidence.

Do not alter the accepted assignment. Do not run an audit probe/search,
MMseqs2, finalization, a baseline, or a model.

## Part A — bounded accepted-filename correction

### Defect

The accepted decode manifest records and the live decode generation contains:

```text
duplicate_edges_500.json
duplicate_edges_251.json
duplicate_edges_101.json
```

The current runner instead constructs `exact_rc_edges_<width>.json` during
both real legacy execution and restart-fingerprint preparation. Synthetic
runner fixtures repeat that invented name and therefore conceal the real-path
failure.

### Required correction

- Preserve the explicit caller-supplied decode-artifact directory.
- For each width, derive the required basename from the matching retained
  `duplicate_edges_<width>.json` entry returned by `_load_decode_manifest`.
- Resolve that basename under the explicitly supplied directory.
- Continue requiring the exact manifest-bound byte size and SHA-256 before
  parsing.
- Use one shared resolution helper/path rule in both the CLI restart-skip
  fingerprint precomputation and `stage_legacy_diagnostic`; do not leave the
  second hardcoded occurrence inconsistent merely because the current
  fingerprint omits the path string.
- Update synthetic fixtures/tests to use the real accepted filename contract.
- Add focused regressions proving the old code fails against a real-named
  fixture and that an invented/renamed file cannot substitute for the
  manifest-recorded basename.

Do not rename, copy, symlink, regenerate, or hand-author any accepted real
artifact. Do not change edge contents, hashes, scientific meaning, report
definitions, or any other stage.

Run the focused correction regressions and the affected non-MMseqs 002C test
set inside `.venv-002c-legacy`. Do not run the full real-binary MMseqs2 pipeline
classes in `tests/test_splits_002c_runner.py`. No real CSV, FASTA, membership,
or return-bundle file may be opened during correction implementation/testing.

Commit the correction locally before continuing. The commit may contain only
the necessary runner, synthetic tests/fixtures, and directly affected
documentation. If tests fail or the needed change expands beyond this bounded
defect, stop before real execution.

## Part B — frozen evidence and paths

After the correction commit, revalidate all of the following before the first
real stage:

- `manifests/sequence_assignment_002c2b.json`: SHA-256
  `28aa6687fc335ffcba36eb441ebf2d55ae25565349fc8dfcb48a29be566267f6`;
- `manifests/sequence_decode_002b2.json`: SHA-256
  `d9826b471ef3f12539eaf51be5c21ba8be20190f3d7c6042143e839d6bb0a7b3`;
- `configs/splits/sequence_partitions_002c_v1.toml`: SHA-256
  `35d077ed939137b1b1e97a432b9ff3731be29d64afc922632fb7b3e3b0865bbf`;
- accepted primary assignment selection record:
  `artifacts/splits/sequence_partitions_002c_v1/selected/assign.json`, SHA-256
  `4340e6550e0b494b7831f1ff882de4cd3397ec335b463704ac573b1ab9dc7253`;
- accepted primary membership: 361,180 IDs, 173,465 components, zero split
  components, SHA-256
  `ebca22489c85d4e6fe11b507c7ebd6ad0bd760246c1f96f1505f471aee278907`;
- accepted decode directory:
  `artifacts/splits/sequence_partitions_v1/decode/generations/decode_907eac7a0a69415a`;
- accepted Task 002B cluster-evidence root:
  `artifacts/teammate_run_results/20260928T091014Z_87391_arm64`; and
- all frozen CSV, dataset-audit, proteins, component-membership, and
  component-report hashes through the accepted assignment's current-input
  validator.

Re-hash every real artifact actually consumed against its accepted manifest.
Do not trust a prior successful check or a filename alone.

Use `.venv-002c-legacy` with `PYTHONPATH=src`. Confirm the resolved versions
are Python 3.12, NumPy 2.0.2, SciPy 1.16.1, scikit-learn 1.6.1, and
iterative-stratification 0.1.9.

Create new non-overwriting logs only under:

```text
artifacts/splits/checkpoint_logs/002c2c/
```

Record each command, exit status, start/end UTC, wall time, peak RSS, and disk
before/after. These non-MMseqs stages have no 10-GiB MMseqs launch gate, but a
killed process, resource error, or nonzero exit is still a hard stop.

## Part C — legacy diagnostic

Run exactly one real legacy diagnostic against the accepted primary assignment
root. After Part A, the existing CLI argument may retain its historical name,
but it must resolve the manifest-recorded `duplicate_edges_<width>.json`
basenames inside the supplied accepted decode directory:

```text
PYTHONPATH=src .venv-002c-legacy/bin/python3 -m rbpbench.splits.runner_002c \
  --stage legacy_diagnostic \
  --config configs/splits/sequence_partitions_002c_v1.toml \
  --repo-root . \
  --csv dataset_K562_multilabel_with_NEGs.csv \
  --output-dir artifacts/splits/sequence_partitions_002c_v1 \
  --decode-manifest manifests/sequence_decode_002b2.json \
  --exact-rc-edges-dir artifacts/splits/sequence_partitions_v1/decode/generations/decode_907eac7a0a69415a \
  --cluster-evidence-root artifacts/teammate_run_results/20260928T091014Z_87391_arm64
```

Do not add `--force`, `--authorize-mmseqs`, another stage, or a scientific
override.

Nonzero legacy crossing counts are expected to be possible and are not a stop
condition. They are descriptive evidence about the former row-level split and
must not alter the new assignment.

Stop for any input/provenance/dependency mismatch, nonzero exit, or malformed
report. On success, independently reconcile and report:

- legacy train and holdout counts and their deterministic set digests;
- final-component crossing count/rate over holdout-represented components;
- train rows in crossing components, over all legacy train rows;
- holdout rows in crossing components, over all legacy holdout rows;
- for each width, total clusters, holdout-represented clusters, crossing
  clusters/rate, and train/holdout affected-row counts/rates against their own
  denominators;
- for each width, exact/RC raw crossing-pair count and distinct affected
  holdout-row count/rate; and
- dependency versions, generation binding, and artifact inventory.

Describe per-width membership honestly as direct-or-transitive cluster
co-membership, never as a direct alignment for every pair.

## Part D — exact/RC audits of the accepted new assignment

Only after the legacy diagnostic completes and reconciles, run these three
commands sequentially, in the stated order:

```text
PYTHONPATH=src .venv-002c-legacy/bin/python3 -m rbpbench.splits.runner_002c \
  --stage exact_audit --width 500 \
  --config configs/splits/sequence_partitions_002c_v1.toml \
  --repo-root . \
  --output-dir artifacts/splits/sequence_partitions_002c_v1 \
  --decode-manifest manifests/sequence_decode_002b2.json \
  --decode-fasta-dir artifacts/splits/sequence_partitions_v1/decode/generations/decode_907eac7a0a69415a

PYTHONPATH=src .venv-002c-legacy/bin/python3 -m rbpbench.splits.runner_002c \
  --stage exact_audit --width 251 \
  --config configs/splits/sequence_partitions_002c_v1.toml \
  --repo-root . \
  --output-dir artifacts/splits/sequence_partitions_002c_v1 \
  --decode-manifest manifests/sequence_decode_002b2.json \
  --decode-fasta-dir artifacts/splits/sequence_partitions_v1/decode/generations/decode_907eac7a0a69415a

PYTHONPATH=src .venv-002c-legacy/bin/python3 -m rbpbench.splits.runner_002c \
  --stage exact_audit --width 101 \
  --config configs/splits/sequence_partitions_002c_v1.toml \
  --repo-root . \
  --output-dir artifacts/splits/sequence_partitions_002c_v1 \
  --decode-manifest manifests/sequence_decode_002b2.json \
  --decode-fasta-dir artifacts/splits/sequence_partitions_v1/decode/generations/decode_907eac7a0a69415a
```

Do not add `--force`, `--authorize-mmseqs`, or another stage.

For each width, independently require:

- the exact 361,180-ID assignment/FASTA universe;
- accepted FASTA size and SHA-256;
- the derived duplicate-group count and largest group;
- zero cross-partition exact/RC pair violations;
- zero distinct affected rows; and
- a current selection record bound to the accepted assignment and decode
  generation.

If any width reports a cross-partition violation, stop immediately. Preserve
the accepted diagnostic evidence already written, do not run the remaining
width or later checkpoint, and do not modify assignment.

## Part E — sanitized checkpoint manifest

After all four stages pass/reconcile, write only:

```text
manifests/sequence_non_mmseqs_audits_002c2c.json
```

It must contain no sequence, label, full membership, or large row-ID list.
Include:

- schema/checkpoint/status and correction/execution commits;
- exact commands, resolved dependency versions, and input/upstream hashes;
- per-stage runtime, peak RSS, disk observations, selection-record and output
  artifact hashes/sizes/generation digests;
- the complete aggregate legacy diagnostic described in Part C;
- per-width exact/RC new-assignment summaries from Part D;
- independent reconciliation conclusions; and
- explicit boundary evidence that MMseqs2, audit probe/search, finalization,
  baseline, and model stages did not run.

Validate the JSON and independently reproduce all recorded hashes and summary
values before staging it. Stage and commit only this manifest in the execution
evidence commit. Retain ignored generations/logs unchanged for review.

## Stop conditions

Stop without patching or retrying for:

- any frozen hash, accepted assignment, decode, cluster-evidence, or dependency
  mismatch;
- any target output/selection record that existed before this checkpoint;
- any nonzero exit, timeout, killed process, resource failure, malformed
  report, inventory mismatch, or nondeterministic digest;
- any new-split exact/RC cross-partition violation;
- any need to change assignment, grouping, thresholds, labels, or report
  definitions; or
- any need to launch MMseqs2 or a later stage.

Do not stop merely because the former split shows nonzero leakage; report it
with the reviewed denominators.

## Required return

Return:

1. correction commit, exact changed-file list, tests, and proof that the
   real/synthetic filename mismatch is closed;
2. execution-manifest commit and staged-file audit;
3. all four exact commands, exit statuses, runtime, peak RSS, and disk evidence;
4. the complete aggregate legacy diagnostic and an appropriately qualified
   interpretation;
5. all three new-assignment exact/RC audit summaries and zero-violation proof;
6. input/upstream/inventory/hash reconciliation;
7. sanitized manifest path, byte size, and SHA-256;
8. anomalies, if any;
9. proof that no MMseqs2, audit probe/search, finalization, baseline, or model
   stage ran; and
10. clean worktree and `git diff --check` result.

End with: **Task 002C-3 fresh cross-partition MMseqs2 audits were not
started.**
