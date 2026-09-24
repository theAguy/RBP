# Review of Task 001B checkpoint B1 second correction

## Verdict

**B1 is not accepted yet. A final convergence correction is required.**

Commit `01d98b5` is a strong improvement: live checksum-list verification,
generation-based promotion, index restart revalidation, warning detection,
cleanup receipt preservation, and same-volume coverage are now present. The
complete suite passes independently with the pinned binaries. Nevertheless,
the implementation still does not fully enforce the accepted artifact,
output-cap, dependency, cleanup-root, and checkpoint contracts.

B2 remains blocked. This review did not open or hash the real dataset, access
an NCBI URL, download a human reference, create a human-genome index, or run
real mapping.

## Independent verification

- Reviewed all nine files changed by `01d98b5` against B1-C1–C6 and the
  reconciled Task 001B plan.
- Ran the complete suite with the isolated environment and pinned real
  binaries on `PATH`: **291 passed in 65.59s**.
- `git diff --check 01d98b5^ 01d98b5` is clean.
- Reproduced an output-cap bypass: a subprocess writing 1,000 bytes to stderr
  and zero bytes to stdout is accepted under a 100-byte cap.
- Reproduced a derived-manifest restart hole: after changing the accepted
  manifest bytes, `_verify_derive_evidence_hashes` returns no violation.
- Confirmed from the runner that report/mappings outputs remain fixed-path,
  non-transactional files and report restart skips perform no artifact
  revalidation.
- Confirmed that `--allow-mapping` still permits `sample`/`decode`/`controls`
  together with mapping, and permits `combined_report` together with a real
  build-scoped stage.

## Corrections that are now satisfactory

- The live `md5checksums.txt` listing is acquired through the injected
  transport and compared with both frozen and downloaded MD5 evidence.
- Download, derive, index, align, and exact-match outputs use generation
  directories with an atomic JSON selection record.
- Current download/index/align artifacts are revalidated before relevant
  restart skips.
- Minimap2's literal multi-part warning is rejected.
- Source and derived paths participate in the volume check.
- Cleanup preserves pre-deletion file hashes in its completed receipt and
  detects altered report JSON/mappings evidence.

## Remaining blockers

### B1-F1 — The combined 4-GiB limit still excludes accepted bytes

`_run_tool_to_file` watches only `output_path`; it never counts the paired
stderr file while the process runs or in its final cap check. `stage_align`
subtracts BWA stderr only after BWA has already been accepted, so BWA alone
can exceed the complete allowance through stderr. Minimap2 and SeqKit have the
same hole.

The shared counter also stops at SAM/BED/log files. The per-build compressed
mappings table, reference-index diagnostic, report JSON, and report Markdown
are not charged to or checked against the same 4-GiB allowance, despite the
accepted review explicitly requiring them.

Required:

- use one per-build budget object/counter shared across align, exact-match,
  and report;
- live-count stdout plus stderr for each subprocess, including already
  accepted build artifacts, and terminate when their combined size breaches
  the remaining allowance;
- write report/mappings artifacts to a candidate generation and reject it if
  the complete accepted build-output set would exceed 4 GiB;
- add regressions for stderr-only growth, SeqKit stderr growth, and report or
  mappings output taking the aggregate over the limit.

### B1-F2 — Report replacement and restart state are not transactional

`stage_report` still writes `reference_index.json`, `mappings.tsv.gz`,
`report.json`, and `report.md` directly at fixed accepted paths. A failed or
interrupted forced report retry can therefore replace part or all of a prior
accepted report set.

More seriously, when an earlier report completion already exists, a forced
retry that produces failed reconciliation raises before recording a new
completion but leaves the old completion/fingerprint in state. The failed
retry has already overwritten `report.json`; the next non-forced invocation
sees the old fingerprint as valid and report restart revalidation is hardcoded
to no violations, so it can skip the failed report.

Required:

- make the complete per-build report set one generation selected by an atomic
  report-stage record;
- validate reconciliation and the combined output cap before selection;
- revalidate every selected report artifact before a restart skip;
- invalidate or replace prior completion state atomically with the new
  selected generation;
- test a previously passed report followed by a forced failed retry, process
  interruption between every report member, and a later non-forced retry.

### B1-F3 — Successful same-input reruns do not invalidate downstream work

