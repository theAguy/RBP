# Task 002C-2A planning review request

## Reviewer role and boundary

Act as the second scientific/methodological reviewer for
`docs/tasks/002c2a_legacy_cluster_evidence.md`. Review the plan only. Do not
edit code, open the real membership TSVs, open the dataset CSV or FASTAs, run
MMseqs2, execute assignment, or start Task 002C-2A.

This review is deliberately bounded. The goal is to correct one unsupported
scientific label and unblock local partition work without recreating Task
002B or expanding the project.

## Finding to review

The accepted Task 002B return retained three MMseqs2 cluster-membership TSVs
and their selected records, but not the internal alignment-result databases.
MMseqs2 documents the TSV columns as cluster representative/member and
connected-component clustering as breadth-first reachability. Therefore the
TSV can prove per-width cluster co-membership, including transitive
relationships, but cannot prove that every representative/member pair is a
direct accepted alignment.

The proposed correction removes the promised direct-edge diagnostic and
replaces it with per-width legacy train/holdout cluster-boundary counts and
rates. The later fresh Task 002C-3 directed searches remain the direct
pairwise zero-hit test for the new split.

## Questions requiring an explicit answer

1. Is it correct that `createtsv` output from a connected-component cluster DB
   is membership evidence rather than a complete/direct similarity-edge list?
2. Does the proposed per-width crossing-cluster diagnostic make an honest and
   useful statement about leakage in the former split without overstating
   direct pairwise similarity?
3. Are the requested denominators sufficient: crossing clusters over clusters
   represented in holdout, affected holdout rows over all holdout rows, and
   affected train rows over all train rows?
4. Is direct streaming use of the accepted membership TSVs preferable to
   producing three redundant JSON "edge" derivatives?
5. Are the source hash, selected-record, generation-digest, closed-universe,
   cluster-count, and largest-cluster checks sufficient to bind the evidence?
6. Does one implementation-and-validation checkpoint, stopping before CSV
   access and assignment, remain appropriately bounded, or is there a genuine
   scientific reason it must be split further?
7. Identify only blocking correctness issues. Optional engineering refinements
   should be deferred.

## Requested verdict

Return one of:

- **Approve**;
- **Approve with bounded corrections**; or
- **Stop**, naming the precise scientific blocker.

For every correction, state the concrete false conclusion or integrity failure
it prevents. Do not propose rerunning Task 002B, retaining its internal MMseqs2
databases, adding another clustering tool, changing thresholds, running
assignment, or beginning model work.
