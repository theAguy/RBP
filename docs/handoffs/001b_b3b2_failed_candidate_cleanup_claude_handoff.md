# Executor handoff — Task 001B B3B-2 failed-candidate cleanup

Claude, perform only the evidence-verified cleanup below. This closes Task 001B
without retrying coordinate execution.

## Required reading and Git boundary

1. Work only on `issue-001b-coordinate-execution` from the commit containing
   this handoff and
   `manifests/coordinate_index_hg38_b3b2_stop.json`.
2. Read
   `docs/reviews/001b_b3b2_resource_stop_and_coordinate_deferral.md`, the stop
   manifest, and the existing B3B-2 handoff.
3. Require the expected origin, a clean tracked worktree, and `fce6eb8` as an
   ancestor. Do not push, merge, rewrite history, or change code/tests/config.

## Authorized action

Delete exactly this unaccepted candidate directory after all checks pass:

```text
indices/hg38/generations/index_bfeb7be42185425f
```

No runner stage, mapper, network request, test suite, reference operation, CSV
read, probe, or model action is authorized.

## Fail-closed checks before deletion

- Resolve the repository root independently from Git.
- Resolve the target and require it to be exactly the named direct child of
  `<repo>/indices/hg38/generations/`.
- Refuse if the target or any ancestor from `indices/` downward is a symlink.
- Require `indices/hg38/index.json` to remain the non-executed record with
  SHA-256
  `da375f2259a696bc1a2baadbb4010bd2acd6532816be4cb9423a401500f4f37f`.
- Require the target to be absent from accepted state/provenance selection
  records.
- Recompute all ten file names, sizes, SHA-256 values, and the exact
  5,424,083,332-byte total from the committed stop manifest. Any disagreement
  is a hard stop.
- Print the resolved target and complete deletion list before removing it.

## Preserve exactly

- `indices/hg38/index.json` and everything outside the one candidate;
- `references/sources/GRCh38.p14/`;
- `references/derived/hg38/`;
- `artifacts/coordinate_feasibility/hg38/b3b1_logs/`;
- `artifacts/coordinate_feasibility/hg38/b3b2_logs/`;
- all committed manifests and documentation.

## Receipt and commit

After deletion, update only the `cleanup` object in
`manifests/coordinate_index_hg38_b3b2_stop.json` with:

- `completed: true`;
- UTC completion time;
- executor starting commit;
- exact resolved deleted path and 5,424,083,332 reclaimed candidate bytes;
- unchanged post-cleanup `indices/hg38/index.json` hash;
- proof that the target is absent and every preserve path remains present;
- free disk before/after;
- `receipt_commit` left as `null` in file content because a commit cannot
  self-identify without changing its own hash.

Validate JSON, run `git diff --check`, stage only that manifest, and commit
locally. Return all checks, the deletion list, disk change, staged-file audit,
commit hash, and worktree status. End exactly with:

`Task 001B is closed; Task 002 was not started.`