Stage fingerprints describe declared inputs but not the accepted generation or
record digest. A forced same-input index rerun can select a new generation and
prune the old index while `align` retains the same fingerprint. Align restart
validation checks the *current* index, not the exact index generation/digest
recorded when the accepted mapping was produced. Its recorded old index paths
can therefore disappear while the mapping remains marked current.

The same problem propagates downstream: a new align generation does not change
the exact/report fingerprints, and a new exact-match generation does not
change the report fingerprint. Report can remain stale even when the mapping
artifacts it summarizes changed.

Required:

- give every accepted stage record a stable record/generation digest;
- chain the accepted upstream digest—not only the declared-input
  fingerprint/`executed` boolean—into downstream restart validity;
- have align record and verify the exact index manifest/file-set digest used
  for that mapping;
- do not prune a generation still referenced by an accepted downstream
  record, or retain all dependency evidence needed to reproduce it;
- add forced same-input index→align and align/exact→report regressions proving
  downstream stages rerun or are proven byte-equivalent without stale paths.

### B1-F4 — Manifest evidence is still incomplete

The derived record stores the FASTA hash but not the derived manifest hash.
`_verify_derive_evidence_hashes` checks only that the manifest path exists;
changing its content is accepted as valid restart evidence. This was
reproduced directly.

Claude also correctly reported that the raw reference-manifest file SHA-256
is not stored and compared in index/align/exact-match records. The CLI input
fingerprint notices raw-byte changes, but the accepted records and index
manifest retain only a canonical parsed-content hash. That is insufficient
for the promised auditable binding.

Required:

- record and revalidate the derived manifest SHA-256 and byte size;
- pass the raw reference-manifest SHA-256 into index, align, exact-match, and
  report accepted records and into the index binding manifest;
- compare both raw and canonical hashes downstream;
- add whitespace-only raw-manifest drift and semantic derived-manifest
  tampering regressions.

### B1-F5 — The executable checkpoint boundary is still porous

The new rule limits only the number of build-scoped stages. It explicitly
allows `sample`/`decode`/`controls` with `align`, which can cross B2 sampling
and its review gate directly into real mapping. It also allows
`combined_report` with a real build-scoped stage, although Task 001B requires
the combined report to run as a separate non-mapping invocation after the
per-build report is accepted.

Required:

- under real `--allow-mapping`, permit exactly one build-scoped stage, with
  at most `preflight` as an accompanying stage;
- require `sample`, `decode`, and `controls` to run without real-mapping
  authorization in B2-only invocations;
- require `combined_report` to run without `--allow-mapping` as a separate
  invocation;
- add B2+align and report+combined-report rejection tests that fail before
  CSV access or subprocess execution.

### B1-F6 — Cleanup pinning/evidence still fails open at two boundaries

The cleanup root is supplied by the same user who supplies `--indices-dir`.
Passing an arbitrary directory as both `--repo-root` and the parent of
`--indices-dir` satisfies the equality check, so the CLI has renamed the
shape assertion rather than independently proving the actual repository root.

If `derive.json` is missing or invalid, cleanup sets `reference_path=None` and
continues without the required accepted-reference guard. It also checks only
report JSON and mappings hashes, not the recorded report Markdown or the
derived-reference evidence.

Required:

- resolve the repository root independently (for example, the checked-out
  Git top-level) and refuse a conflicting CLI path; keep root injection only
  at the low-level test boundary;
- require a valid, executed, hash-verified derive record/reference before
  cleanup rather than dropping the guard when it is absent;
- verify every selected report artifact recorded in provenance, including
  report Markdown;
- add arbitrary matched-root/indices, missing derive record, altered derived
  reference/manifest, and altered report-Markdown cleanup regressions.

## Transaction completion requirement

For download, derive, index, align, exact-match, and report, a failure while
writing the atomic selection record currently leaves an unselected generation
behind. Wrap the selection write so failure discards that new generation and
leaves the previous selection untouched. Test this transition directly for
each stage; do not infer it from a failure earlier in generation construction.

## Acceptance for the final convergence round

- Add focused regressions for every B1-F1–F6 and selection-record failure
  above; each regression must fail on `01d98b5` for the intended reason.
- Run the complete suite twice with pinned real binaries on `PATH`.
- Run `git diff --check` and audit staged files for generated/large artifacts.
- Do not access the real CSV or any NCBI URL; do not download/index a human
  genome, run real mapping, push, merge, or begin B2.
