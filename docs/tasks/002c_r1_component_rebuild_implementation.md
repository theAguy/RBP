# Task 002C-R1 — Components v2 implementation and synthetic proof

## Objective

Implement the small, reusable core needed to rebuild sequence components from
the **same direct MMseqs2 search relation used by the cross-partition audit**.
This corrects the design gap exposed by the stopped Task 002C-3 portable audit
without modifying any accepted v1 evidence.

This is an implementation-and-test checkpoint only.  It does not authorize a
real-data MMseqs2 run, resource probing, component rebuild, partition
assignment, or modelling.

## Background and authority

The v1 assignment is rejected for model evaluation because the direct 500-nt
train-to-validation audit found 4,792 qualifying pairs.  The verified result,
scientific decisions, and later execution sequence are recorded in
`docs/reviews/002c3_cross_partition_failure_and_component_rebuild_plan.md`.
That document is authoritative for the correction boundary.

Existing Task 002B v1 clustering/membership evidence remains historical and
diagnostic.  Do not rewrite it or relabel it as a direct-edge source.

## Frozen relation

At each of the three protected widths, the v2 relation is the output of the
same direct MMseqs2 search predicate as Task 002C's audit:

| Width | Minimum identity | Coverage |
| --- | ---: | ---: |
| 500 | 0.90 | 0.80 |
| 251 | 0.90 | 0.95 |
| 101 | 0.90 | 0.95 |

The command must retain `--search-type 3`, `--strand 2`, `--cov-mode 0`,
`--max-seqs 361180`, `--alignment-mode 3`, `-e 1000`, `--mask 0`, and
`-s 7.5`, with an explicit type-2 nucleotide database.  These are scientific
settings, not resource settings, and are not caller-configurable.

## Required implementation

### 1. Direct-search command builder

Add a new builder for an all-vs-all direct search.  It may reuse the audited
search builder internally, but its public name and docstring must make clear
that it builds the v2 component relation rather than an audit.

Requirements:

- query and target database are explicit arguments; R3 will provide the same
  full-width database for both;
- it uses exactly the frozen audit-search scientific flags;
- it contains no `--single-step-clustering` or cluster-only option;
- unknown widths fail before a subprocess could start; and
- the returned command remains shell-free.

### 2. Strict direct-edge parsing and normalization

Implement a pure-Python, streaming parser for a two-column MMseqs2
`createtsv` result.  For each width it must:

- require exactly two non-empty tab-separated canonical IDs;
- reject malformed, duplicate, missing, or foreign endpoint IDs against the
  supplied full canonical-ID universe;
- discard self-pairs;
- canonicalize every remaining pair as `(min_id, max_id)`;
- collapse duplicate/reversed pairs deterministically; and
- write/read a deterministic, content-hashable normalized edge artifact
  without raw sequences or labels.

The parser must never interpret the older MMseqs2 cluster-membership TSV as a
direct edge list.

### 3. Components v2

Implement a deterministic connected-component constructor that accepts the
normalized direct edges at all three widths and separately supplied exact/RC
edges.  It must:

- require the complete canonical-ID universe exactly once;
- include singleton IDs;
- compute transitive closure across and within widths;
- create component IDs as hashes of sorted member IDs, never tool serials;
- emit deterministic member-to-component membership and a compact summary;
- fail closed on inconsistent/missing width input, malformed edge evidence,
  or an endpoint outside the universe; and
- expose enough metadata for a later runner to bind artifact hashes,
  width-specific counts, and the exact/RC contribution.

Do **not** implement a real-data stage runner, resource gate, all-vs-all
MMseqs2 execution, or Git manifest in this checkpoint.  Design the functions
so R2/R3 can call them without changing the scientific semantics.

### 4. Documentation

Add focused documentation to `docs/SPLITS.md` describing components v2 and
the distinction between:

- v1 MMseqs2 cluster co-membership (historical, not a direct edge list), and
- v2 normalized direct-search edges (the future leakage relation).

Do not revise accepted historical manifests, Task 002B results, or the v1
assignment as though it had passed.

## Required tests

Use synthetic in-memory or temporary fixtures only.  No real CSV, decoded
FASTA, existing ignored artifact, network resource, or MMseqs2 subprocess may
be opened or run.

At minimum test:

1. the v2 command has exactly the audited scientific flags and rejects an
   unknown width;
2. self-pair removal, reverse-order canonicalization, duplicate collapse, and
   deterministic output;
3. malformed rows, extra fields, empty IDs, foreign IDs, and missing/universe
   reconciliation failures;
4. disconnected singleton retention;
5. transitive A-B-C connectivity, including a chain spanning different widths;
6. exact/RC edges joining otherwise disconnected direct-search groups;
7. deterministic component IDs and membership under shuffled edge order;
8. an explicit regression: a synthetic legacy cluster membership omits a
   qualifying A-B direct edge, while components v2 consume the direct edge and
   keep A/B together; and
9. proof that no API accepts a caller-provided identity, coverage, or
   `--max-seqs` override.

Run the focused split tests needed for the new code.  A full repository suite,
real-binary test, and real-data run are out of scope.

## Stop conditions

Stop rather than broadening the task if implementation appears to require:

- changing any frozen threshold or audit acceptance rule;
- treating cluster membership as direct-edge evidence;
- opening real sequence/data artifacts;
- launching MMseqs2 or downloading anything;
- building the v2 full-data runner; or
- changing assignment, audit, model, coordinate, or competitor code.

## Commit and return

Commit only source, focused tests, and documentation.  Do not stage generated
artifacts.  Do not push or merge.

Return the commit hash, changed files, focused test command/results,
`git diff --check` result, staged-file audit, confirmation of the no-real-data
boundary, and any remaining design issue.  End with:

**Task 002C-R2 resource probing and Task 002C-R3 full edge discovery were not
started.**
