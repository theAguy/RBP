# Task 002C-2A Claude executor handoff — legacy cluster evidence

## Authorization and Git boundary

Implement Task 002C-2A only on branch `issue-002c-partition-assignment`,
starting from commit `6f86d2a` or a descendant containing this handoff. Work
locally on the current project Mac. Commit the implementation and return the
required evidence, but do not merge or push.

Before editing, verify:

- repository root and origin `https://github.com/theAguy/RBP.git`;
- branch `issue-002c-partition-assignment`;
- `6f86d2a` is an ancestor of `HEAD`; and
- the tracked worktree is clean apart from this handoff commit if applicable.

Stop for an unexpected branch, remote, ancestry failure, unrelated tracked
change, or any mismatch in the frozen files below. Do not discard or overwrite
an existing change.

## Required reading, in order

1. `CONTRIBUTING.md`
2. `docs/tasks/002c2a_legacy_cluster_evidence.md`
3. `docs/reviews/002c2a_legacy_cluster_evidence_review_request.md`
4. `docs/reviews/002c2a_legacy_cluster_evidence_reconciliation.md`
5. `docs/reviews/002c1_partition_orchestration_acceptance.md`
6. the former-split and checkpoint sections of
   `docs/tasks/002c_partition_assignment_and_audit.md`
7. `docs/SPLITS.md`
8. the affected config/code/tests only.

The task and reconciliation are authoritative. Do not reopen their scientific
decision.

## Exact real-evidence authorization

This checkpoint may read only these files under
`artifacts/teammate_run_results/20260928T091014Z_87391_arm64/`:

- `RETURN_MANIFEST.json`;
- `RETURN_INVENTORY.json`;
- `selected_records/cluster_500.json`;
- `selected_records/cluster_251.json`;
- `selected_records/cluster_101.json`;
- `memberships/cluster_500.membership.tsv`;
- `memberships/cluster_251.membership.tsv`; and
- `memberships/cluster_101.membership.tsv`.

Revalidate every byte size and SHA-256 against the frozen table in the task
before parsing. The three membership TSVs total about 23 MB and are the only
large real artifacts authorized here.

Do not open, hash, stat, inventory, copy, or otherwise access:

- `dataset_K562_multilabel_with_NEGs.csv`;
- decoded FASTAs or duplicate-edge contents;
- final Task 002B union membership or component report;
- any other returned Task 002B file;
- model files, predictions, references, or coordinate artifacts.

Do not use the network. Do not launch MMseqs2 or any other external scientific
tool.

## Scientific correction to implement

The three accepted `createtsv` files are per-width connected-component cluster
memberships. They are not complete or necessarily direct pairwise similarity
edges. A representative/member TSV row must never be described or consumed as
a direct alignment.

Replace `directly_edge_matched_by_width` with a per-width cluster-boundary
diagnostic. For each width, the report must contain:

- total cluster count;
- clusters represented in the legacy holdout;
- clusters containing at least one legacy-train and one legacy-holdout row;
- crossing-cluster rate over clusters represented in holdout;
- train rows in crossing clusters, count and rate over all legacy-train rows;
  and
- holdout rows in crossing clusters, count and rate over all legacy-holdout
  rows.

Use names that explicitly say `cluster`/`co-membership` or
`cluster_boundary`; do not retain the old direct-edge field as an alias. The
report must state that relationships may be direct or transitive.

Preserve the union-component crossing diagnostic and exact/reverse-complement
diagnostic unchanged.

## Required implementation

### 1. Evidence configuration and ingestion

Replace the production `[legacy_edges.similarity_edges]` placeholder contract
with a per-width cluster-membership evidence contract. It must bind, for every
width:

- membership relative path, byte size, and SHA-256;
- selected-record relative path, byte size, and SHA-256;
- expected selected generation digest;
- expected member count, cluster count, and largest cluster size; and
- evidence kind identifying connected-component membership.

The evidence contract must also bind `RETURN_MANIFEST.json` and
`RETURN_INVENTORY.json` by relative path, byte size, and SHA-256 so their
cross-check is reproducible rather than dependent on whichever files happen to
be present under the supplied root.

Do not hard-code the collaborator's absolute path. The legacy-diagnostic CLI
must accept an explicit portable Task 002B return root (or equally clear
explicit membership/record roots) and resolve only the pinned children beneath
it. Reject traversal and symlink escapes. If renaming an existing tracked
module, use `git mv` so its history is preserved.

Before later legacy-diagnostic use, and in the dedicated validation path for
this checkpoint:

1. verify all source hashes/sizes;
2. cross-check return inventory/manifest entries;
3. require each selected record to declare the expected width, `stage` =
   `cluster`, `executed` = true, sample count, generation digest, and the same
   membership inventory hash/size;
