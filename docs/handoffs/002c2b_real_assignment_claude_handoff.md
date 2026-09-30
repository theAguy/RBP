# Task 002C-2B Claude executor handoff — real component assignment

## Authorization and Git boundary

Execute Task 002C-2B assignment only on branch
`issue-002c-partition-assignment`, starting from acceptance commit `6e49097`
or a descendant containing this handoff. Work on the current project Mac.
Commit only the small sanitized execution manifest and return evidence. Do not
push or merge.

Before any real input access, verify:

- repository root and origin `https://github.com/theAguy/RBP.git`;
- branch `issue-002c-partition-assignment`;
- `6e49097` is an ancestor of `HEAD`;
- tracked worktree is clean; and
- both output roots named below are absent or empty.

If either output root contains any prior file, stop and list it. Do not delete,
overwrite, adopt, or force-rerun prior evidence.

## Required reading, in order

1. `CONTRIBUTING.md`
2. `docs/tasks/002c_partition_assignment_and_audit.md`
3. `docs/reviews/002c_partition_assignment_reconciliation.md`
4. `docs/reviews/002c1_partition_orchestration_acceptance.md`
5. `docs/reviews/002c2a_legacy_cluster_evidence_acceptance.md`
6. `configs/splits/sequence_partitions_002c_v1.toml`
7. the `assign` portions of `src/rbpbench/splits/runner_002c.py`,
   `assignment.py`, `ingestion.py`, `audit.py`, and `output.py`.

This handoff authorizes execution, not another planning or implementation
round. Do not edit code/config/tests unless a real correctness defect stops the
run; if that happens, preserve evidence and return the defect without patching
or retrying.

## Scope

Run the accepted deterministic whole-component assignment twice in separate
empty output roots, compare their scientific outputs, write one small sanitized
manifest, and stop.

This checkpoint may read exactly these five frozen real inputs:

| Input | Bytes | SHA-256 |
|---|---:|---|
| `dataset_K562_multilabel_with_NEGs.csv` | 724,425,277 | `982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945` |
| `manifests/dataset_audit.json` | as pinned | `e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c` |
| `configs/proteins.tsv` | as pinned | `374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9` |
| `artifacts/teammate_run_results/20260928T091014Z_87391_arm64/final_component_result/component_membership.tsv.gz` | 14,578,797 | `6000c340056ba8204432e7f4c417fb811f8a3d1a5b1c091dea98461862c7b692` |
| `artifacts/teammate_run_results/20260928T091014Z_87391_arm64/final_component_result/component_report.json` | 13,036,977 | `b8b5872a4cc5061c562de871ec4500876fcdb72afcab069b21ab2bb44cb3e186` |

Do not open decoded FASTAs, per-width cluster memberships, return-bundle files,
models, predictions, references, coordinate artifacts, or any other ignored
real result. Do not use the network or launch MMseqs2.

## Environment and output roots

Use the accepted `.venv-002c-legacy` environment and `PYTHONPATH=src`.

Primary output root:

```text
artifacts/splits/sequence_partitions_002c_v1
```

Independent repeat root:

```text
artifacts/splits/sequence_partitions_002c_v1_repeat_002c2b
```

Retain both roots unchanged through review. They are Git-ignored. Do not copy
their large membership artifacts into Git.

Capture each invocation's exact command, stdout, stderr, wall time, peak RSS,
and disk before/after in non-overwriting checkpoint logs outside the two output
roots, for example:

```text
artifacts/splits/checkpoint_logs/002c2b/
```

## Pre-start validation

Before the first assignment:

1. re-hash/re-size all five inputs and require exact matches;
2. confirm the component report declares 361,180 rows, 173,465 components,
   and no giant-component gate failure;
3. confirm the two output roots are absent/empty;
4. confirm no `rbpbench.splits.runner_002c` or MMseqs2 process is active; and
5. record free disk and available/installed memory. Resource observations are
   evidence, not permission to change the accepted assignment contract.

Stop for any mismatch or existing output. Do not use `--force`.

## Primary assignment

Run exactly:

