# Task 002C-2C planning review request — legacy and exact/RC diagnostics

## Reviewer role and boundary

Act as the second scientific/methodological reviewer for the next bounded
checkpoint of `docs/tasks/002c_partition_assignment_and_audit.md`. Review the
plan only. Do not edit code, open the real CSV or FASTAs, inspect row-level
membership, run the legacy fold, execute an audit, launch MMseqs2, or begin a
baseline/model stage.

The planning reviewer has independently accepted Task 002C-2B in
`docs/reviews/002c2b_real_assignment_acceptance.md`. Task 002C-2C must use that
assignment unchanged and run locally on the current 16-GiB Mac.

## Accepted inputs

- Accepted assignment code correction: `a15fcfa`.
- Accepted real assignment evidence: `2d5d114`.
- Independent acceptance review: `436ec1c`.
- Primary assignment root:
  `artifacts/splits/sequence_partitions_002c_v1`.
- Primary membership SHA-256:
  `ebca22489c85d4e6fe11b507c7ebd6ad0bd760246c1f96f1505f471aee278907`.
- Assignment manifest:
  `manifests/sequence_assignment_002c2b.json`, SHA-256
  `28aa6687fc335ffcba36eb441ebf2d55ae25565349fc8dfcb48a29be566267f6`.
- Accepted decode manifest:
  `manifests/sequence_decode_002b2.json`, SHA-256
  `d9826b471ef3f12539eaf51be5c21ba8be20190f3d7c6042143e839d6bb0a7b3`.
- Accepted decode generation:
  `artifacts/splits/sequence_partitions_v1/decode/generations/decode_907eac7a0a69415a`.
- Accepted Task 002B return root:
  `artifacts/teammate_run_results/20260928T091014Z_87391_arm64`.

The accepted assignment contains 361,180 IDs and 173,465 indivisible
components, with train/validation/test row fractions 68.2388/15.8899/15.8713%,
zero split components, and all positive/known-negative evaluation floors
passing without repair.

## Checkpoint objective

Run only the two non-MMseqs2 diagnostics that remain before the fresh search
audit:

1. reproduce the submitted notebook's original fold-0 80/20 row-level split
   and quantify how much accepted sequence grouping crosses that old
   train/holdout boundary; and
2. independently regenerate exact/reverse-complement identities from the
   accepted decoded FASTAs and require zero such relationships across the new
   train/validation/test boundaries.

No result from this checkpoint may alter the accepted assignment. The legacy
diagnostic is descriptive: nonzero old-split leakage is a finding, not a
failure and not permission to tune thresholds or membership. In contrast, any
exact/RC cross-boundary violation in the new split is a hard stop before
Task 002C-3.

## Proposed execution sequence

### 1. Preflight and evidence currency

Before each real stage:

- verify the branch, clean worktree, accepted-commit ancestry, and repository
  origin;
- revalidate the current accepted assignment and its five frozen inputs;
- revalidate the decode manifest and the exact width-specific FASTA or
  duplicate-edge artifacts used by that stage;
- revalidate all eight accepted Task 002B cluster-evidence files through the
  shared verifier before the legacy diagnostic;
- require the relevant selection record/output generation to be absent before
  first execution; do not delete, overwrite, adopt, or `--force` prior output;
  and
- record command, exit status, wall time, peak RSS, and disk before/after in
  new non-overwriting checkpoint logs.

### 2. Bounded accepted-filename correction

Planning inspection found one real-path mismatch before execution:

- `manifests/sequence_decode_002b2.json` identifies the accepted artifacts as
  `duplicate_edges_500.json`, `duplicate_edges_251.json`, and
  `duplicate_edges_101.json`;
- those exact files exist in the accepted decode generation and match the
  manifest's sizes/hashes; but
- `stage_legacy_diagnostic` currently hardcodes
  `exact_rc_edges_<width>.json`, a filename used only by synthetic fixtures.

The proposed correction is to preserve the explicit caller-supplied accepted
decode-artifact directory but resolve each width using the basename recorded
in the accepted decode manifest (`duplicate_edges_<width>.json`). Continue to
verify its exact manifest-bound size and SHA-256 before parsing. Do not rename,
copy, symlink, regenerate, or hand-author replacement edge files, and do not
change their scientific interpretation.

Update synthetic fixtures/tests to use the real accepted filename contract and
prove that a correctly hashed file under an invented filename cannot silently
substitute for the manifest-recorded artifact. Keep the correction limited to
the runner/interface, tests, and directly affected documentation. Commit and
review it before opening real Task 002C-2C inputs.

### 3. Legacy split diagnostic