4. stream-parse exactly two tab-separated fields per non-empty line;
5. require every canonical ID `row_0..row_361179` exactly once as a member and
   every representative to be canonical; and
6. reproduce the expected cluster count and largest-cluster size.

Missing, repeated, foreign, malformed, mismatched, or stale evidence fails
closed. Do not attempt repair.

The accepted collaborator run used the reviewed Apple-Silicon Task 002B
exception. Do not reject its selected records merely because their arm64
MMseqs2 binary hash differs from the earlier osx-64 environment; bind the
already accepted selected-record hashes and generation digests instead.

### 2. Diagnostic and restart/provenance changes

Update the legacy-diagnostic implementation to consume the verified membership
mapping by width and calculate the required cluster-boundary metrics. Bind all
three membership files and all three selected records—keyed by width and
evidence kind—into:

- the stage fingerprint;
- selection-record evidence;
- report provenance; and
- finalization's current-evidence revalidation.

A changed membership, selected record, generation digest, source manifest,
config, or assignment must invalidate the legacy diagnostic. A missing source
generation is not relevant because this checkpoint deliberately consumes the
accepted returned copy; its pinned bytes are the authority.

Keep exact/RC evidence independently bound through the accepted decode
manifest. If CLI arguments must be separated so membership and exact/RC files
have distinct roots, do so explicitly and test it; never infer one location
from the other.

### 3. Documentation correction

In `docs/tasks/002c_partition_assignment_and_audit.md`:

- remove the temporary evidence-correction warning;
- replace the obsolete direct-edge bullet itself with the complete per-width
  cluster-boundary diagnostic and denominators; and
- correct later 002C-2/002C-4 wording if it could imply that the retired
  direct-edge metric remains required.

Update `docs/SPLITS.md`, code docstrings, config comments, and affected test
names/assertions. A repository search after the correction must find no active
production claim that Task 002B membership rows are direct similarity edges.
Historical review/handoff records may retain the old wording when clearly
historical; do not rewrite accepted history merely to make a grep empty.

### 4. Sanitized evidence manifest

Provide a deterministic, small
`manifests/sequence_legacy_cluster_evidence_002c2a.json` containing:

- schema and evidence kind;
- relative source names, sizes, and SHA-256 values;
- selected-record sizes/hashes and generation digests;
- the accepted MMseqs2 command semantics transcribed from those records;
- member/cluster/largest-cluster summaries and reconciliation status; and
- an explicit statement that cluster co-membership can be direct or transitive
  and is not a retained direct-alignment edge list.

Do not include row-level IDs, cluster memberships, sequences, labels, absolute
collaborator paths, or large artifacts. Re-running the evidence validation must
reproduce this manifest byte-for-byte.

## Required focused tests

Use tiny synthetic fixtures except for the single authorized real validation
pass. Tests must cover at least:

1. a transitive A-B-C cluster where A/C co-membership is reported but never
   labeled a direct A-C match;
2. exact per-width counts and all three denominators/rates;
3. hash/size/selected-record/generation-digest mismatch;
4. malformed rows, duplicate/missing/foreign members, and foreign
   representatives;
5. wrong width/stage/executed/sample count and membership-inventory binding;
6. changed membership or selected record invalidating restart/finalization;
7. portable root confinement, traversal, and symlink escape refusal;
8. deterministic sanitized-manifest output without forbidden row-level data;
9. preservation of exact/RC and union-component diagnostic behavior; and
10. dry-run opening no declared real input.

Run the focused affected 002C tests once and the non-MMseqs split tests needed
to catch regressions once. Do not run real-binary MMseqs2 tests or a repository-
wide suite: neither is proportionate to this no-subprocess correction. Report
the exact commands and counts.

## Real validation and stop boundary

After tests pass, run only the dedicated evidence-validation operation over
the eight authorized returned files. Confirm all three accepted summaries and
write the sanitized manifest. Then stop.

Do not open the real CSV or FASTAs. Do not run `assign`,
`legacy_diagnostic`, `exact_audit`, `audit_probe`, `audit_search`, `finalize`,
MMseqs2, a baseline, or a model. Task 002C-2 real scientific execution remains
unauthorized.

## Commit and return

Commit only intended source, tests, config, docs, and the small sanitized
manifest. Do not stage anything under `artifacts/` or any large/generated
membership file. Do not push or merge.

Return:

1. commit hash and changed-file list;
2. the replacement schema and exact scientific interpretation;
3. focused test commands/results;
4. real evidence-validation command, runtime/peak memory if available, and
   all three reconciled summaries;
5. sanitized manifest path, size, and SHA-256;
6. proof that forbidden real inputs/tools/stages were untouched;
7. `git diff --check`, staged-file audit, and clean-worktree status; and
8. any remaining gap.

End with: **Task 002C-2 real assignment was not started.**
