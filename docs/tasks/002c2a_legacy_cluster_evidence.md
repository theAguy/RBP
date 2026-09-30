# Task 002C-2A — Correct and bind the legacy clustering evidence

**Status:** accepted; see
`docs/reviews/002c2a_legacy_cluster_evidence_acceptance.md`
**Parent:** `docs/tasks/002c_partition_assignment_and_audit.md`
**Branch:** `issue-002c-partition-assignment`

## Objective

Replace Task 002C-1's impossible placeholder for three purported "direct
similarity-edge" files with a scientifically accurate diagnostic based on the
three accepted Task 002B per-width cluster-membership tables. Validate and bind
those tables, update the synthetic implementation and documentation, and stop
before reading the real dataset CSV or running assignment.

This is a correction to the *description and use of retained evidence*. It does
not change the accepted Task 002B clustering, thresholds, components, or final
component report.

## Why the correction is necessary

The accepted Task 002B return contains, for each width, the output of:

```text
mmseqs createtsv sequenceDB sequenceDB clusterDB membership.tsv
```

MMseqs2 documents this cluster TSV as `cluster-representative` and
`cluster-member` rows. It also documents `--cluster-mode 1` as connected-
component clustering: every sequence reachable by breadth-first traversal is
placed in the component. Consequently, a member can be connected to its
reported representative through another sequence; the TSV row is a cluster
assignment, not proof that the two endpoints were directly aligned above the
frozen thresholds.

The Task 002B return did not include the internal alignment-result databases.
We therefore cannot honestly reconstruct or claim the complete set of direct
Task 002B similarity edges. We must not convert representative/member rows to
invented "direct edges."

Primary references:

- MMseqs2 user guide, connected-component algorithm and cluster TSV format:
  <https://www.mmseqs.com/latest/userguide.pdf>
- MMseqs2 source parameter definitions for `--cluster-mode 1` and
  `--single-step-clustering`:
  <https://github.com/soedinglab/MMseqs2/blob/master/src/commons/Parameters.cpp>

## Correct replacement diagnostic

Retain the already accepted union-component crossing diagnostic. Replace the
unsupported field `directly_edge_matched_by_width` with a clearly named
per-width cluster-boundary diagnostic.

For each width (500, 251, 101), report:

- total clusters;
- clusters represented in the legacy holdout;
- clusters containing at least one legacy-train and at least one
  legacy-holdout row;
- crossing-cluster rate over clusters represented in the holdout;
- legacy-holdout rows in a crossing cluster, count and rate over all legacy
  holdout rows; and
- legacy-train rows in a crossing cluster, count and rate over all legacy
  train rows.

The report and documentation must say that co-membership demonstrates a
direct-or-transitive relationship under the frozen per-width Task 002B
clustering. It must not say that every affected holdout row has a direct
pairwise alignment to a training row.

This remains useful because it attributes the former split's component leakage
to each protected representation separately. The later Task 002C-3 fresh
cross-partition MMseqs2 searches remain the independent pairwise zero-leakage
acceptance test for the new split.

## Frozen accepted inputs

All paths below are relative to:

```text
artifacts/teammate_run_results/20260928T091014Z_87391_arm64/
```

The checkpoint may read only the small return metadata, the three selected
cluster records, and the three membership TSVs listed here:

| Evidence | Bytes | SHA-256 |
|---|---:|---|
| `RETURN_MANIFEST.json` | 11,390 | `c5936acaf768ec68edd67eecb714bd3ebbdaebc47ccca230832604520d85681a` |
| `RETURN_INVENTORY.json` | 5,510 | `f117a29b8100bf09cc80f36051b0c6794401e65d57de841068be27f2aa788767` |
| `selected_records/cluster_500.json` | 28,224 | `2a94a2f0982744a46c1342e61d0877f4ce0c9d29611b126d4179e8d81038fc62` |
| `selected_records/cluster_251.json` | 28,082 | `6dc4317f02dd5bd2bec4ae608beb77b5971676439e8b3c8bcd0ad889fbc41f03` |
| `selected_records/cluster_101.json` | 28,183 | `8d16becd9de7a4411ce17d9f4a5ff77f49292090e73b6e68ea556a20dc78bd56` |
| `memberships/cluster_500.membership.tsv` | 7,717,239 | `5e70b99f82b02002bda1143c7c7216615f10befd34ada7ef67e608f4b2417ed8` |
| `memberships/cluster_251.membership.tsv` | 7,723,215 | `c9298e7f18645668eece836ab64a108eb14a558019af045616bf823cb234ddee` |
| `memberships/cluster_101.membership.tsv` | 7,723,490 | `82cd719c0bba1ccb54f0ee18a8cb103159e6712b19479772d60cfc66d86c65d3` |