```text
PYTHONPATH=src .venv-002c-legacy/bin/python3 -m rbpbench.splits.runner_002c \
  --stage assign \
  --config configs/splits/sequence_partitions_002c_v1.toml \
  --repo-root . \
  --csv dataset_K562_multilabel_with_NEGs.csv \
  --component-membership artifacts/teammate_run_results/20260928T091014Z_87391_arm64/final_component_result/component_membership.tsv.gz \
  --component-report artifacts/teammate_run_results/20260928T091014Z_87391_arm64/final_component_result/component_report.json \
  --audit-json manifests/dataset_audit.json \
  --proteins-tsv configs/proteins.tsv \
  --output-dir artifacts/splits/sequence_partitions_002c_v1
```

Do not add `--force`, `--authorize-mmseqs`, another stage, or a scientific
override.

If it exits nonzero, violates a 30/30 floor, exceeds the accepted three-
percentage-point row-balance boundary, reports an input/component mismatch, or
raises any repair/resource error, stop. Preserve the transactional state and
logs; do not patch, weaken a floor, split a component, or retry.

## Independent repeat

Only after the primary run passes every reconciliation below, repeat the exact
same command with only this substitution:

```text
--output-dir artifacts/splits/sequence_partitions_002c_v1_repeat_002c2b
```

This is an independent second execution. Each accepted assignment also performs
its built-in reordered-row byte-equality check. Do not reuse/copy the primary
selection record or generation into the repeat root.

## Required reconciliation

Independently inspect the two accepted assignment records, generation
inventories, membership artifacts, and assignment manifests. Confirm:

1. exactly 361,180 canonical IDs occur once in each result;
2. exactly 173,465 accepted components occur and no component is split across
   partitions;
3. partitions are exactly `train`, `validation`, and `test`;
4. row fractions are within three percentage points of 70/15/15;
5. every protein 1–122 has at least 30 known positives and 30 known negatives
   in both validation and test;
6. unknown labels did not enter positive/known-negative balance counts;
7. all configured input hashes and assignment parameters are recorded;
8. every generated artifact matches its selection-record inventory;
9. primary and repeat decompressed memberships are byte-identical (the gzip
   files should also be byte-identical because compression is deterministic);
10. primary and repeat scientific manifests/summaries are identical; and
11. neither run produced or invoked a legacy diagnostic, exact audit,
    audit probe/search, finalization, MMseqs2, baseline, or model stage.

Different generation-directory paths/digests caused solely by the intentional
unique generation path are operational and should not be compared as
scientific output. Disclose them rather than treating them as nondeterminism.

## Sanitized checkpoint manifest

Write only:

```text
manifests/sequence_assignment_002c2b.json
```

It must contain no row-level IDs, labels, or embedded component maps. Include:

- schema/checkpoint/status and execution commit;
- exact commands and environment versions;
- five input paths relative to the repository, sizes, and hashes;
- each run's runtime, peak RSS, disk observations, output generation digest,
  membership/report relative paths, sizes, and hashes;
- row/component/partition counts and row fractions;
- minimum validation/test positive and known-negative counts, including the
  protein/class attaining each minimum;
- count/list of any balance deviations above three percentage points;
- repair-step/proposal summary available from accepted output;
- primary/repeat byte-identity conclusions; and
- explicit boundary evidence that later stages did not run.

Validate JSON, reproduce all recorded output hashes from disk, and ensure the
manifest is small before staging it.

## Commit and return

Stage and commit only
`manifests/sequence_assignment_002c2b.json`. Do not stage output roots, logs,
the CSV, collaborator artifacts, code, config, tests, or documentation. Do not
push or merge.

Return:

1. commit hash and staged-file audit;
2. exact commands and exit statuses;
3. runtime, peak memory, and disk evidence for both runs;
4. the complete reconciliation results, including partition counts/fractions
   and all four validation/test minimum label counts;
5. primary/repeat membership and scientific-summary equality proof;
6. manifest path, byte size, and SHA-256;
7. anomalies or disclosed balance deviations;
8. proof that no later stage/tool/model ran; and
9. clean worktree and `git diff --check` result.

End with: **Task 002C-2C legacy diagnostic and exact/RC audits were not
started.**
