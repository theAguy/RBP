# Task 001B checkpoint B2 acceptance

## Verdict

**Checkpoint B2 is accepted. Checkpoints B3–B7 remain unstarted.**

Commit `85ea50a` records a successful, reconciled real-dataset sampling,
decoding, and control-generation checkpoint. This acceptance authorizes
planning/review of B3 only; it does not itself authorize a reference download,
human-genome indexing, mapping, or exact search.

## Independent acceptance evidence

- Reviewed `manifests/coordinate_sampling_b2.json` and the ignored artifacts
  selected by it.
- Recomputed and matched all **13** recorded hashes/byte sizes: execution
  source specification, four frozen inputs, six generated artifacts, and two
  captured logs.
- Independently streamed the real CSV and verified all **10,000** selected
  decoded sequences re-encode exactly to their source bit strings, with zero
  mismatches.
- Confirmed the committed manifest is the only file changed by `85ea50a`,
  `git diff --check` is clean, and the worktree is clean.

## Accepted B2 reconciliation

- Biological assignments: **10,000 unique**.
- Strata: **5,000 representative**, **626 quota**, **4,374 filler**; the sets
  are pairwise disjoint, their union is the sample, and assignment labels
  agree with the recorded sets.
- Protein quotas: all 122 proteins have at least 20 known positives and 20
  known negatives; observed minima are **25 positive** and **23 negative**.
- Decoded FASTA: **10,000 unique IDs**, exactly equal to the sampled IDs; all
  sequences are 500 nt, A/C/G/T-only, and pass strict source round-trip.
- Controls: **100 unique IDs and 100 unique sequences**, tied to the
  deterministic first 100 sorted representative IDs; every control is 500 nt,
  A/C/G/T-only, differs from its paired biological sequence, and preserves
  the exact dinucleotide multiset.
- Runner state contains only `sample`, `decode`, and `controls`.
- Provenance hashes match the current artifacts and records no executed
  download, derivation, index, alignment, or exact-match stage.
- Runtime was approximately 46.4 seconds with about 805 MiB peak RSS; generated
  artifacts total approximately 6.9 MiB and free disk remained far above the
  80-GiB floor.

## Non-blocking operational note

The B2 stdout and timing/stderr logs were captured under a temporary Claude
scratch directory. Their hashes still matched during acceptance, stdout is
empty, and the relevant timing/resource values are preserved in the committed
manifest, so this does not block B2. Beginning with B3, acquisition, indexing,
probe, and tool logs must be stored under the persistent ignored
`artifacts/coordinate_feasibility/` tree rather than an ephemeral temporary
directory.

The dry-run `indices/hg38/index.json` and `indices/hg19/index.json` records
predate B2 and were not modified by it. They are not accepted real index
evidence and must never be adopted by B3; the guarded B3 index stage must
replace them only after real reference preparation and validation.

## Next checkpoint boundary

B3 is hg38 preparation only: fresh resource checks, verified GRCh38.p14 source
acquisition, deterministic filtered-reference derivation, build-specific BWA
and minimap2 indexing, tiny real-tool smoke mapping, and the largest-contig
SeqKit feasibility probe with all 10,100 patterns. B4 full-reference execution
remains prohibited until B3 evidence is independently reviewed and accepted.
