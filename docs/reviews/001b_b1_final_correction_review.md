# Review of Task 001B checkpoint B1 final convergence correction

## Verdict

**B1 is not accepted yet. One narrow acceptance correction is required.**

Commits `905f0bd` and `1138022` genuinely correct the six final-convergence
areas and the six selection-record failure paths at the point where each
artifact generation is created. The complete suite passes independently.
However, the new transactional report selection is not authoritative through
its downstream consumers: combined reporting, provenance, and cleanup still
read the mutable fixed-path convenience mirrors. A crash or write failure
after `report_state.json` is committed can therefore leave a valid accepted
generation beside stale, partial, or corrupt mirrors that downstream stages
then consume.

B2 remains blocked. This review did not open or hash the real dataset, access
an NCBI URL, download a human reference, create a human-genome index, or run
real mapping.

## Independent verification

- Reviewed both commits against
  `docs/reviews/001b_b1_second_correction_review.md` and the final-convergence
  handoff.
- Ran the complete suite with the isolated environment and pinned binaries on
  `PATH`: **324 passed in 65.59s**.
- `git diff --check b176925..1138022` is clean.
- Reproduced the remaining defect with a tiny synthetic, non-evaluated report:
  after creating a valid accepted report generation, changing only the
  fixed-path `report.json` mirror to invalid JSON makes `stage_combined_report`
  fail with `JSONDecodeError`, while the report JSON selected by
  `report_state.json` remains present and valid.

## Corrections that are now satisfactory

- One live output allowance covers stdout and stderr, with report artifacts
  charged before selection.
- Per-build report members are built in one immutable generation and selected
  by an atomic `report_state.json` record only after reconciliation and budget
  validation.
- Accepted-stage digests are chained downstream and referenced generations are
  retained.
- Derived-manifest and raw reference-manifest evidence is recorded and checked.
- The executable checkpoint boundary permits only one build-scoped stage plus
  optional preflight under real authorization.
- Cleanup resolves the actual Git root, requires derived-reference evidence,
  and verifies report Markdown.
- Selection-record write failure discards the candidate generation for all six
  stages; the follow-up commit supplies the two initially missing acquisition
  regressions.

## Remaining blocker: selected report state is not used downstream

`stage_report` commits `report_state.json` and then writes four fixed-path
mirrors. Those mirror writes are deliberately outside the transaction. That
is safe only if they are optional conveniences, but three downstream paths
still treat them as authoritative:

1. `stage_combined_report` reads `<build>/report.json` and
   `<build>/mappings.tsv.gz` rather than the paths selected by
   `report_state.json`.
2. `_write_provenance` reads/hashes fixed `reference_index.json`,
   `mappings.tsv.gz`, `report.json`, and `report.md` rather than the selected
   generation.
3. cleanup reads the fixed report and validates fixed-path hashes recorded by
   provenance, rather than validating and consuming the selected report
   generation.

This creates a concrete crash window after the atomic pointer commit and
before all mirrors have been refreshed. On restart, report-stage validation
can correctly accept the selected generation and skip rebuilding it, but the
downstream consumer can still fail on, or silently use, an older mirror.

There is a related restart hole: `combined_report_fingerprint()` includes only
the report stage's declared-input fingerprint. A forced same-input report
rerun can select a new report generation without changing that fingerprint,
so a previously completed combined report can be skipped even though its
accepted input generation changed.

### Required correction

- Add one fail-closed loader for an accepted per-build report state. It must
  require `executed: true`, verify every selected artifact hash, verify the
  expected upstream generation digests where applicable, and return the
  selected generation paths.
- Make `stage_combined_report`, `_write_provenance`, and cleanup consume those
  selected paths. Fixed-path mirrors may remain for human convenience, but
  must never authorize, invalidate, or supply a scientific result.
- Include each accepted report state's `generation_digest` in the combined
  report restart fingerprint, and validate report-state evidence before
  deciding that combined reporting may be skipped.
- Keep cleanup's provenance gate, but ensure provenance and cleanup refer to
  the same selected-generation paths and hashes. A stale or missing mirror
  must be irrelevant; changed selected evidence must fail closed.
- Add failure-injection/regression coverage for interruption after
  `report_state.json` commit and between mirror writes, corrupt/missing mirrors
  with a valid selected generation, selected-generation tampering, a forced
  same-input report rebuild invalidating combined-report restart, provenance
  path/hash attribution, and cleanup using the selected report.

## Non-blocking note

The index `generation_digest` hashes the full provenance manifest, including
generation-specific paths and runtime metadata. Consequently a byte-identical
forced rebuild will normally receive a different digest and conservatively
rerun downstream work. That is safe but more expensive than the comment and
unit-test name imply. It may be normalized to immutable content/binding hashes
in this correction if the change is small, but it is not an acceptance
condition and must not broaden the round.

## Acceptance for the narrow correction

- Add focused regressions for every downstream consumer and restart boundary
  listed above; demonstrate that they fail on `1138022` for the intended
  reason.
- Run the complete suite twice with pinned real binaries on `PATH`.
- Run `git diff --check` and audit staged files for generated/large artifacts.
- Do not access the real CSV or any NCBI URL; do not download/index a human
  genome, run real mapping, push, merge, or begin B2.
