# Task 002C-R2 — Components-v2 direct-search resource probe

## Objective

Measure whether the three full all-vs-all direct MMseqs2 searches required for
components v2 are safe and practical on the 64-GiB Apple-Silicon collaborator
Mac. R2 implements a guarded probe, packages it for offline execution, runs
the probe once, and returns a small evidence package with conservative full-run
projections.

R2 does **not** run a full all-vs-all search, build components v2, reassign
partitions, continue the failed v1 audit, or train a model.

## Scientific inputs and immutability

Use the already accepted decoded 500-, 251-, and 101-nt FASTAs. Revalidate
them against `manifests/sequence_decode_002b2.json`. The probe is label-blind:
it may read canonical IDs and sequences only, never the label column,
predictions, coordinates, or partition assignment.

Every probe search must use
`commands.components_v2_direct_search_command()` and therefore the unchanged
frozen relation:

- identity 0.90;
- coverage 0.80 at 500 nt and 0.95 at 251/101 nt;
- `--cov-mode 0 --max-seqs 361180`;
- `--search-type 3 --strand 2 --alignment-mode 3`;
- `-e 1000 --mask 0 -s 7.5`; and
- at most four threads.

No scientific flag is configurable by the probe CLI or package.

## Probe design

Select one deterministic, label-blind set of 10,000 canonical query IDs using
the existing accepted ranking rule. Use exactly the same IDs at all three
widths and record their sorted-ID digest.

For each width, sequentially:

1. create a nucleotide query database from the 10,000-query subset;
2. create a nucleotide target database from the complete 361,180-row FASTA;
3. run the frozen direct search from the subset query database against the
   complete target database;
4. render the result with `mmseqs createtsv`;
5. validate every result endpoint, query membership, target membership, row
   shape, and exact count; and
6. record stage-specific resource and output evidence.

This query-subset/full-target design exercises the complete target database
and measures per-query hit/output density without pretending that a
10,000-by-10,000 search represents the full run. Probe output is resource
evidence only and must never be consumed as components-v2 scientific edges.

The three widths run sequentially. A failed width stops the package without
retry or progression to a later width.

## Measurements and projections

Record separately for database creation, search, and TSV rendering:

- exact command and binary identity;
- exit status and elapsed time;
- peak child RSS when available;
- starting/minimum/ending free disk;
- generation and individual artifact sizes;
- raw result-row count;
- distinct query and target counts;
- per-query hit-count distribution (minimum, median, p95, p99, maximum);
- whether any query reaches the frozen `--max-seqs` ceiling; and
- all retained evidence hashes.

Project the full-width search using query scale
`361180 / 10000 = 36.118`. Database-creation time is reported separately and
is not multiplied as though it were per-query search time. Report both the
linear estimate and a conservative estimate with a 1.5 safety factor for:

- search runtime;
- rendered hit rows/bytes; and
- result/temp/output disk.

Memory is not assumed to scale linearly with query count. Report observed peak
RSS and a conservative 1.5-times envelope, clearly labelled as a projection
rather than a guarantee.

## Proposed gates

The planning review must approve or correct these gates before implementation:

- native arm64 macOS and the accepted MMseqs2 18.8cc5c binary/hash;
- physical RAM at least 64 GiB;
- available RAM at least 24 GiB immediately before every MMseqs2 launch;
- free disk at least 100 GiB before each width and at least 80 GiB throughout;
- probe output/temp ceiling 10 GiB per width;
- two-hour timeout per probe width;
- no MMseqs2 multi-part/override warning, OOM, truncation, or result-cap
  saturation;
- conservative projected peak RSS no greater than 48 GiB;
- conservative projected retained artifacts no greater than 25 GiB total;
- conservative projected wall time no greater than 12 hours per width and
  24 hours across all three widths.

Crossing any gate is a stop for review. It is not permission to reduce
`--max-seqs`, sample the future scientific run, lower sensitivity, change the
similarity thresholds, or omit a width.

## Implementation and package requirements

Implement a restart-safe, transactional probe runner under
`src/rbpbench/splits/`. Unit/integration tests use tiny synthetic fixtures and
fake executables only. The real probe must run through a self-contained
native-arm64 package derived from the already verified portable environment
pattern used for Task 002C-3.

The package must:

- verify its own immutable inventory before reading inputs;
- verify the accepted decode manifest, all three FASTAs, environment lock,
  Python environment, MMseqs2 version/hash, host architecture, RAM, and disk;
- create a new output root and refuse unknown/prior files;
- run the three probes sequentially with live timeout/RAM/disk supervision;
- preserve accepted evidence transactionally;
- stop without retry on any failure;
- exclude FASTAs, raw MMseqs2 databases, and raw result TSVs from the returned
  package; and
- always produce one small SUCCESS or STOPPED return ZIP containing commands,
  logs, resource reports, checksums, sanitized summaries, and selection
  records.

The working bundle may retain large probe artifacts until review. Cleanup is
separately authorized only after evidence acceptance.

## Checkpoint boundary

R2 has two operational steps but one scientific purpose:

1. implement/test/build and independently verify the portable probe package;
2. execute that immutable package once on the 64-GiB collaborator Mac.

The package must never conditionally continue into R3. Even a successful R2
returns its projections and stops. R3 requires a new reviewed authorization.

## Acceptance

R2 is accepted only if:

- all three widths complete under unchanged flags;
- the subset/full-target design and identical query-ID set reconcile;
- all evidence inventories and hashes validate;
- projections and gate outcomes can be independently reproduced from the
  returned summaries; and
- no full search, components-v2 build, assignment, audit, or model stage ran.
