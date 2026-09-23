# Executor handoff — Task 001B checkpoint B1

Claude, switch from second reviewer to implementation executor for **B1 only**.
Implement the readiness layer with tiny synthetic fixtures and the pinned tool
binaries. Do not continue to B2 or any later checkpoint.

## Read before editing

Read these files in order:

1. `docs/tasks/001b_coordinate_feasibility_execution.md`
2. `docs/reviews/001b_coordinate_execution_second_review.md`
3. `docs/reviews/001b_coordinate_execution_reconciliation.md`
4. `docs/tasks/001_coordinate_recovery_feasibility.md`
5. `docs/tasks/001a_coordinate_pipeline_implementation.md`
6. `docs/COORDINATES.md`
7. `docs/DATA.md`
8. `docs/DECISIONS.md`
9. `CONTRIBUTING.md`

Then inspect the merged coordinate runner, command, manifest, preflight,
reference, provenance, report, and existing coordinate tests before designing
changes. The reconciliation accepts every required review item; it is not a
request to re-plan the study.

## Git boundary

- Verify `origin` is `https://github.com/theAguy/RBP.git`.
- Work only on `issue-001b-coordinate-execution`.
- Verify the reconciled planning commit `2d13599` is an ancestor of `HEAD`
  before editing.
- Preserve unrelated user work and do not commit directly to `main`.
- Commit the bounded B1 implementation locally when complete, but do not merge
  or push it. The planning reviewer will inspect it first.

Stop and report any mismatch rather than repairing Git history or substituting
a different branch.

## Authorization boundary

B1 authorizes:

- checking `osx-64` package availability for BWA 0.7.19, minimap2 2.31, and
  SeqKit 2.13.0;
- creating an isolated project environment and installing those exact versions
  inside it;
- implementing the readiness code and documentation required by the reconciled
  task;
- running unit/integration tests and real-binary smoke tests only against tiny
  synthetic reference/query fixtures.

B1 does **not** authorize:

- opening or hashing `dataset_K562_multilabel_with_NEGs.csv`;
- fetching any NCBI human FASTA, assembly report, or checksum listing;
- building an hg38/GRCh38 or hg19/GRCh37 index;
- running any real dataset sampling, decoding, exact search, or mapping;
- changing scientific thresholds, sampling, mapper roles, source assemblies,
  reference policy, or resource ceilings.

The NCBI URLs may appear in the checked-in execution-source specification, but
must not be requested during B1.

## First stop check

Before implementation, query the isolated package channels for exact `osx-64`
availability. If any exact version is unavailable, stop immediately and return
the solver/channel evidence. Do not silently substitute a version, source
build, container, or global installation.

## Required B1 implementation

Implement every item under **Required readiness work before real downloads**
and the B1 checkpoint in the reconciled task, including:

1. `configs/coordinate_execution_sources.toml` (or a clearly justified
   equivalent) containing the frozen four local-input hashes, both reference
   sources, authoritative sizes/MD5s, and derived-reference policy.
2. Fail-closed expected-versus-observed local-input verification that runs
   before the real CSV can be opened. Tests must use fixture paths and fixture
   hashes; do not access the real CSV in B1.
3. Restart-safe download/checksum logic and streaming assembly-report/FASTA
   derivation, tested only with local tiny fixtures and a local fake downloader
   or injected transport.
4. Build-specific BWA-prefix and minimap2-index preparation/use, creation-time
   index manifests, single-part and `k=15/w=5/non-HPC/-I 8G` checks, reference
   binding, and stale/foreign-index rejection.
5. Separate, hashed external-tool stdout/stderr evidence; never discard stderr.
   Parameter-override and multipart-index warnings must fail closed.
6. Exact-match/report reference binding, complete restart fingerprints,
   protection of prior `executed: true` records, and atomic successful record
   replacement.
7. Exactly-one-build enforcement for `--allow-mapping`, nonzero failed
   reconciliation, the disk-budget ledger/checks, narrow cleanup guards, and
   the required `.gitignore` additions.
8. Real BWA/minimap2/SeqKit smoke tests on tiny fixtures. The SeqKit fixture
   must test BED6, both strands once, no double counting, and an
   `--ignore-case` match spanning lowercase and uppercase reference bases.
9. Updated user/execution documentation and a reproducible exact environment
   export recording package builds, channels, binary versions, and binary
   SHA-256 hashes.

Do not create a convenient `--stage all` real-execution path around the
checkpoint gates. Any cleanup test must operate only in a newly created tiny
temporary directory and must prove refusal of symlinks and unsafe targets.

## Verification

- Run the complete existing and new test suite under the isolated Python 3.11
  environment.
- Run focused regressions for every R1–R12 finding.
- Run the real installed binaries only on tiny synthetic fixtures.
- Run `git diff --check` and confirm no generated environment, binary, FASTA,
  index, SAM, BED, compressed mapping table, or other artifact is staged.
- Confirm all tests are stable on at least two consecutive full-suite runs.

## Return and stop

Return the eight evidence items required by the task's **Executor return at
every checkpoint** section, plus:

- the exact commit hash and changed-file list;
- package-availability and isolated-environment evidence;
- separate counts for unit tests, focused R1–R12 regressions, and real-binary
  tiny smoke tests;
- explicit confirmations that the real CSV was not opened and no NCBI human
  reference URL was requested.

Stop after the local B1 commit. End the handoff with this exact sentence:

`Task 001B checkpoints B2–B7 were not started.`