Expected accepted summaries are:

| Width | Members | Clusters | Largest cluster | Generation digest |
|---:|---:|---:|---:|---|
| 500 | 361,180 | 174,190 | 231 | `c17b88f6c2c9e631821719265cc0fcc17f1989a649a11cdad53ae42d425053e7` |
| 251 | 361,180 | 259,288 | 65 | `e673e8c11821dbb9e19f62f374078fa6fc210cff86c31bb74d9460b15a9b1096` |
| 101 | 361,180 | 296,182 | 35 | `d94437d807c5ade3e31cca96459dd076aa71ec6dc2cda0d8f437d6f351a5b6c0` |

## Authorized implementation

1. Replace the `legacy_edges.similarity_edges` configuration contract with a
   per-width accepted cluster-membership contract. Bind each membership TSV by
   width, size, SHA-256, selected-record hash, and accepted generation digest.
2. Stream-parse each TSV as exactly two tab-separated fields,
   `representative` and `member`. Require every canonical ID `row_0` through
   `row_361179` exactly once as a member, require every representative to be
   canonical, and reproduce the accepted cluster count and largest-cluster
   size. Missing, duplicate, foreign, malformed, or hash-mismatched evidence is
   a hard failure.
3. Update the legacy diagnostic implementation and schema to calculate the
   per-width cluster-boundary metrics above. Do not retain the misleading old
   field as an alias.
4. Preserve the separately hash-bound exact/reverse-complement evidence and
   the accepted union-component crossing diagnostic unchanged.
5. Bind the three membership files and their selected records into the legacy
   diagnostic fingerprint, selection record, provenance, and final report.
6. Update the Task 002C plan and `docs/SPLITS.md` so all scientific claims use
   the corrected terminology. In the parent plan, explicitly replace the
   obsolete bullet requiring "holdout rows with at least one directly recorded
   Task 002B similarity edge" with the complete per-width cluster-boundary
   metric list in this task. Remove the temporary evidence-correction warning
   once the replacement is made, and update any later checkpoint/final-manifest
   wording that could still imply the retired direct-edge requirement.
7. Add synthetic regressions proving that a transitive A-B-C cluster is
   reported as cluster co-membership and never described as a direct A-C edge;
   also cover all reconciliation and stale-evidence failures.
8. Read and validate the three real returned membership TSVs once. Write a
   small sanitized manifest at
   `manifests/sequence_legacy_cluster_evidence_002c2a.json` containing only
   hashes, sizes, counts, generation digests, reconciliation results, source
   command semantics, and the explicit direct-edge limitation. Do not include
   row-level membership or labels.
9. Replace the impossible production placeholders with the accepted
   membership bindings in this checkpoint's separately reviewed commit.
10. Stop. Do not run `assign`, `legacy_diagnostic`, `exact_audit`, any MMseqs2
    command, or any model/baseline stage.

## Explicit prohibitions

- Do not open the 724-MB dataset CSV, decoded FASTAs, final union membership,
  final component report, model files, predictions, references, or coordinate
  artifacts.
- Do not execute MMseqs2 or regenerate clustering.
- Do not infer direct edges from connected components or cluster memberships.
- Do not copy the three membership TSVs into Git or create a second large
  derivative edge file.
- Do not tune thresholds, grouping, assignment, or resource gates.

## Acceptance gate

- Every frozen file hash and selected-record binding matches.
- Each width reconciles exactly 361,180 canonical members and its accepted
  cluster summary.
- Synthetic tests demonstrate the difference between direct edges and
  transitive co-membership.
- The old `directly_edge_matched_by_width` claim and impossible similarity-edge
  placeholders are gone from production code/config/documentation.
- Exact/RC and union-component diagnostics remain intact.
- The sanitized manifest is small and contains no row-level or label data.
- The worktree contains only intended code, tests, config, docs, and the small
  manifest; the large returned artifacts remain ignored and unchanged.
- Task 002C-2 real assignment has not started.

## What follows after acceptance

Task 002C-2 can then proceed locally in small checkpoints: real assignment and
repeatability first, followed by the former-split diagnostic and independent
exact/reverse-complement audits. Task 002C-3's fresh MMseqs2 searches remain a
separate resource-gated checkpoint.
