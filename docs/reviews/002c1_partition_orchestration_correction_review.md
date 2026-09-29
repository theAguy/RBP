# Task 002C-1 implementation review

## Verdict

**The scientific direction is sound, but Task 002C-1 is not accepted yet. A
single bounded correction is required before any real Task 002C-2 input is
opened.**

Commit `d90bae7` adds the intended separate 002C runner, strict signed-label
parsing, normalized whole-component assignment, deterministic repair, exact
legacy-fold dependencies, exact/reverse-complement grouping, directed MMseqs2
search parsing, transactional candidate directories, and useful synthetic
coverage. The reviewer's focused pure/synthetic run passed 93 tests in 3.20
seconds. Claude's reported larger test runs are credible and no Task 002B
scientific rule was changed.

The remaining findings are acceptance-path defects, not a request to redesign
the project. They must converge in one correction. Do not start Task 002C-2,
open a real CSV/component/result, or run a real-data MMseqs2 command while
correcting them.

Claude disclosed that he listed filenames under the forbidden ignored result
directory while checking scope. No file content was read and the
implementation does not use those paths, so this is recorded as a process
violation but not treated as scientific contamination. Do not repeat it.

## Blocking corrections

### C1 — Bind every frozen input, including the accepted component report

`stage_assign()` verifies only the CSV and two-column component membership.
The configured `dataset_audit.json`, `proteins.tsv`, and accepted Task 002B
component-report hashes are never checked. The component report is not a CLI
input, and `load_component_membership()` is called without the accepted
component-size map. Consequently, a membership with the right row/component
counts but the wrong size distribution can pass, and the runner cannot prove
that all frozen inputs from the Task 002C plan were used.

Correct this by:

- accepting the Task 002B component-report path explicitly;
- resolving the dataset-audit and protein-table paths from an explicit repo
  root, not the process working directory;
- verifying the exact configured size/hash of all five frozen inputs before
  assignment;
- parsing and validating the accepted report's row count, component count,
  component-size map, and passed giant-component result;
- comparing the membership-derived size map exactly with the report; and
- binding every input hash plus the config hash into the assignment record,
  fingerprint, generation manifest, and final manifest.

Validate the configuration schema and the frozen scientific invariants. A
config field must either drive the implementation or be checked against the
reviewed code constant; it may not be silently dead. This includes target
fractions, objective weights, evaluation floor, balance threshold, legacy
fold parameters, protected widths, and resource gates.

### C2 — Make assignment real-scale-safe without changing its science

The selected `assign.json` currently embeds both the 361,180-entry
sample-to-component map and the 173,465-entry component-to-partition map.
Those mappings already exist in the immutable assignment generation and
should not be duplicated in the selection pointer. Downstream stages must
stream/revalidate the generation artifact instead.

The repair swap search can evaluate the Cartesian product of incoming and all
outgoing components, repeatedly recomputing the full scientific tuple. On the
real 173,465-component universe this can become effectively unbounded. The
configuration also declares only accepted repair passes, not a bounded number
of proposals, although the handoff required a fixed pass/proposal bound.

Correct this by:

- keeping large maps in inventoried generation artifacts and storing only
  paths/hashes/counts/digests in the selected record;
- streaming the three-column membership wherever possible;
- building deterministic inverted indexes for label-carrying repair
  candidates instead of scanning all components for every violation;
- adding a fixed, versioned maximum proposal count and counting every tested
  move/swap against it; exhaustion fails closed;
- making swap candidate ordering deterministic and bounded without changing
  the approved lexicographic acceptance tuple; and
- adding a large synthetic sparse-component exercise/profiling assertion that
  demonstrates the real code path does not allocate a dense row-by-label
  matrix or enter an unbounded quadratic sweep.

The assignment universe is exactly protein IDs 1 through 122, not merely the
IDs observed in a fixture. Missing totals must cause an explicit infeasibility
or frozen-input error rather than disappearing from the floor check.

### C3 — Strictly validate and bind every sequence representation

`_read_fasta()` silently overwrites duplicate headers and does not validate
headers, width, alphabet, empty records, or the complete assigned universe.
The exact audit therefore does not implement the promised strict regeneration
boundary. The MMseqs2 path can silently audit a narrowed FASTA, because its
closed universes are derived from whatever records happened to be read.

The directed audit fingerprint also omits the input FASTA hash. A changed
FASTA can therefore reuse an accepted probe/search. Exact-audit fingerprints
bind a FASTA hash, but downstream currency is still based on the assignment
stage fingerprint rather than its exact generation digest.

Correct this by:

- using strict, streaming FASTA/decode validation: unique canonical IDs,
  exact assigned universe, exact requested width, nonempty A/C/G/T-only
  sequence, and no duplicate/foreign/missing ID;
- regenerating the exact/reverse-complement representations through the
  project's strict decode contract for the local exact audit, or proving an
  accepted decode generation has the identical strict contract and binding
  its inventory/digest;
- reconciling the complete FASTA universe before subsetting a directed
  MMseqs2 query/target pair;
