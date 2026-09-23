# Planning review — Task 001B checkpoint B1 implementation

## Verdict

**Do not accept B1 yet; corrections are required.**

Commit `dda805f` is a substantial implementation and its complete suite passes
with the pinned real binaries. However, several promises from the reconciled
plan remain unenforced at the exact restart/cleanup boundaries that B1 was
created to close. These are correctable implementation defects, not changes to
the scientific design.

B2 remains blocked. This review did not open or hash the real CSV, request an
NCBI reference URL, build a human-genome index, or run real mapping.

## Verification performed

- Inspected all 24 changed files in `dda805f` against the reconciled task and
  R1–R12 findings.
- Ran the complete suite with the isolated environment and its binaries on
  `PATH`: **230 passed**.
- Ran `git diff --check`: clean.
- Reproduced the disk-ledger arithmetic defect directly: after cumulative
  snapshots of 5 GiB and 6 GiB since baseline, `observed_new_gib` reports 11
  GiB although the actual current increase is 6 GiB.

## Blocking corrections

### B1-R1 — Exact-match/report reference binding is still missing

`exact_match_fingerprint` and `report_fingerprint` still chain only from prior
stage state. They do not include the current reference or manifest hash.
`stage_exact_match` validates the current manifest against the current FASTA,
but never compares that FASTA with `align.json`'s recorded reference hash.
`stage_report` likewise uses the CLI reference for junction lookup without
checking it against alignment and exact-match provenance.

Consequently, a forced exact-match/report invocation can combine mapping from
reference A with exact matches or junction diagnostics from reference B. This
is the original second-review R3 failure, not existing 001A coverage.

Required:

- include current reference and manifest hashes in exact-match and report
  fingerprints;
- fail closed unless exact-match's reference hash equals alignment's recorded
  reference hash;
- fail closed unless report's reference hash equals both alignment and
  exact-match recorded hashes;
- add full runner regressions for forced mismatches and non-forced invalidation.

### B1-R2 — Index manifests do not bind an index to its reference

`index_manifest.json` records index-file hashes and a command string, but not
the reference FASTA SHA-256, reference-manifest hash, frozen parameter payload,
or resolved tool version. Alignment verifies that files match whichever index
manifest is found; it never proves that this index was built from the current
reference.

The CLI overrides deepen the hole: the BWA prefix and minimap2 index may come
from different directories, and neither supplied path is checked against the
paths recorded by the manifest being verified. A replaced index plus replaced
manifest can also pass because the index-manifest content hash is absent from
alignment restart validity.

Required:

- bind each index manifest to reference SHA-256, raw reference-manifest
  SHA-256, exact frozen index parameters, binary version/hash, and build;
- require each actual BWA/MMI path to equal the corresponding recorded path;
- either prohibit overrides for real Task 001B execution or validate each
  override against its own bound manifest;
- include index-manifest content hashes in alignment fingerprints;
- test a valid foreign index built from a different FASTA, same-sized
  replacement index/manifest, and split-directory overrides.

### B1-R3 — Accepted evidence can still be destroyed by a failed retry

`_guarded_write_record` protects only dry-run/basic-authorization branches.
An authorized attempt that fails manifest validation, preflight, index
validation, or upstream-stage availability still writes `executed: false`
over a prior `executed: true` record. This contradicts the reconciled task,
which explicitly includes failed preflight and missing-index attempts.

There is a second, more serious path: mapper outputs and index files are opened
at their final locations. A failed rerun can truncate/partially replace SAM,
BED, log, or index files while the old accepted JSON record remains.

Required:

- no non-executed outcome may overwrite prior executed evidence; record failed
  attempts separately;
- write mapper/exact outputs and complete index sets into attempt-specific
  temporary locations, validate/hash everything, then atomically promote a
  successful set;
- preserve the prior accepted record and artifacts on subprocess failure,
  timeout, disk stop, failed preflight, stale manifest, or invalid index;
- add regressions for every failure class, including failure after BWA succeeds
  but before minimap2 completes.

### B1-R4 — The 30-GiB mechanism is not correct or persistent

`DiskBudgetLedger.observed_new_gib` sums cumulative “since baseline” values,
double-counting every later snapshot. The baseline is recreated for every
runner invocation, although B2–B6 are intentionally separate invocations, so
files retained from earlier checkpoints disappear from the accounting.

The 4-GiB build-output allowance is pre-checked once for align and again for
exact match; no writer actually enforces a combined size ceiling or stops a
growing file. Download and derivation are not connected to the ledger, and
volume identity/baseline state is not durably resumed across checkpoints.

Required:

- use the current/latest (or maximum conservative) delta from the persisted
  baseline, never the sum of cumulative deltas;
- persist one baseline/volume ledger for the complete B1–B6 study and reload it
  on every invocation;
- account for every pinned path/volume and reject unexpected cross-volume
  placement unless separately budgeted;