Use `.venv-002c-legacy` and the pinned environment:

- Python 3.12;
- NumPy 2.0.2;
- SciPy 1.16.1;
- scikit-learn 1.6.1; and
- iterative-stratification 0.1.9.

Reproduce exactly:

```text
MultilabelStratifiedKFold(
    n_splits=5,
    shuffle=True,
    random_state=42,
)
fold_index = 0
stratification input = positive-only targets * masks
```

Report at minimum:

- legacy train and holdout counts and deterministic index-set digests;
- final-component crossings, including crossing components over components
  represented in holdout and affected train/holdout rows over their own row
  denominators;
- for each 500/251/101 width, crossing connected-component clusters over
  clusters represented in holdout and affected train/holdout rows over their
  own denominators; and
- exact/RC legacy-boundary raw pair counts plus distinct affected holdout-row
  counts/rates.

Cluster membership is a direct-or-transitive co-membership relation; do not
describe every affected pair as a direct alignment. Do not compare model
scores, change assignment, or turn this descriptive result into a pass/fail
gate.

### 4. Independent exact/RC audit of the new assignment

Run `exact_audit` sequentially for widths 500, 251, and 101 using the accepted
decode FASTAs. For each width:

- require exactly the accepted 361,180-ID universe;
- require the accepted FASTA size and SHA-256;
- canonicalize forward/reverse-complement sequence identity independently of
  MMseqs2;
- report duplicate-group count, largest group, raw violating-pair count,
  distinct affected-row count, and their correctly labelled denominators;
- require zero cross-partition violations; and
- stop immediately on any nonzero violation or stale/mismatched evidence.

The expected duplicate-group count is not itself a gate typed from memory; it
must be derived from the accepted FASTA and compared with the accepted decode
evidence. Only the cross-partition count has the zero-violation acceptance
rule.

### 5. Reconciliation and sanitized evidence

Independently re-read the accepted diagnostic records and reports. Recompute
all headline counts/rates from the retained evidence where practical, verify
all inventories and upstream generation bindings, and confirm that only these
selection records were added:

- `legacy_diagnostic`;
- `exact_audit_500`;
- `exact_audit_251`; and
- `exact_audit_101`.

Write one small sanitized manifest:

```text
manifests/sequence_non_mmseqs_audits_002c2c.json
```

It may contain aggregate counts, rates, digests, hashes, commands, dependency
versions, runtimes, and resource observations. It must not contain raw
sequences, labels, full membership maps, or large row-ID lists.

Commit only the bounded correction files in one commit and, after successful
execution, the sanitized manifest in a separate commit. Do not push or merge.

## Stop conditions

Stop without patching or retrying for:

- any frozen input, accepted assignment, decode, or cluster-evidence mismatch;
- any dependency-version mismatch;
- any existing or ambiguous selection record/generation for these stages;
- a nonzero exit, timeout, killed process, or resource failure;
- any exact/RC cross-partition violation in the new split;
- nondeterministic fold digests or inconsistent denominators;
- any need to change assignment, grouping thresholds, labels, or scientific
  definitions; or
- any temptation to start an audit probe/search, MMseqs2, finalization,
  baseline, or model stage.

## Questions requiring an explicit answer

1. Is the legacy diagnostic correctly treated as descriptive even if it finds
   extensive crossing, while the new split's exact/RC audit remains a hard
   zero-violation gate?
2. Are the component-, cluster-, train-row-, holdout-row-, pair-, and
   affected-row denominators sufficient to prevent overstating leakage?
3. Is reproducing the old splitter from the pinned environment and recording
   deterministic index-set digests sufficient, or is another scientifically
   necessary check missing?
4. Is consuming the manifest-recorded `duplicate_edges_<width>.json` files
   directly the correct fix for the real/synthetic filename mismatch? Identify
   any smaller safe alternative if not.
5. Is one accepted legacy run plus independent report reconciliation
   sufficient, rather than executing the same deterministic diagnostic twice?
6. Are three sequential, independent exact/RC width audits sufficient before
   the later fresh MMseqs2 searches?
7. Is the sanitized manifest boundary complete without retaining row-level
   violation lists when all new-split violation counts must be zero?
8. Identify only blocking scientific/correctness issues. Defer optional
   refactors, performance tuning, and broader documentation changes.

## Requested verdict

Return one of:

- **Approve**;
- **Approve with bounded corrections**; or
- **Stop**, naming the precise blocker.

For every requested correction, state the concrete false conclusion or
integrity failure it prevents and the earliest checkpoint that needs it. Do
not execute Task 002C-2C during this planning review.
