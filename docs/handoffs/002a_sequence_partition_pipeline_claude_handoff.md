# Executor handoff — Task 002A sequence-partition pipeline

Claude, implement and verify only checkpoint 002A. Use synthetic fixtures; do
not open the real dataset or construct real partitions.

## Git and required reading

1. Work only on `issue-002-sequence-partitions` from the commit containing this
   handoff. Verify expected origin, clean tracked worktree, and `6fda088` as an
   ancestor. Do not push, merge, or rewrite history.
2. Read, in order:
   - `docs/tasks/002_sequence_clustered_partitions.md`;
   - `docs/reviews/002_sequence_clustered_partitions_reconciliation.md`;
   - `docs/DATA.md`, `docs/DECISIONS.md`, and `CONTRIBUTING.md`.
3. Keep all reusable code in `src/rbpbench/splits/` and fixtures/tests in the
   corresponding test directories. Do not modify coordinate-pipeline behavior.

## Environment gate

Before implementation, confirm Bioconda has the exact osx-64 package
`mmseqs2=18.8cc5c=h8b377d6_0`. If unavailable, stop before installation.
Otherwise create a new isolated environment named `rbpbench-splits-002`; do
not alter `rbpbench-coord-001b` or install globally. Export a reproducible
environment specification and record the resolved binary version and SHA-256.

On a tiny FASTA, prove the installed binary accepts and honors:

```text
createdb: --dbtype 2
cluster:   --alignment-mode 3 --cov-mode 0 -e 1000 --mask 0 -s 7.5
           --cluster-mode 1 --single-step-clustering 1
audit search: --search-type 3 --strand 2 --alignment-mode 3
              --cov-mode 0 -e 1000 --mask 0 -s 7.5
```

`--search-type` and `--strand` are intentionally audit-search-only because the
MMseqs2 clustering workflow does not expose them. Prove clustering is
nucleotide and both-orientation using the type-2 database plus a real-binary
reverse-complement fixture. If any flag is unsupported by the workflow to which
it is assigned, stop and return the exact help/output. Do not silently omit or
replace it.

## Authorized implementation

Implement only:

1. streaming strict one-hot decode into deterministic 500/251/101 center-window
   FASTAs with canonical `row_<index>` identifiers;
2. exact and reverse-complement canonical hashing at all three widths;
3. shell-free MMseqs2 command construction/execution with separate captured
   stdout/stderr, timeouts, hashes, binary identity, and atomic output
   promotion;
4. cluster-membership parsing with complete/unique ID reconciliation;
5. deterministic union-find across the three representations, including
   transitive components and component IDs derived from sorted member IDs;
6. deterministic whole-component 70/15/15 assignment using only known
   positive/known-negative counts after grouping;
7. component-size, balance, minimum-count, and cross-partition audit helpers;
8. deterministic `mtime=0` gzip membership output and sanitized manifest/report
   generation.

The assignment and reporting helpers are fixture-tested in 002A, but no real
partition is created.

## Required tests

Use only tiny synthetic CSV/FASTA fixtures. Cover at least:

- strict decode failures and exact 500/251/101 cropping;
- exact/reverse-complement grouping at every width;
- shifted 500-nt overlap, near-identical 251/101 inputs, unrelated sequences,
  and transitive A-B-C components;
- explicit nucleotide database and audit-search type, reverse-complement
  clustering plus explicit both-strand audit search, true identity,
  bidirectional coverage, permissive E-value, masking disabled, sensitivity,
  single-step graph construction, and connected components against the real
  pinned binary;
- input-order-independent memberships and component IDs;
- missing/duplicate/foreign cluster IDs and external-tool failure;
- no component splitting during balance assignment;
- 70/15/15 targets, 30/30 viability checks, and disclosed balance deviations;
- 5%/20% giant-component gates with diagnostic composition;
- fresh-search audit separation plus tool-independent exact/reverse-complement
  cross-partition detection at all widths;
- deterministic gzip bytes and manifest/input/output hash binding;
- interruption/failure never replacing a prior accepted fixture generation.

Run the complete suite in a clean temporary checkout so ignored real reference
artifacts cannot contaminate coordinate tests. No test may open the real CSV,
source/reference FASTA, B2 FASTA, or prior real artifacts.

## Return and stop

Commit only source, tests, tiny fixtures, documentation, and the isolated
environment specification. Do not commit generated MMseqs databases or large
outputs. Return:

1. commit and changed-file list;
2. environment/package/binary evidence;
3. exact command semantics and real-binary fixture results;
4. focused and full-suite test results;
5. proof that the real dataset and real reference artifacts were untouched;
6. staged-file audit, `git diff --check`, and worktree status;
7. remaining gaps separated into blockers and optional improvements.

Stop after the local commit. End exactly with:

`Task 002B real sequence grouping was not started.`