- check downloads, derivation, indices, mapping, and exact-match against the
  same ledger;
- enforce the combined per-build output allowance while writing, terminate on
  breach, mark the attempt unusable, and preserve prior accepted artifacts;
- add sequential-step, cross-invocation, deletion, external-volume, and actual
  output-growth tests.

### B1-R5 — Cleanup is not yet safe or auditable

The CLI calls `execute_index_cleanup` before printing the deletion list, so the
required preview occurs after deletion. It passes `reference=None`, accepts an
arbitrary `--indices-dir`, and checks only JSON booleans—not that mapping files
exist and match recorded hashes.

Cleanup also removes `index_manifest.json`, index logs, preflight evidence, and
`index.json`. Top-level provenance embeds only the shallow index record/path,
not the detailed index manifest, so cleanup destroys the only complete index
provenance. No durable cleanup receipt is written.

Required:

- implement a two-step preview/confirm API, with preview persisted and printed
  before deletion;
- prove the target is exactly the pinned repository `indices/<build>/`, pass
  and guard the real reference path, reject symlinked components, and refuse
  arbitrary roots;
- verify the index manifest and every required mapping/exact/report artifact
  and recorded hash before deletion;
- copy/embed complete index provenance outside the disposable directory before
  cleanup, then write a durable receipt containing the preview list, hashes,
  confirmation, completion status, and timestamp;
- test that fabricated `executed: true` booleans or missing/changed artifacts
  cannot authorize deletion.

### B1-R6 — Production hash verification and checkpoint gates are optional

`--execution-sources` is optional, so the runner still opens any CSV when the
flag is omitted. The executable therefore does not itself guarantee B2's
frozen-hash gate.

Separately, `--allow-mapping --build hg38` with no `--stage`, or with
`--stage all`, still expands to the full stage list. That can cross index,
mapping, exact-match, report, and combined-report gates in one invocation.

Required:

- make an execution-source specification mandatory for runner data access;
  fixture tests must supply a fixture spec rather than relying on a production
  bypass;
- reject `--allow-mapping` when stages are omitted or `all` is requested;
- require an explicit allowlist of stages compatible with the active
  checkpoint, and test that a single invocation cannot cross gates.

### B1-R7 — Reference acquisition/derivation is not an executable guarded path

The downloader and derivation functions exist, but no checked-in runner/CLI
workflow connects them to the execution-source spec, authoritative byte size,
live checksum-list agreement, persistent disk ledger, restart state, and
manifest output. B3 would therefore require ad hoc Python or new implementation
while supposedly executing an already-reviewed checkpoint.

Derivation writes directly to the final FASTA, so a failed derivation can
destroy a prior valid file while leaving an older manifest behind. The
downloader does not itself check authoritative byte size or checksum-list
content.

Required:

- provide guarded, restart-safe, documented acquisition and derivation CLI
  stages now, tested with injected/local transport only;
- validate live checksum-list entry, authoritative byte size and MD5, then
  record local SHA-256;
- derive to a temporary file, validate all contigs/lengths/categories and
  manifest content, then atomically promote FASTA plus manifest;
- wire both stages into the persistent disk ledger and checkpoint state.

### B1-R8 — Mapping warnings and failed-report state are accepted incorrectly

Mapper stderr is captured, but minimap2 mapping stderr is never inspected for
the required “indexing parameters overridden” or multipart-index warnings.
Capturing a disqualifying warning is not equivalent to stopping on it.

When report reconciliation fails, the runner marks the report stage complete
before exiting nonzero. A later non-forced invocation with the same fingerprint
can therefore skip the failed report.

Required:

- inspect minimap2 mapping stderr before accepting/promoting output and stop on
  either disqualifying warning;
- never mark a failed reconciliation stage complete;
- add regressions for both paths.

### B1-R9 — Masking classification overstates what base counts establish

Lowercase bases establish soft masking. In contrast, an `N` fraction above 1%
does not establish hard repeat masking; assembly gaps can produce the same
observation. The current heuristic may therefore label an uppercase assembly
with ordinary gaps as `hard` without evidence.

Required: retain raw uppercase/lowercase/ambiguous counts, report `soft` when
lowercase is observed, and otherwise use `none_detected` or `unknown` unless
authoritative source metadata establishes hard masking. Do not state as fact
that the NCBI source is soft-masked before B3 measures it.

## Additional provenance correction

Index-building provenance currently resolves binaries with `version=None`.
Record the actual detected pinned version in each index tool record. Persist
the complete, cumulative provenance across checkpoint invocations rather than
overwriting earlier build/disk evidence with only the current invocation.

## Acceptance for the correction round

- Add regression tests that fail on `dda805f` for every item above.
- Run the complete suite twice with real pinned binaries on `PATH`.
- Return targeted regression counts separately from the full suite.
- Do not access the real CSV or any NCBI human-reference URL.
- Stop after a local correction commit; do not push, merge, or start B2.
