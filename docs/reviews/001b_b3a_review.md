# Task 001B checkpoint B3A implementation review

## Verdict

**Changes required.** Commit `1f14adc` is a substantial and generally clean
implementation, and A1 plus the derivation half of A2 are accepted. The full
pinned-environment suite passes (`401 passed`), but the guarded probe path does
not yet enforce several requirements that its helper-level tests claim to
cover. B3B remains unauthorized.

No real CSV, B2 FASTA, NCBI source, human reference, or human index was opened
or executed by this review.

## Accepted work

- Exact URL-basename handling, checksum-first ordering, and structured
  malformed/duplicate/conflicting checksum evidence are correct.
- Transactional download preservation is retained.
- Derived manifests now contain deterministically validated
  `contig_lengths`, including the accepted ascending-accession tie-break.
- LF/CRLF handling and the generalized Git provenance helpers are reasonable.
- The probe has the right broad shape: separate stage/state, generation-based
  outputs, one-thread mapper smoke, one SeqKit invocation, and no B4 state
  mutation.

## Blocking findings

### B3A-R1 — the probe is not bound to the accepted B2 checkpoint

`stage_probe` trusts caller-supplied FASTA paths and caller-supplied expected
hash strings. A caller can provide any two FASTAs and their matching hashes;
the stage then calls `build_pattern_fasta` without expected ID sets or counts.
The successful integration fixture proves that two biological records plus
one control are accepted, although real mode must require exactly 10,000 plus
100.

The real CLI must consume and validate the committed accepted B2 manifest,
not accept free-form hashes as the trust anchor. It must verify the manifest's
accepted identity/status and its sample IDs, sample FASTA, and control FASTA
paths, sizes, hashes, counts, and exact expected ID sets. Real CLI mode must
fail unless the pattern population is exactly 10,000 biological plus 100
controls and agrees with accepted B2 evidence. Tiny counts may remain possible
only through an explicit test-only/direct-function seam that the CLI cannot
activate. The accepted manifest is
`manifests/coordinate_sampling_b2.json` as committed at `e62026b`, with raw
SHA-256 `2dbe37bcdad4622e2801d1b42169acd5e2096a4ef6a8625fee99766c52f4e200`.

### B3A-R2 — reference and index binding is incomplete

The probe checks only that `contig_lengths` is nonempty. It does not validate
exact key equality with `contigs`, positive integer values, or total-base
agreement before selecting the largest contig.

`_verify_index_record_for_probe` receives `build` but never uses it. It hashes
the files and compares two values copied from `index.json`, but does not verify
the selected index manifest's build, raw reference-manifest hash, or current
content-derived generation digest. Use the existing full index-binding logic
for both BWA and minimap2, including actual paths, build, reference hash,
canonical manifest hash, raw manifest hash, and recomputed generation digest.

### B3A-R3 — restart validity does not match the accepted fingerprint contract

The runner-level `probe_restart_fingerprint` omits the expected B2 evidence,
current binary hashes/versions, command semantics, current implementation
commit, and clean-tree state. The helper `probe_fingerprint` is sensitive to
some of these in isolation, but it is calculated only after execution and is
not recomputed/compared when the runner decides to skip an accepted probe.
It also omits the raw reference-manifest hash.

Require a non-null commit and a clean tree before any real probe subprocess.
Build one stable, reproducible fingerprint contract and use it both for the
accepted record and restart revalidation. A change in accepted B2 evidence,
reference/raw manifest, exact index generation, any resolved binary,
command/parameter semantics, or implementation commit must force
revalidation/re-execution rather than a skip.

### B3A-R4 — retained evidence is only partially protected

The accepted generation retains six tool files, but restart revalidation and
`generation_digest` cover the three stdout files only. Altering or removing a
retained stderr log can therefore remain silently accepted, even though
minimap2 stderr is load-bearing evidence.

Hash, size, and revalidate all six retained files and include all six in the
generation digest. Candidate cleanup must be verified: the current
`shutil.rmtree(..., ignore_errors=True)` may select a generation while the
supposedly ephemeral pattern/contig/query files remain. A failed cleanup must
discard the candidate and preserve the prior accepted record. Also account
for every retained superseded probe generation, or handle it under an
explicitly reviewed non-destructive retention policy; selected-byte
accounting must not silently ignore retained old bytes.

### B3A-R5 — the two disk caps are not actually enforced together

The candidate workspace receives a projected check but no live/observed
1-GiB cap. The probe's tool writers use a fresh 1-GiB counter without limiting
it to the remainder of the shared 4-GiB build budget. `build_budget.accept()`
only increments after all tools finish and does not reject overflow. Thus a
probe can exceed the shared 4-GiB ceiling when other accepted build outputs
already consume part of it.

Enforce candidate bytes during construction and before every subsequent
writer. For retained output, every tool's live limit must be the smaller of
the probe's remaining 1-GiB share and the shared build budget's remaining
bytes. Refuse before selection if either counter would be exceeded.

### B3A-R6 — the real probe can exceed memory and cannot apply the projection gates

`seqkit_bed.read_text().splitlines()` loads a file allowed to approach 1 GiB
and creates additional copies. BED validation must stream line by line.
Validate BED6 strand and score semantics as well as column count, IDs, bounds,
and duplicate keys.

The recorded host-memory snapshots contain physical RAM only; there is no
measured available/reclaimable memory. The accepted wall/output/memory
projection formulas and stop decisions are also absent. Record `Lmax`,
`Ltotal`, scale, observed SeqKit wall/RSS/output/hits, the accepted 1.5x and
2x projections, zero-hit limitation, available/reclaimable memory at probe
start, and explicit pass/fail results for the 4.5-hour, provisional 1-GiB,
and peak-RSS-plus-2-GiB gates. A failed or unavailable gate must prevent probe
acceptance.

### B3A-R7 — integration coverage overstates the guarded path

The real-binary test exercises probe building blocks directly, not
`stage_probe` through its authorization, fresh preflight, binding, budget,
transaction, and selected-record path. Add a real-binary tiny integration
test through the guarded stage. Add end-to-end regressions for R1-R6 that
demonstrably fail on `1f14adc`; helper sensitivity alone is not sufficient.

## Verification performed

- `git diff --check a63a2ba..1f14adc`: clean.
- Pinned environment with its binaries on `PATH`: `401 passed`.
- Without the environment bin directory on `PATH`: the five disclosed older
  fixture failures reproduce (`383 passed, 13 skipped, 5 failed`). This is
  not treated as a new B3A regression, but the official verification command
  must continue to state the required environment explicitly.
- Worktree was clean before this review documentation was added.

## Gate

Claude may implement only the bounded B3A correction handoff. B3B-1 and
B3B-2 remain unauthorized. Acceptance requires focused regressions that fail
on `1f14adc`, two clean full-suite runs in the pinned environment, and a new
review.
