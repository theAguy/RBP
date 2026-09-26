# Executor handoff — Task 002B-1 final bounded correction

Claude, correct commit `acc677f` only for the four items below. This is a
convergence pass, not a redesign. Use tiny synthetic fixtures only and do not
start Task 002B-2.

## Git and scope

1. Work on `issue-002-sequence-partitions` from the commit containing this
   handoff. Verify the expected origin, clean tracked worktree, and `acc677f`
   as an ancestor. Do not push, merge, or rewrite history.
2. Read `docs/reviews/002b1_orchestration_correction_review.md` and the prior
   002B task/reconciliation/review documents.
3. Preserve all accepted scientific parameters and the accepted removal of
   `--split-memory-limit 8G`.

## FC1 — Require a current complete prerequisite chain

Implement shared fail-closed helpers that recompute current evidence rather
than merely loading an intact selected record:

- a current preflight must match the live config, CSV, audit JSON, proteins
  TSV, MMseqs2 path/version/SHA-256, and approved macOS host boundary; recheck
  the configured installed-RAM minimum and free-disk floor before each real
  stage rather than treating an old preflight's host snapshot as current;
- a current decode must be intact and reproduce its fingerprint from that
  current preflight plus the live CSV/config;
- probe, cluster, and component-report CLI paths must use the current decode
  helper, not `_require_accepted("decode")` alone;
- decode must refuse a stale preflight before creating a generation; and
- probe/cluster must independently reject an MMseqs2 binary whose current
  version/hash does not match the production config before launching any
  subprocess, including direct stage-function calls used outside `main()`.

Do not silently rerun prerequisites. Raise a clear stale-prerequisite error
that names the earliest stage the operator must rerun.

Required regressions:

1. audit JSON mutation after accepted preflight blocks decode before a
   generation is created;
2. proteins TSV mutation does the same;
3. a same-version binary whose bytes change after accepted preflight/decode
   blocks probe before any clustering subprocess; and
4. stale preflight/decode cannot be used to skip a downstream accepted stage.

## FC2 — Enforce the final resource snapshot

After every MMseqs2 child exits, unconditionally re-measure both:

- total Task 002 output bytes against the configured 50-GiB ceiling; and
- free disk against the configured 80-GiB floor.

This final check must run even if the child completed before the first polling
interval. A violation must fail the attempt and let the outer transaction
discard only the new candidate while preserving prior accepted evidence.
Persist the successful final measurements in command/stage provenance.

Add a fast fake-process regression that completes before the first poll and
prove a low final free-disk reading still fails. Retain the existing live
growth and process-group tests.

## FC3 — Make synthetic tests host-independent

Fixture helpers that are not specifically testing installed-RAM detection
must mock a sufficient numeric installed-RAM value. Keep or add focused tests
showing that production preflight fails closed for `None` and for a value
below the configured minimum. Do not weaken production fail-closed behavior.

The reviewer must be able to run `tests/test_splits_b1_corrections.py` in a
restricted macOS environment where `sysctl` is unavailable and have the
unrelated synthetic tests exercise their intended assertions.

## FC4 — Complete component-report evidence binding

Add immutable snapshots of the selected artifact inventories for decode and
all three cluster generations to the accepted component-report record. Bind
them to the corresponding stage fingerprints/generation digests already
recorded. Revalidation must continue to reject missing, added, or changed
upstream files.

Add a focused schema/assertion test. Do not change component construction or
scientific reporting.

## Verification and return

To avoid another long validation loop, run only what this change needs:

1. the new focused final-correction tests;
2. the full synthetic split suite once;
3. the existing real-binary split smoke file once, with none skipped; and
4. `git diff --check` plus a staged-file audit.

The already accepted command-science fixtures do not need two more complete
multi-minute repetitions. Do not fix unrelated coordinate failures.

Commit the bounded correction locally and return:

1. commit and changed-file list;
2. FC1-FC4 resolution;
3. focused tests and proof they fail on `acc677f`;
4. synthetic-suite and real-binary-smoke results;
5. diff/status/staged-file audit;
6. confirmation that no real CSV/artifact/reference/model/network was
   touched; and
7. remaining gaps, if any.

Stop after the local commit. End exactly with:

`Task 002B-2 real decode was not started.`
