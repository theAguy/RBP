# Executor handoff — Task 001B checkpoint B3A

Claude, switch from planning reviewer to executor for **B3A only**. Implement
the reconciled tiny-fixture readiness corrections in
`docs/tasks/001b_b3_hg38_preparation.md`. Do not begin B3B or perform any real
reference/network/genome-scale work.

## Git and required reading

1. Work only on `issue-001b-coordinate-execution` with origin
   `https://github.com/theAguy/RBP.git`.
2. Verify the B2 acceptance commit `e62026b`, B3 plan commit `48d20d0`, and
   this reconciliation/handoff commit are ancestors of `HEAD`.
3. Read, in order:
   - `docs/reviews/001b_b3_reconciliation.md`;
   - `docs/tasks/001b_b3_hg38_preparation.md`;
   - `docs/tasks/001b_coordinate_feasibility_execution.md`;
   - `docs/reviews/001b_b1_acceptance.md`;
   - `docs/reviews/001b_b2_acceptance.md`;
   - `configs/coordinate_execution_sources.toml`.
4. Inspect the current download, derivation, manifest, reference, indexing,
   command, runner, disk-budget, provenance, and test code before editing.

Commit locally on the same branch. Do not push, merge, rewrite history, or
work on `main`.

## Strict authorization boundary

B3A authorizes source/tests/docs changes and pinned real-binary tests only on
tiny synthetic fixtures.

B3A does **not** authorize:

- opening or hashing the real CSV or generated B2 FASTAs;
- any network request or NCBI URL access;
- downloading/reading/deriving a human reference;
- building a human-genome index;
- invoking a mapper or SeqKit on real B2/human data;
- altering frozen source values, contig policy, sampling, mapper parameters,
  thresholds, or resource ceilings;
- deleting the pre-existing ignored dry-run records;
- beginning B3B, B4, B5, B6, or B7.

All downloader tests use injected local transports. Every reference/query in
tests is tiny and synthetic.

## Required B3A implementation

Implement A1–A4 in the reconciled plan literally, including:

1. Exact remote basenames and checksum-first acquisition; structured
   malformed/duplicate/conflicting listing evidence; transactional download
   preservation.
2. Validated `contig_lengths`, total-base agreement, deterministic largest
   contig and tie-break, and CRLF-safe source parsing.
3. One separately authorized build-scoped probe stage with:
   - transactional 10,100-equivalent pattern construction (fixture counts in
     unit tests; exact 10,100 enforced for real mode);
   - streaming largest-contig extraction;
   - deterministic A/C/G/T smoke window;
   - accepted reference/index/B2/commit binding;
   - pinned one-thread BWA/minimap2 smoke and exact SeqKit semantics;
   - SAM and BED6/bounds/duplicate validation;
   - honest zero-hit acceptance;
   - immutable output generation plus protected `probe.json`;
   - persistent provenance and restart revalidation distinct from B4 state.
4. Explicit budgets and retention:
   - at most 1 GiB candidate work from the existing margin;
   - at most 1 GiB combined retained probe outputs/logs, enforced live;
   - 2-GiB whole-run projected-peak reservation;
   - accepted probe bytes included in the same 4-GiB per-build counter used
     by align/exact-match/report;
   - ephemeral reconstructed inputs removed before selection; selected probe
     evidence retained and never deleted in B3A.
5. Persistent ignored log paths under the hg38 artifact tree and cumulative
   provenance; no ephemeral scratch path as the only log location.

Do not weaken existing B1/B2 guarantees or make the probe reuse/overwrite
`align.json`, `exact_match.json`, report state, or combined-report state.

## Minimum regression set

Add focused tests that fail on the pre-B3A implementation for:

1. real-NCBI-shaped `GCF_...` remote basename differing from assembly label;
2. missing, malformed, duplicate, and conflicting checksum entries;
3. checksum-first ordering and no large-file transport after listing failure;
4. download interruption/selection-write failure preserving prior generation;
5. `contig_lengths` key/length/total validation and tied-largest tie-break;
6. LF/CRLF equivalence;
7. probe dry run, authorization/checkpoint combinations, protected prior
   record, candidate interruption, and selection-write failure;
8. missing/changed B2 inputs, invalid reference manifest, and
   missing/foreign/stale/changed index generation;
9. pattern ID/count/hash validation and transactional construction;
10. streaming contig extraction and deterministic valid-window selection;
11. mapper SAM parsing/unmapped/foreign-contig rejection;
12. SeqKit BED6, bounds, known-ID, duplicate-hit, and zero-hit behavior;
13. fingerprint invalidation for B2/reference/manifest/index/binary/command/
    implementation-commit changes;
14. live 1-GiB probe cap, 2-GiB projected check, and downstream shared
    4-GiB budget seeding;
15. selected-vs-ephemeral retention and provenance separation from B4
    align/exact/report/combined state;
16. a guarded real-binary tiny probe integration test when pinned binaries are
    available.

Run the complete suite twice in `rbpbench-coord-001b` with pinned binaries on
`PATH`, plus focused new tests and real-binary smoke counts. Run
`git diff --check` and audit staged files for generated/large artifacts.

## Required return and stop

Return:

1. local correction commit and complete changed-file list;
2. itemized A1–A4 implementation;
3. focused regression names/counts and which fail on the pre-B3A commit;
4. two full-suite results and real-binary test count;
5. budget/fingerprint/restart/retention evidence;
6. `git diff --check`, staged-file audit, and clean-worktree result;
7. confirmation that the real CSV/B2 FASTAs, network, NCBI sources, and human
   reference/index were untouched;
8. every remaining gap without proceeding.

Stop after the local B3A commit. End with exactly:

`Task 001B checkpoint B3B was not started.`
