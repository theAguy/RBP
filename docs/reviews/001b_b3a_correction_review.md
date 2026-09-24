# Task 001B checkpoint B3A correction review

## Verdict

**One narrow final correction is required.** Commit `bd1d671` closes the
original B3A-R1 through R7 findings in substance, and the pinned suite passes
(`441 passed`). The accepted real B2 manifest and its three probe inputs also
re-verify successfully: frozen manifest SHA-256, 10,000 biological IDs, and
100 control IDs all match.

Three guarded-path defects remain. Two were independently reproduced against
`bd1d671`; the third is a fail-closed reference-evidence gap. B3B remains
unauthorized.

## Accepted corrections

- The real CLI now binds to the frozen accepted B2 manifest instead of
  caller-supplied hashes and enforces 10,000 plus 100.
- Full index build/path/reference/raw-manifest binding is present.
- Clean Git state is required before probe subprocesses.
- All six retained tool files are hashed and restart-revalidated.
- Candidate cleanup is checked, BED parsing is streamed, and projection and
  available-memory gates are implemented.
- A real-binary test now executes the guarded `stage_probe` path.

## Final blocking findings

### B3A-F1 — accepted and restart fingerprints use different command representations

`stage_probe` fingerprints the actual commands, including the random
generation directory and candidate file paths. The runner's restart
recomputation fingerprints placeholder commands using `REFERENCE`, `READS`,
and `QUERY`. These values can never be equal for an accepted real attempt.

Independent reproduction on `bd1d671` produced an executed probe whose
accepted fingerprint was
`096f428c7595a157008d58d59d26cfeb42baafc6e525d6c66f3b7a7cba8a1909`,
while the current restart representation produced
`1727b6124b4cdfe5701789c346822abc51613c70d8f0959885b15bbcde7cb769`.
The accepted BWA command contained attempt-specific index/query paths; the
restart command was `bwa mem -a -Y -t 1 REFERENCE READS`.

Define one stable command-semantics representation and use it in both places.
Keep exact executed commands separately in resource provenance. Add a true
restart test: a successful guarded attempt followed by an unchanged second
runner invocation must skip without creating another generation; changing
each load-bearing fingerprint input must invalidate that skip.

### B3A-F2 — the shared build budget is not decremented between probe writers

Each tool is capped against `build_budget.remaining_bytes`, but the shared
budget is not charged after BWA or minimap2; it is charged only once at the
end. Therefore several outputs can each fit the same unchanged remainder
while their sum exceeds it. Prior retained probe bytes are also excluded from
the supplied build budget and only added after execution, so retry accounting
can exceed the combined ceiling as well.

Independent reproduction used retained file sizes of 67, 60, 59, and three
zero-byte logs with a 77-byte shared allowance. Every individual writer fit,
the probe was accepted with 186 bytes, and the shared budget ended over its
ceiling. This must be impossible.

Before the first writer, charge/seed every prior retained probe byte into the
same shared counter (or equivalently construct a correctly seeded local
counter). After each tool, immediately charge its stdout plus stderr to both
the probe sub-budget and shared build budget. Do not charge cumulative bytes
again at the end. Add regressions for cumulative multi-writer overflow and a
retry with prior retained probe bytes plus other accepted build outputs.

### B3A-F3 — per-contig lengths are not revalidated against the FASTA

The new reference pass computes only a grand total. Exact keys, positive
values, and total agreement do not prove each accession's declared length.
With three or more contigs, bases can be redistributed between non-largest
contig lengths while preserving the same keys, positivity, grand total, and
largest-contig choice; the probe will accept the false manifest.

Stream an observed `accession -> length` map from the current reference,
detect duplicate/malformed headers, and require exact equality with accepted
`contig_lengths` before selection. Derive `Ltotal` from that verified map.
Add a preserved-total/per-contig-redistribution regression that fails on
`bd1d671`.

## Verification performed

- `git diff --check e3d4bbb..bd1d671`: clean.
- Pinned environment with all three binaries on `PATH`: `441 passed`.
- Accepted B2 manifest verification: no violations; 10,000 biological IDs,
  100 control IDs, raw SHA-256
  `2dbe37bcdad4622e2801d1b42169acd5e2096a4ef6a8625fee99766c52f4e200`.
- No network, NCBI source, human reference, or human index was accessed.

## Gate

Only the final B3A correction handoff is authorized. After its implementation,
the reviewer will rerun the focused reproductions and full suite. B3B-1 and
B3B-2 remain unauthorized until explicit acceptance.