- binding the exact FASTA hash/inventory, assignment generation digest,
  config hash, direction, width, and binary identity into every probe/search
  fingerprint and record; and
- reporting exact/RC affected-row counts and a true affected-row denominator
  and rate. Do not label an edge-count divided by total rows as a row rate.

### C4 — Repair restart currency and finalization completeness

The new generation digest is salted with its generation path, but downstream
fingerprints bind only the upstream stage fingerprint. A forced byte-identical
rebuild can therefore leave old downstream evidence apparently current even
though the accepted upstream generation changed. `load_accepted()` also
returns true for a record without a generation directory, which is fail-open.

Finalization requires the assignment, legacy record, three exact audits, and
18 searches, but it does not require any probe record. It does not bind search
records to the probe generation used to authorize them. It also trusts copied
summary fields instead of independently reproducing component integrity,
membership counts, row balance, label floors, and audit completeness.

Use the plan's intended resource-probe shape: **one deterministic bounded
probe per protected width (three total), not 18 direction-specific probes**.
The 18 full scientific searches remain direction-specific. Every full search
must bind the current accepted probe for its width.

Correct this by:

- making a missing generation directory fail closed;
- recomputing every current record from the live config and exact upstream
  generation digests/inventories before run or skip;
- making changed CSV/component report/component membership/config/FASTA/
  binary or a rebuilt upstream generation invalidate exactly the downstream
  records that depend on it;
- requiring and binding three current width probes and all 18 current
  directed searches in finalization;
- independently re-reading the final membership and recomputing the complete
  ID universe, component indivisibility, partition counts, row deviations,
  all 244 evaluation-floor counts, and audit completeness before promotion;
  and
- preserving the prior selected generation byte-for-byte on any candidate or
  selection-record failure.

### C5 — Enforce the configured memory/probe gates

`guarded_exec.py` enforces timeout and disk only. It never checks installed
RAM, available RAM before launch, child peak RSS, the 10-GiB probe peak gate,
or the required post-probe available-memory gate. The corresponding config
fields are currently unused.

Correct this using the already established Task 002B semantics:

- fail closed when installed or available memory cannot be measured;
- require the configured installed-RAM and live available-memory thresholds
  immediately before every MMseqs2 subprocess;
- measure and record peak RSS for the whole guarded attempt;
- fail the width probe if peak RSS exceeds 10 GiB or post-probe available
  memory is below 10 GiB; and
- retain process-group kill, live/final disk checks, timeout, command, binary,
  elapsed-time, and log hashes in provenance.

No resource threshold may be weakened as part of this correction.

### C6 — Make the former-split diagnostic complete, not optional

The legacy stage silently omits a width when `edges_<width>.json` or
`exact_rc_edges_<width>.json` is absent. Finalization only copies the legacy
train/holdout digests, so it can accept a diagnostic with none of the required
component/edge/exact-RC leakage rates.

Correct this by requiring hash-bound evidence for all three protected widths:

- component crossing count/rate and train/holdout crossing-row count/rates;
- directly recorded Task 002B similarity-edge matched holdout count/rate for
  each width, with explicit source artifact provenance; and
- exact/RC affected holdout count/rate and raw pair count for each width,
  regenerated from the strict width representations rather than silently
  treated as optional.

Validate and use the configured legacy fold parameters and dependency
versions. Finalization must include the complete sanitized legacy diagnostic,
not only its two index-set digests.

### C7 — Complete reproducibility evidence

The isolated legacy environment was described in the return but no explicit
environment export/manifest was committed. Add a small reproducible manifest
recording Python and the four exact package versions plus the commands needed
to recreate it. Do not commit the virtual environment itself.

## Required regression evidence

Add focused regressions that fail on `d90bae7` and pass after the correction,
covering at least:

1. missing/tampered dataset audit, proteins table, component report, and
   component-size map;
2. absence of large inline maps from the selection pointer, bounded repair
   proposals, full 1..122 floor universe, and the existing multi-step repair;
3. duplicate FASTA header, wrong width/alphabet, missing ID, changed FASTA,
   and changed/rebuilt upstream generation;
4. missing/stale width probe and one missing/stale directed search at
   finalization;
5. installed/available-memory measurement failure, low pre-launch memory,
   excessive probe peak RSS, and low post-probe memory;
6. missing legacy edge/exact evidence for each individual width; and
7. final independent summary mismatch refusing promotion.

Run the new/changed 002C tests twice. Run the complete 002C test set once with
the intended tiny real-binary tests executing, and the repository-wide suite
once from a clean checkout while disclosing the known unrelated Task 001
failures. **Do not repeat the slow unrelated Task 002B real-binary suite twice**;
the prior return already established it, and this correction must not touch
the Task 002B runner/config.

Commit only code, tests, config, documentation, and the small environment
manifest. Return the commit, changed-file list, itemized C1-C7 resolution,
focused regression proof, test results, diff/staged-file audit, and remaining
gaps. Do not push, merge, access real inputs, or start Task 002C-2.
